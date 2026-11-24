"""Decode actual received Apollo media; retain WAV for audible verification."""
import ctypes as c
import json
import struct
import subprocess
import wave
from native import library


def validate_live(path):
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'],
                   check=True, capture_output=True)
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
        '-select_streams', 'v:0', '-show_entries', 'stream=width,height,nb_read_frames',
        '-of', 'json', str(path)]))['streams'][0]
    assert (probe['width'], probe['height']) == (1280, 720), probe
    assert int(probe['nb_read_frames']) >= 100, probe
    lib = library('opus')
    lib.opus_decoder_create.argtypes = [c.c_int, c.c_int, c.POINTER(c.c_int)]
    lib.opus_decoder_create.restype = c.c_void_p
    lib.opus_decode.argtypes = [c.c_void_p, c.c_void_p, c.c_int, c.c_void_p, c.c_int, c.c_int]
    lib.opus_decoder_destroy.argtypes = [c.c_void_p]
    error = c.c_int()
    decoder = lib.opus_decoder_create(48000, 2, c.byref(error))
    assert decoder and not error.value
    packets = path.with_name(path.name+'.opus-packets').read_bytes()
    offset = count = energy = 0
    try:
        with wave.open(str(path.with_suffix('.wav')), 'wb') as wav:
            wav.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            while offset < len(packets):
                size = struct.unpack_from('!H', packets, offset)[0]
                offset += 2
                packet = packets[offset:offset+size]
                offset += size
                assert len(packet) == size
                pcm = (c.c_int16*960)()
                assert lib.opus_decode(decoder, packet, size, pcm, 480, 0) == 480
                wav.writeframes(bytes(pcm))
                count += 1
                energy += sum(x*x for x in pcm)
    finally:
        lib.opus_decoder_destroy(decoder)
    assert count >= 100, count
    rms = (energy/(count*960))**.5
    print(f'Live decoded video={probe["nb_read_frames"]} frames; audio={count} packets; RMS={rms:.1f}')
    if rms < 10:
        print('Audio is silent: play sound on the Apollo desktop before audible acceptance.')
