"""Experimental LAN Takion server. IPv4, one 720p60 H.264 test stream per profile."""
import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import struct
import sys
import time
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from google.protobuf.message import DecodeError
from crypto import GK
from media import prepare, prepare_audio
from input import Controller
from fec import parity
sys.path.insert(0, str(Path(__file__).parent/'build'))
import takion_pb2 as pb

class Connection:
    def __init__(self, server, addr, active, peer_tag, seq):
        self.server, self.addr, self.active = server, addr, active
        self.peer_tag = peer_tag
        self.tag = secrets.randbelow(0xfffffffe)+1
        self.seq = self.tag
        self.expected = seq
        self.cookie = secrets.token_bytes(32)
        self.ready = False
        self.fragment = bytearray()
        self.waiting = {}
        self.rx_queue = {}
        self.tx = self.rx = None
        self.position = 0
        self.video_index = 0
        self.task = None
        self.audio_task = None
        self.prepare_task = None
        self.source_started = False
        self.controller = Controller()
        self.last_input = time.monotonic()
        self.last = time.monotonic()
        self.bang = False
        self.plain_bang_ack = None
        self.closed = False

    def close(self):
        if self.closed: return
        self.closed = True
        if self.task: self.task.cancel()
        if self.audio_task: self.audio_task.cancel()
        if self.prepare_task: self.prepare_task.cancel()
        if self.source_started: self.server.source.end()
        self.controller.reset()
        for crypt in (self.tx,self.rx):
            if crypt: crypt.close()
        self.waiting.clear()
        self.rx_queue.clear()

    def send(self, data):
        self.server.transport.sendto(data, self.addr)

    def sign(self, packet, position, mac_offset=5, pos_offset=9, control=True):
        packet = bytearray(packet)
        packet[mac_offset:mac_offset+4] = bytes(4)
        if self.tx:
            saved = packet[pos_offset:pos_offset+4]
            if control: packet[pos_offset:pos_offset+4] = bytes(4)
            mac = self.tx.mac(bytes(packet), position)
            packet[pos_offset:pos_offset+4] = saved
            packet[mac_offset:mac_offset+4] = mac
        return bytes(packet)

    def control(self, kind, payload=b'', flags=0, reliable=False, plain=False):
        pos = self.position if self.tx and not plain else 0
        if self.tx and not plain: self.position += ((len(payload)+31)//16)*16
        packet = b'\0' + struct.pack('!I4sIBBH', self.peer_tag, bytes(4), pos, kind, flags, len(payload)+4) + payload
        if not plain: packet = self.sign(packet, pos)
        self.send(packet)
        if reliable:
            self.waiting[struct.unpack_from('!I',payload)[0]] = [packet,time.monotonic(),0]

    def message(self, msg, plain=False):
        data = msg.SerializeToString()
        payload = struct.pack('!IHHB', self.seq, 1, 0, 0) + data
        self.seq = (self.seq+1)&0xffffffff
        self.control(0,payload,flags=1,reliable=True,plain=plain)

    def ack(self, seq):
        self.control(3,struct.pack('!IIHH',seq,0x19000,0,0))

    def receive(self, packet):
        self.last = time.monotonic()
        typ = packet[0] & 15
        if typ != 0:
            if self.server.probe and typ == 3:
                self.send(packet)  # Senkusha RTT and upstream MTU echo.
            elif self.rx and typ in (1,6):
                # Feedback has its own layout: key position @4, GMAC @8.
                if len(packet) < 12: return
                pos = struct.unpack_from('!I',packet,4)[0]
                clean = packet[:8]+bytes(4)+packet[12:]
                if not hmac.compare_digest(self.rx.mac(clean,pos),packet[8:12]): return
                payload = self.rx.crypt(packet[12:],pos+16)
                seq = struct.unpack_from('!H',packet,1)[0]
                self.controller.receive(typ,seq,payload)
                self.last_input = time.monotonic()
                if self.server.source: self.server.source.input(self.controller)
                self.server.input_observed.update(self.controller.observed)
                self.server.feedback_packets += 1
            return
        if len(packet) < 17: return
        tag, mac, pos, kind, flags, size = struct.unpack_from('!I4sIBBH',packet,1)
        if len(packet) != size+13 or size < 4: return
        payload = packet[17:]
        if kind == 1:
            self.control(2,struct.pack('!IIHHI',self.tag,0x19000,100,100,self.tag)+self.cookie,plain=True)
            return
        if tag != self.tag: return
        if kind == 10 and hmac.compare_digest(payload,self.cookie):
            self.ready = True
            self.control(11,plain=True)
            return
        if not self.ready: return
        if self.rx:
            # ACK of the unencrypted BANG may race client key installation.
            clean = packet[:5]+bytes(8)+packet[13:]
            if not hmac.compare_digest(self.rx.mac(clean,pos),mac):
                if not (kind == 3 and len(payload) >= 12 and mac == bytes(4) and self.plain_bang_ack is not None and struct.unpack_from('!I',payload)[0] == self.plain_bang_ack):
                    return
                self.plain_bang_ack = None
        if kind == 3 and len(payload) >= 12:
            acked = struct.unpack_from('!I',payload)[0]
            for seq in list(self.waiting):
                if ((acked-seq)&0xffffffff) < 0x80000000:
                    del self.waiting[seq]
            return
        if kind != 0 or len(payload) < 8: return
        seq, channel, _ = struct.unpack_from('!IHH',payload)
        delta = (seq-self.expected)&0xffffffff
        if delta >= 0x80000000:
            self.ack((self.expected-1)&0xffffffff)
            return
        if delta > 64: return
        self.rx_queue.setdefault(seq,(flags,payload[8:]))
        while self.expected in self.rx_queue:
            flag, data = self.rx_queue.pop(self.expected)
            self.ack(self.expected)
            self.expected = (self.expected+1)&0xffffffff
            if not self.fragment:
                if not data or data[0] != 0: continue
                data = data[1:]
            self.fragment.extend(data)
            if len(self.fragment) > 8192:
                self.close()
                return
            if flag & 1:
                msg = pb.TakionMessage.FromString(bytes(self.fragment))
                self.fragment.clear()
                if msg.IsInitialized(): self.handle(msg)

    def handle(self,msg):
        if msg.type == pb.TakionMessage.DISCONNECT:
            self.close()
            return
        if self.server.probe:
            self.handle_probe(msg)
            return
        if msg.type == pb.TakionMessage.BIG and not self.bang:
            big = msg.big_payload
            if big.session_key != self.active.session_id: raise ValueError('session mismatch')
            encoded = base64.b64decode(big.launch_spec,validate=True)
            mask = self.server.host.crypto.transform(self.active.pending.ctx,bytes(len(encoded)))
            launch = json.loads(bytes(a^b for a,b in zip(encoded,mask)).rstrip(b'\0'))
            handshake = base64.b64decode(launch['handshakeKey'],validate=True)
            if len(handshake) != 16: raise ValueError('bad handshake key')
            if not hmac.compare_digest(hmac.digest(handshake,big.ecdh_pub_key,'sha256'), big.ecdh_sig):
                raise ValueError('ECDH signature invalid')
            remote = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(),big.ecdh_pub_key)
            private = ec.generate_private_key(ec.SECP256K1())
            secret = private.exchange(ec.ECDH(),remote)
            public = private.public_key().public_bytes(Encoding.X962,PublicFormat.UncompressedPoint)
            reply = pb.TakionMessage(type=pb.TakionMessage.BANG)
            reply.bang_payload.CopyFrom(pb.BangPayload(server_version=big.client_version,token=1,
                encrypted_key_accepted=True,version_accepted=True,session_key=self.active.session_id,
                ecdh_pub_key=public,ecdh_sig=hmac.digest(handshake,public,'sha256')))
            self.plain_bang_ack = self.seq
            self.message(reply,plain=True)
            self.tx = GK(self.server.host.crypto.lib,3,handshake,secret)
            self.rx = GK(self.server.host.crypto.lib,2,handshake,secret)
            self.bang = True
            self.server.host.sessions.event('takion_keys_ready',self.active.pending.profile)
            # Wait until the client processes BANG and installs its receiving keys.
            self.prepare_task = asyncio.create_task(self.prepare_stream())
        elif msg.type == pb.TakionMessage.STREAMINFOACK and self.task is None:
            self.task = asyncio.create_task(self.video())
            self.audio_task = asyncio.create_task(self.audio())
            self.server.host.sessions.event('stream_started',self.active.pending.profile)
        elif msg.type in (pb.TakionMessage.IDRREQUEST,pb.TakionMessage.CORRUPTFRAME):
            if self.server.source: self.server.source.lib.rp_moon_idr()
        elif msg.type == pb.TakionMessage.HEARTBEAT:
            self.message(pb.TakionMessage(type=pb.TakionMessage.HEARTBEAT))

    async def prepare_stream(self):
        try:
            if self.server.source:
                self.source_started = True
                self.server.video_header = await self.server.source.begin()
            await asyncio.sleep(.05)
            if not self.closed: self.stream_info()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f'Apollo stream setup failed: {exc}',flush=True)
            self.close()

    def handle_probe(self,msg):
        if msg.type == pb.TakionMessage.TAKIONPROTOCOLREQUEST:
            response = pb.TakionMessage(type=pb.TakionMessage.TAKIONPROTOCOLREQUESTACK)
            response.takion_protocol_request_ack.takion_protocol_version = 9
            self.message(response)
        elif msg.type == pb.TakionMessage.BIG:
            response = pb.TakionMessage(type=pb.TakionMessage.BANG)
            response.bang_payload.CopyFrom(pb.BangPayload(server_version=9,token=1,encrypted_key_accepted=True,version_accepted=True,session_key='probe'))
            self.message(response)
        elif msg.type == pb.TakionMessage.SENKUSHA:
            command = msg.senkusha_payload
            if command.command == pb.SenkushaPayload.MTU_COMMAND:
                mtu = command.mtu_command
                if not 576 <= mtu.mtu_req <= 1500: return
                packet = bytearray(mtu.mtu_req-28)
                packet[0] = 2
                struct.pack_into('!H',packet,3,mtu.id&0xffff)
                packet[9] = 0xff
                self.send(packet)
            elif command.command == pb.SenkushaPayload.CLIENT_MTU_COMMAND and command.client_mtu_command.state:
                self.message(msg)

    def stream_info(self):
        if self.closed: return
        msg = pb.TakionMessage(type=pb.TakionMessage.STREAMINFO)
        msg.stream_info_payload.resolution.add(width=1280,height=720,video_header=self.server.video_header)
        msg.stream_info_payload.audio_header = struct.pack('!BBIII',2,16,48000,480,1)
        msg.stream_info_payload.congestion_control_interval = 1000
        self.message(msg)

    async def video(self):
        frame_index = 0
        deadline = asyncio.get_running_loop().time()
        try:
            while not self.closed and self.server.host.sessions.active.get(self.active.pending.profile.name) is self.active:
                frame = await self.server.source.video() if self.server.source else self.server.frames[frame_index % len(self.server.frames)]
                chunks = [frame[i:i+1102] for i in range(0,len(frame),1102)]
                if len(chunks) > 255: raise ValueError('frame exceeds FEC block size')
                units = [struct.pack('!H',1102-len(chunk)) + chunk for chunk in chunks]
                units.append(parity(units,1104))
                for unit, data in enumerate(units):
                    if self.server.drop_test and frame_index % 10 == 5 and unit == len(chunks)-1:
                        self.video_index += 1
                        self.server.dropped_packets += 1
                        continue
                    pos = self.position
                    self.position += ((len(data)+31)//16)*16
                    encrypted = self.tx.crypt(data,pos+16)
                    packed = (unit<<21) | (len(chunks)<<10) | 1
                    header = struct.pack('!BHHIB4sIHB',2,self.video_index&0xffff,frame_index&0xffff,packed,0,bytes(4),pos,0,0)
                    self.send(self.sign(header+encrypted,pos,10,14,False))
                    self.video_index += 1
                frame_index += 1
                deadline += 1/60
                if not self.server.source:
                    await asyncio.sleep(max(0,deadline-asyncio.get_running_loop().time()))
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"Video stream failed: {exc}",flush=True)
            self.close()

    async def audio(self):
        index = 0
        deadline = asyncio.get_running_loop().time()
        try:
            while not self.closed and self.server.host.sessions.active.get(self.active.pending.profile.name) is self.active:
                data = await self.server.source.audio() if self.server.source else self.server.audio_frames[index % len(self.server.audio_frames)]
                pos = self.position
                self.position += ((len(data)+31)//16)*16
                # One source unit, no redundant previous units in this first prototype.
                packed = (len(data)<<8) | 1
                header = struct.pack('!BHHIB4sIB',3,index&0xffff,index&0xffff,packed,5,bytes(4),pos,0)
                if self.active.pending.profile.name == 'PS5': header += b'\0'
                self.send(self.sign(header+self.tx.crypt(data,pos+16),pos,10,14,False))
                index += 1
                deadline += .01
                if not self.server.source:
                    await asyncio.sleep(max(0,deadline-asyncio.get_running_loop().time()))
        except asyncio.CancelledError:
            pass

        except Exception as exc:
            print(f"Audio stream failed: {exc}",flush=True)
            self.close()

class TakionServer(asyncio.DatagramProtocol):
    def __init__(self,host,probe=False,drop_test=False,source=None):
        self.source = source
        self.host,self.probe = host,probe
        self.drop_test = drop_test
        self.connections = {}
        self.dropped_packets = 0
        self.feedback_packets = 0
        self.input_observed = set()
        if not probe and not source:
            self.video_header,self.frames = prepare()
            self.audio_frames = prepare_audio()
        self.timer = None

    def connection_made(self,transport):
        self.transport = transport
        self.tick()

    def connection_lost(self,exc):
        if self.timer: self.timer.cancel()
        for conn in self.connections.values(): conn.close()
        self.connections.clear()

    def tick(self):
        now = time.monotonic()
        for addr,conn in list(self.connections.items()):
            if conn.closed or now-conn.last > 15 or self.host.sessions.active.get(conn.active.pending.profile.name) is not conn.active:
                conn.close()
                del self.connections[addr]
                continue
            if now-conn.last_input > 2:
                conn.controller.reset()
                if self.source and not self.probe: self.source.input(conn.controller)
            for item in list(conn.waiting.values()):
                packet,sent,tries = item
                if now-sent > .2:
                    if tries >= 10:
                        conn.close()
                        break
                    conn.send(packet)
                    item[1],item[2] = now,tries+1
        self.timer = asyncio.get_running_loop().call_later(.1,self.tick)

    def datagram_received(self,packet,addr):
        if not packet or len(packet)>1600: return
        try:
            conn = self.connections.get(addr)
            if len(packet)==33 and packet[0]==0 and packet[13]==1:
                candidates = [s for s in self.host.sessions.active.values() if s.peer==addr[0]]
                # Prototype currently requires one active profile per client IP for UDP routing.
                if len(candidates)!=1: return
                peer_tag,_,_,_,seq = struct.unpack_from('!IIHHI',packet,17)
                if conn is None and len(self.connections) >= 32: return
                if conn is None or conn.closed or conn.peer_tag != peer_tag:
                    if conn: conn.close()
                    conn = Connection(self,addr,candidates[0],peer_tag,seq)
                    self.connections[addr] = conn
            if conn and not conn.closed: conn.receive(packet)
        except (ValueError,KeyError,DecodeError,struct.error,OverflowError) as exc:
            print(f'Takion rejected packet: {type(exc).__name__}',flush=True)
