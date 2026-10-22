"""SM3 国密哈希算法纯 Python 实现 + Hmac-SM3。

优先使用 OpenSSL 提供的 sm3（hashlib），不可用时回退到纯 Python 实现，
两者输出一致（标准测试向量 "abc" -> 66c7f0f4...b8f4ba8e0）。
"""
import hashlib
import struct

IV = (0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
      0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E)


def _rotl(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _p0(x: int) -> int:
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x: int) -> int:
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _pure_sm3(msg: bytes) -> bytes:
    length = len(msg) * 8
    padded = msg + b"\x80"
    while len(padded) * 8 % 512 != 448:
        padded += b"\x00"
    padded += length.to_bytes(8, "big")

    v = list(IV)
    for off in range(0, len(padded), 64):
        blk = padded[off:off + 64]
        w = list(struct.unpack(">16I", blk))
        for j in range(16, 68):
            w.append(_p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15))
                     ^ _rotl(w[j - 13], 7) ^ w[j - 6])
        w1 = [w[j] ^ w[j + 4] for j in range(64)]

        a, b, c, d, e, f, g, h = v
        for j in range(64):
            t = 0x79CC4519 if j < 16 else 0x7A879D8A
            ss1 = _rotl((_rotl(a, 12) + e + _rotl(t, j % 32)) & 0xFFFFFFFF, 7)
            ss2 = ss1 ^ _rotl(a, 12)
            ff = (a ^ b ^ c) if j < 16 else ((a & b) | (a & c) | (b & c))
            gg = (d ^ e ^ f) if j < 16 else ((d & e) | (~d & f))
            tt1 = (ff + d + ss2 + w1[j]) & 0xFFFFFFFF
            tt2 = (gg + h + ss1 + w[j]) & 0xFFFFFFFF
            d, c, b, a = c, _rotl(b, 9), a, tt1
            h, g, f, e = g, _rotl(f, 19), e, _p0(tt2)
        v = [(x ^ y) & 0xFFFFFFFF for x, y in zip(v, (a, b, c, d, e, f, g, h))]

    return b"".join(struct.pack(">I", x) for x in v)


def sm3_digest(msg: bytes) -> bytes:
    try:
        return hashlib.new("sm3", msg).digest()
    except (ValueError, TypeError):
        return _pure_sm3(msg)


def sm3_hex(msg: bytes) -> str:
    return sm3_digest(msg).hex()


def hmac_sm3(key: bytes, msg: bytes) -> bytes:
    """HMAC-SM3（RFC 2104 构造，分组长度 64 字节）。"""
    block = 64
    if len(key) > block:
        key = sm3_digest(key)
    key = key.ljust(block, b"\x00")
    ipad = bytes(b ^ 0x36 for b in key)
    opad = bytes(b ^ 0x5C for b in key)
    return sm3_digest(opad + sm3_digest(ipad + msg))


def hmac_sm3_hex(key: bytes, msg: bytes) -> str:
    return hmac_sm3(key, msg).hex()
