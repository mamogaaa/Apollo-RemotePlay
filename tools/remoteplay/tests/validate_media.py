"""Validate reconstructed frames exactly and decode received Opus packets."""
import ctypes as c
import ctypes.util
import re
import struct
import subprocess

def validate(path, expected):
    data = path.read_bytes()
    starts = [m.start() for m in re.finditer(b'\x00\x00\x00\x01\x09',data)]
    frames = [data[a:b] for a,b in zip(starts,starts[1:]+[len(data)])]
    assert len(frames)>=100, len(frames)
    for i, frame in enumerate(frames):
        assert frame == expected[i%len(expected)], f'Video frame {i} differs from source'
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],check=True,capture_output=True)
    lib = c.CDLL(c.util.find_library('opus'))
    lib.opus_decoder_create.argtypes = [c.c_int,c.c_int,c.POINTER(c.c_int)]
    lib.opus_decoder_create.restype = c.c_void_p
    lib.opus_decode.argtypes = [c.c_void_p,c.c_void_p,c.c_int,c.c_void_p,c.c_int,c.c_int]
    lib.opus_decoder_destroy.argtypes = [c.c_void_p]
    error = c.c_int()
    decoder = lib.opus_decoder_create(48000,2,c.byref(error))
    assert decoder and not error.value
    packets = path.with_name(path.name+'.opus-packets').read_bytes()
    offset = count = energy = samples = 0
    try:
        while offset < len(packets):
            size = struct.unpack_from('!H',packets,offset)[0]
            offset += 2
            data = packets[offset:offset+size]
            offset += size
            assert len(data)==size
            pcm = (c.c_int16*960)()
            n = lib.opus_decode(decoder,data,size,pcm,480,0)
            assert n==480, n
            count += 1
            energy += sum(x*x for x in pcm)
            samples += len(pcm)
        assert count >=100
        rms = (energy/samples)**.5
        assert 1000 < rms < 5000, rms
    finally:
        lib.opus_decoder_destroy(decoder)
    print(f'Validated {len(frames)} bit-exact video frames; decoded {count} Opus packets, RMS={rms:.0f}')
