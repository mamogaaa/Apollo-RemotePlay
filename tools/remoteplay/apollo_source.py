"""Live encoded H.264 source and controller sink using Moonlight's native transport."""
import asyncio
import ctypes as c
import ctypes.util
from pathlib import Path
import queue
import re
import threading
from apollo_control import Apollo
from native import library


class AudioConverter:
    """Convert negotiated Apollo Opus durations into fixed 10 ms Remote Play units."""
    def __init__(self):
        self.lib = library('opus')
        for name, args, restype in (
            ('opus_decoder_create',[c.c_int,c.c_int,c.POINTER(c.c_int)],c.c_void_p),
            ('opus_encoder_create',[c.c_int,c.c_int,c.c_int,c.POINTER(c.c_int)],c.c_void_p),
            ('opus_decode',[c.c_void_p,c.c_void_p,c.c_int,c.c_void_p,c.c_int,c.c_int],c.c_int),
            ('opus_encode',[c.c_void_p,c.c_void_p,c.c_int,c.c_void_p,c.c_int],c.c_int),
            ('opus_decoder_destroy',[c.c_void_p],None),('opus_encoder_destroy',[c.c_void_p],None)):
            fn = getattr(self.lib,name); fn.argtypes = args; fn.restype = restype
        err = c.c_int()
        self.decoder = self.lib.opus_decoder_create(48000,2,c.byref(err))
        if not self.decoder or err.value: raise ValueError('Opus decoder creation failed')
        self.encoder = self.lib.opus_encoder_create(48000,2,2049,c.byref(err))
        if not self.encoder or err.value:
            self.lib.opus_decoder_destroy(self.decoder)
            raise ValueError('Opus encoder creation failed')
        for request,value in ((4002,96000),(4006,0)):
            result = self.lib.opus_encoder_ctl(c.c_void_p(self.encoder),c.c_int(request),c.c_int(value))
            if result: self.close(); raise ValueError('Opus configuration failed')
        self.pending = bytearray()

    def convert(self,data):
        pcm = c.create_string_buffer(5760*4)
        count = self.lib.opus_decode(self.decoder,data,len(data),pcm,5760,0)
        if count < 0: raise ValueError('Invalid Apollo Opus packet')
        self.pending.extend(pcm.raw[:count*4])
        while len(self.pending) >= 480*4:
            block = bytes(self.pending[:1920]); del self.pending[:1920]
            out = c.create_string_buffer(255)
            length = self.lib.opus_encode(self.encoder,block,480,out,len(out))
            if length <= 0: raise ValueError('Remote Play Opus encode failed')
            yield out.raw[:length]

    def close(self):
        if self.decoder: self.lib.opus_decoder_destroy(self.decoder); self.decoder = None
        if self.encoder: self.lib.opus_encoder_destroy(self.encoder); self.encoder = None


from controller_mapping import map_controller


class ApolloSource:
    def __init__(self, directory, appid):
        self.control = Apollo(directory)
        self.appid = appid
        self.lib = library('moonbridge')
        callback_type = c.CFUNCTYPE(c.c_int,c.c_int,c.c_void_p,c.c_int,c.c_int)
        self.callback_ref = callback_type(self.callback)
        self.lib.rp_moon_start.argtypes = [c.c_char_p]*5+[c.c_uint32,callback_type]
        self.lib.rp_moon_start.restype = c.c_int
        self.lib.rp_moon_input.argtypes = [c.c_int,c.c_ubyte,c.c_ubyte]+[c.c_short]*4
        self.video_queue = queue.Queue(3)
        self.audio_queue = queue.Queue(10)
        self.lock = threading.Lock()
        self.active = False
        self.wait_idr = True
        self.header = b''
        self.error = None
        self.started = False
        self.converter = AudioConverter()

    def callback(self,kind,pointer,size,metadata):
        try:
            if kind in (4,5):
                self.error = f'Apollo transport failed: kind={kind} stage={size} code={metadata}'
                return 0
            if kind == 3:
                return 0 if metadata in (120,240,480,960) else -1
            data = c.string_at(pointer,size)
            with self.lock:
                if not self.active: return 0
                if kind == 1:
                    if metadata:
                        nals = re.split(b'\x00\x00\x00?\x01',data)
                        self.header = b''.join(b'\0\0\0\1'+n for n in nals if n and n[0]&31 in (7,8))
                        if not self.header: return -1
                        self.wait_idr = False
                    if self.wait_idr: return -1
                    if self.video_queue.full():
                        self.wait_idr = True
                        return -1  # Native transport requests a fresh IDR; retain queued dependencies.
                    self.video_queue.put_nowait(data)
                elif kind == 2:
                    for packet in self.converter.convert(data):
                        if self.audio_queue.full(): self.audio_queue.get_nowait()
                        self.audio_queue.put_nowait(packet)
            return 0
        except Exception as exc:
            self.error = f'Apollo media conversion failed: {type(exc).__name__}'
            return -1

    async def start(self):
        info,url,key,key_id = await asyncio.to_thread(self.control.launch,self.appid)
        result = await asyncio.to_thread(self.lib.rp_moon_start,
            self.control.state['host'].encode(),info.findtext('appversion','').encode(),
            info.findtext('GfeVersion','').encode(),url.encode(),key,key_id,self.callback_ref)
        if result:
            self.converter.close()
            raise RuntimeError(f'Apollo transport start failed: {result}')
        self.started = True

    async def begin(self):
        with self.lock:
            for q in (self.video_queue,self.audio_queue):
                while not q.empty(): q.get_nowait()
            self.header = b''; self.wait_idr = True; self.active = True
        self.lib.rp_moon_idr()
        async with asyncio.timeout(10):
            while not self.header:
                if self.error: raise RuntimeError(self.error)
                await asyncio.sleep(.01)
        return self.header

    async def next_packet(self,q,timeout=10):
        deadline = asyncio.get_running_loop().time()+timeout if timeout else None
        while True:
            if deadline is not None and asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("Apollo stopped producing media")
            if self.error: raise RuntimeError(self.error)
            try: return q.get_nowait()
            except queue.Empty: await asyncio.sleep(.001)

    async def video(self): return await self.next_packet(self.video_queue)
    # WASAPI loopback may emit no packets when no application is playing sound.
    # Silence must not terminate the video session; transport failures still raise.
    async def audio(self): return await self.next_packet(self.audio_queue,timeout=None)

    def input(self,controller):
        if self.started: self.lib.rp_moon_input(*map_controller(controller))

    def end(self):
        with self.lock: self.active = False
        if self.started: self.lib.rp_moon_input(0,0,0,0,0,0,0)

    async def close(self):
        self.end()
        if self.started:
            await asyncio.to_thread(self.lib.rp_moon_stop)
            self.started = False
        self.converter.close()
