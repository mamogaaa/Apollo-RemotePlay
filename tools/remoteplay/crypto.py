"""Research-only ctypes adapter; no key material is logged."""
import ctypes as c
from pathlib import Path
from native import library

class Context(c.Structure):
    _fields_ = [('target', c.c_int), ('bright', c.c_ubyte * 16), ('ambassador', c.c_ubyte * 16)]

class Crypto:
    def __init__(self):
        self.lib = library('rpcrypt')
        ptr = c.c_void_p
        signatures = {
            'aeropause': [c.c_int, c.c_size_t, ptr, ptr],
            'init_regist': [ptr, c.c_int, ptr, c.c_size_t, c.c_uint32],
            'encrypt': [ptr, c.c_uint64, ptr, ptr, c.c_size_t],
            'decrypt': [ptr, c.c_uint64, ptr, ptr, c.c_size_t],
        }
        self.lib.chiaki_rpcrypt_init_auth.argtypes = [ptr, c.c_int, ptr, ptr]
        self.lib.chiaki_rpcrypt_init_auth.restype = None
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

    def auth(self, target, nonce, key):
        if len(nonce) != 16 or len(key) != 16:
            raise ValueError('auth nonce and key must be 16 bytes')
        ctx = Context()
        self.lib.chiaki_rpcrypt_init_auth(c.byref(ctx), target, nonce, key)
        return ctx

    def transform(self, ctx, data, decrypt=False, counter=0):
        out = c.create_string_buffer(len(data))
        self.call('decrypt' if decrypt else 'encrypt', c.byref(ctx), counter, data, out, len(data))
        return out.raw

class GK:
    def __init__(self, lib, index, handshake, secret):
        self.lib = lib
        lib.rp_gk_new.argtypes = [c.c_ubyte, c.c_void_p, c.c_void_p]
        lib.rp_gk_new.restype = c.c_void_p
        lib.rp_gk_free.argtypes = [c.c_void_p]
        lib.rp_gk_free.restype = None
        lib.chiaki_gkcrypt_decrypt.argtypes = [c.c_void_p, c.c_uint64, c.c_void_p, c.c_size_t]
        lib.chiaki_gkcrypt_gmac.argtypes = [c.c_void_p, c.c_uint64, c.c_void_p, c.c_size_t, c.c_void_p]
        if len(handshake) != 16 or len(secret) != 32:
            raise ValueError('invalid GK keys')
        self.ctx = lib.rp_gk_new(index, handshake, secret)
        if not self.ctx:
            raise ValueError('GK initialization failed')

    def crypt(self, data, position):
        buf = c.create_string_buffer(data, len(data))
        if self.lib.chiaki_gkcrypt_decrypt(self.ctx, position, buf, len(data)):
            raise ValueError('GK cipher failed')
        return buf.raw

    def mac(self, data, position):
        out = c.create_string_buffer(4)
        if self.lib.chiaki_gkcrypt_gmac(self.ctx, position, data, len(data), out):
            raise ValueError('GK MAC failed')
        return out.raw

    def close(self):
        if self.ctx:
            self.lib.rp_gk_free(self.ctx)
            self.ctx = None
