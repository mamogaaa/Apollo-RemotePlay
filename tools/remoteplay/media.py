"""Deterministic encoded test source, generated locally with ffmpeg."""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).parent/'build'

def prepare():
    ROOT.mkdir(exist_ok=True)
    path = ROOT/'test.h264'
    if not path.exists():
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=1280x720:rate=60',
                        '-frames:v','120','-c:v','libx264','-preset','ultrafast','-tune','zerolatency',
                        '-profile:v','baseline','-pix_fmt','yuv420p','-b:v','4000k',
                        '-x264-params','aud=1:repeat-headers=1:keyint=60:min-keyint=60:scenecut=0',
                        '-f','h264',str(path)], check=True)
    data = path.read_bytes()
    starts = [m.start() for m in re.finditer(b'\x00\x00\x00\x01\x09', data)]
    if len(starts) != 120:
        raise ValueError('test video must have 120 AUD access units')
    frames = [data[a:b] for a,b in zip(starts, starts[1:] + [len(data)])]
    nals = re.split(b'\x00\x00\x00?\x01', frames[0])
    header = b''.join(b'\x00\x00\x00\x01' + n for n in nals if n and (n[0] & 31) in (7,8))
    return header, frames

if __name__ == '__main__':
    h, f = prepare()
    print(f'Prepared {len(f)} H.264 frames and {len(h)} header bytes')

def prepare_audio():
    import ctypes as c
    import ctypes.util
    import math
    lib = c.CDLL(c.util.find_library('opus'))
    lib.opus_encoder_create.argtypes = [c.c_int,c.c_int,c.c_int,c.POINTER(c.c_int)]
    lib.opus_encoder_create.restype = c.c_void_p
    lib.opus_encode.argtypes = [c.c_void_p,c.c_void_p,c.c_int,c.c_void_p,c.c_int]
    lib.opus_encoder_destroy.argtypes = [c.c_void_p]
    error = c.c_int()
    encoder = lib.opus_encoder_create(48000,2,2049,c.byref(error))
    if not encoder or error.value: raise ValueError('Opus encoder creation failed')
    frames = []
    try:
        # Opus CTLs are variadic: explicitly type the pointer and integer arguments.
        for request,value in ((4002,96000),(4006,0)):
            if lib.opus_encoder_ctl(c.c_void_p(encoder),c.c_int(request),c.c_int(value)):
                raise ValueError('Opus configuration failed')
        for index in range(200):
            pcm = (c.c_int16 * 960)()
            for n in range(480):
                value = int(4000*math.sin(2*math.pi*440*(index*480+n)/48000))
                pcm[2*n] = pcm[2*n+1] = value
            out = c.create_string_buffer(1275)
            size = lib.opus_encode(encoder,pcm,480,out,len(out))
            if not 0 < size < 256: raise ValueError('Opus unit exceeds protocol limit')
            frames.append(out.raw[:size])
    finally:
        lib.opus_encoder_destroy(encoder)
    return frames
