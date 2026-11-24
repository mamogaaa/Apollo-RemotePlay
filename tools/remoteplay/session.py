"""LAN session authorization and encrypted control channel."""
import asyncio
import base64
from dataclasses import dataclass
import secrets
import struct
import time

class Rejected(ValueError):
    def __init__(self, status=403, reason='80108b09'):
        self.status, self.reason = status, reason

@dataclass
class Pending:
    profile: object
    credential: str
    ctx: object
    nonce: bytes
    deadline: float

@dataclass
class Active:
    pending: Pending
    session_id: str
    peer: str
    writer: object
    inbound_counter: int
    outbound_counter: int = 1

class Sessions:
    def __init__(self, host):
        self.host = host
        self.pending = {}
        self.active = {}
        self.events = []

    def event(self, name, profile):
        # Bounded metadata only, for integration tests and diagnostics.
        self.events.append((name, profile.name))
        del self.events[:-128]
        print(f'{name}: {profile.name}', flush=True)

    def init(self, profile, peer, headers):
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if v.deadline > now}
        if self.active:
            raise Rejected(503, '80108b10')
        try:
            credential = bytes.fromhex(headers.get('rp-registkey', '')).decode('ascii')
        except (ValueError, UnicodeError):
            raise Rejected() from None
        client = self.host.store.data[profile.name.lower()]['clients'].get(credential)
        if client is None:
            raise Rejected()
        if len(self.pending) >= 32 and (peer, profile.name) not in self.pending:
            raise Rejected(503, '80108b10')
        nonce = secrets.token_bytes(16)
        ctx = self.host.crypto.auth(profile.target, nonce, bytes.fromhex(client['key']))
        self.pending[peer, profile.name] = Pending(profile, credential, ctx, nonce, now + 15)
        self.event('session_init', profile)
        return {'RP-Nonce': base64.b64encode(nonce).decode(), 'RP-Version': profile.rp_version}

    def authorize(self, profile, peer, headers, writer):
        pending = self.pending.get((peer, profile.name))
        if pending is None or pending.deadline <= time.monotonic():
            raise Rejected()
        if self.active:
            raise Rejected(503, '80108b10')
        names = ['rp-auth', 'rp-did', 'rp-ostype', 'rp-startbitrate']
        if profile.name == 'PS5':
            names.append('rp-streamingtype')
        values = []
        try:
            for counter, name in enumerate(names):
                value = base64.b64decode(headers[name], validate=True)
                if not value or len(value) > 128:
                    raise ValueError('invalid encrypted field')
                values.append(self.host.crypto.transform(pending.ctx, value, decrypt=True, counter=counter))
            if not secrets.compare_digest(values[0], pending.credential.encode().ljust(16, b'\0')):
                raise ValueError('bad authentication')
            if len(values[1]) != 32 or not values[2].endswith(b'\0') or len(values[3]) != 4:
                raise ValueError('bad control fields')
            if profile.name == 'PS5' and values[4] != b'\x01\0\0\0':
                raise ValueError('prototype supports H.264 only')
        except (KeyError, ValueError):
            raise Rejected() from None
        del self.pending[peer, profile.name]
        active = Active(pending, secrets.token_hex(37), peer, writer, len(names))
        self.active[profile.name] = active
        self.event('control_authenticated', profile)
        return active

    async def control(self, active, reader):
        crypto = self.host.crypto
        profile = active.pending.profile
        writer = active.writer
        server_type = bytes([2 if profile.name == 'PS5' else 1]) + bytes(15)
        encoded = base64.b64encode(crypto.transform(active.pending.ctx, server_type)).decode()
        try:
            writer.write(('HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: keep-alive\r\n'
                          f'RP-Server-Type: {encoded}\r\nRP-Prohibit: 0\r\n\r\n').encode())
            await self.send(active, 0x33, b'\x4a' + active.session_id.encode())
            await self.send(active, 0xfe)
            while True:
                # Timeout covers the entire frame so a partial packet cannot stall forever.
                async with asyncio.timeout(15):
                    length, kind, reserved = struct.unpack('!IHH', await reader.readexactly(8))
                    if length > 4096 or reserved:
                        raise ValueError('invalid control frame')
                    data = await reader.readexactly(length)
                if data:
                    data = crypto.transform(active.pending.ctx, data, decrypt=True, counter=active.inbound_counter)
                    active.inbound_counter += 1
                if kind == 0x1fe:
                    self.event('heartbeat_reply', profile)
                    # No background task is needed: next request after a bounded delay.
                    await asyncio.sleep(1)
                    await self.send(active, 0xfe)
                elif kind == 0xfe:
                    await self.send(active, 0x1fe)
                elif kind == 0x50:
                    break  # Disconnect; never suspend/shutdown the PC implicitly.
                elif kind in (0x13, 0x11, 0xd, 0x20, 0x30, 0x36, 0x910, 0x14):
                    self.event('control_message', profile)
        except (asyncio.IncompleteReadError, ConnectionError, OSError, TimeoutError, ValueError):
            pass
        finally:
            if self.active.get(profile.name) is active:
                del self.active[profile.name]
            self.event('control_closed', profile)

    async def send(self, active, kind, data=b''):
        if data:
            data = self.host.crypto.transform(active.pending.ctx, data, counter=active.outbound_counter)
            active.outbound_counter += 1
        active.writer.write(struct.pack('!IHH', len(data), kind, 0) + data)
        await active.writer.drain()
