"""Independent integer arithmetic: no host floating-point rounding dependency."""
def add(a, b):
    def flush(x):
        return x & 0x80000000 if (x >> 23) & 255 == 0 else x
    a, b = flush(a), flush(b)
    ea, eb = (a >> 23) & 255, (b >> 23) & 255
    if (ea == 255 and a & 0x7fffff) or (eb == 255 and b & 0x7fffff):
        return 0x7fc00000
    if ea == 255 or eb == 255:
        if ea == eb == 255 and (a ^ b) & 0x80000000:
            return 0x7fc00000
        return a if ea == 255 else b
    # Exact signed integer in units of 2**-149.
    def integer(x, e):
        m = ((1 << 23) | (x & 0x7fffff)) << (e - 1) if e else 0
        return -m if x >> 31 else m
    v = integer(a, ea) + integer(b, eb)
    if not v:
        return 0x80000000 if a == b == 0x80000000 else 0
    sign = 0x80000000 if v < 0 else 0
    v = abs(v)
    shift = max(0, v.bit_length() - 24)
    q = v >> shift
    if shift:
        r = v - (q << shift)
        half = 1 << (shift - 1)
        q += int(r > half or (r == half and q & 1))
    if q >= 1 << 24:
        q >>= 1
        shift += 1
    if q < 1 << 23:
        return sign
    exponent = shift + 1
    if exponent >= 255:
        return sign | 0x7f800000
    return sign | (exponent << 23) | (q & 0x7fffff)

def reduce64(words):
    v = list(words)
    assert len(v) == 64
    for n in (32, 16, 8, 4, 2, 1):
        v = [add(v[i], v[i+n]) for i in range(n)]
    return v[0]
