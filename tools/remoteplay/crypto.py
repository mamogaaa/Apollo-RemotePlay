"""Research-only ctypes adapter; no key material is logged."""
import ctypes as c
from pathlib import Path

class Context(c.Structure):
    _fields_ = [('target', c.c_int), ('bright', c.c_ubyte * 16), ('ambassador', c.c_ubyte * 16)]

class Crypto:
    def __init__(self):
        self.lib = c.CDLL(str(Path(__file__).parent/'build/librpcrypt.so'))
        ptr = c.c_void_p
        signatures = {
            'aeropause': [c.c_int, c.c_size_t, ptr, ptr],
            'init_regist': [ptr, c.c_int, ptr, c.c_size_t, c.c_uint32],
            'encrypt': [ptr, c.c_uint64, ptr, ptr, c.c_size_t],
            'decrypt': [ptr, c.c_uint64, ptr, ptr, c.c_size_t],
        }
        for name, args in signatures.items():
            f = getattr(self.lib, 'chiaki_rpcrypt_' + name)
            f.argtypes, f.restype = args, c.c_int

    def call(self, name, *args):
        result = getattr(self.lib, 'chiaki_rpcrypt_' + name)(*args)
        if result:
            raise ValueError(f'RPCrypt {name} failed: {result}')

    def registration(self, target, pin, payload):
        if not 480 < len(payload) <= 4096:
            raise ValueError('invalid registration payload size')
        aeropause = payload[0x191:0x199] + payload[0xc7:0xcf]
        # Upstream ambassador_from_aeropause reverses the PSN variant, NOT LAN.
        # LAN: a[i] = (ambassador[i] XOR table[i]) + offset + i (mod 256).
        zero_encoded = c.create_string_buffer(16)
        self.call('aeropause', target, payload[0] >> 3, zero_encoded, bytes(16))
        offset = -0x2d if target >= 1000000 else 0x29
        ambassador = bytes(((aeropause[i] - offset - i) & 255) ^
                           ((zero_encoded.raw[i] - offset - i) & 255) for i in range(16))
        ctx = Context()
        self.call('init_regist', c.byref(ctx), target, ambassador, payload[0x18d] & 31, pin)
        return ctx, self.transform(ctx, payload[480:], decrypt=True)

    def transform(self, ctx, data, decrypt=False):
        out = c.create_string_buffer(len(data))
        self.call('decrypt' if decrypt else 'encrypt', c.byref(ctx), 0, data, out, len(data))
        return out.raw
