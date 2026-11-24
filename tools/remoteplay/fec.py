"""One Cauchy parity shard over GF(2^8), compatible with Chiaki/Jerasure w=8."""

def multiply(a,b):
    value = 0
    while b:
        if b&1: value ^= a
        a <<= 1
        if a&256: a ^= 0x11d
        b >>= 1
    return value

def power(a,n):
    value = 1
    while n:
        if n&1: value = multiply(value,a)
        a = multiply(a,a)
        n >>= 1
    return value

TABLES = [bytes(multiply(power(j,254),x) for x in range(256)) for j in range(1,256)]

def parity(shards, size):
    if not 1 <= len(shards) <= 255 or any(len(s)>size for s in shards):
        raise ValueError('invalid FEC shard dimensions')
    value = 0
    # For m=1, Cauchy matrix element j is inverse(1+j).
    for j,shard in enumerate(shards):
        value ^= int.from_bytes(shard.ljust(size,b'\0').translate(TABLES[j]),'little')
    return value.to_bytes(size,'little')
