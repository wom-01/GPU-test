"""AES-CBC 字段加解密（与对接方 AESCBCUtil.java 完全对齐）。

约定：AES/CBC/PKCS5Padding，随机 IV（16位可打印字符串，UUID去连字符截取），
输出格式：IV明文(前16字符) + Base64(密文)。
解密方按同样规则：前16字符为IV，剩余部分 Base64 解码后解密。
用于：
  1. 认证方式2 —— Authorization 头携带的 thirdOSid+Timestamp+Nonce 密文；
  2. 开通结果中敏感字段（publicSshPort / username / password）的加密传输。
双方须使用相同密钥（config.AES_KEY，16/24/32 字节）。
"""
import base64
import uuid

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class AesError(Exception):
    """加解密失败（密钥不匹配 / 密文格式非法 / 填充错误）。"""


def _pkcs7_pad(data: bytes) -> bytes:
    n = 16 - len(data) % 16
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data or len(data) % 16:
        raise AesError("密文长度非法")
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        raise AesError("填充校验失败")
    return data[:-n]


def _crypt(data: bytes, key: bytes, iv: bytes, encrypt: bool) -> bytes:
    if len(key) not in (16, 24, 32):
        raise AesError("AES 密钥长度须为 16/24/32 字节")
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    op = cipher.encryptor() if encrypt else cipher.decryptor()
    return op.update(data) + op.finalize()


def encrypt(plaintext: str, key: bytes) -> str:
    """返回：IV明文(16字符) + Base64(密文)。"""
    iv_str = uuid.uuid4().hex[:16]
    ct = _crypt(_pkcs7_pad(plaintext.encode("utf-8")), key, iv_str.encode("utf-8"), True)
    return iv_str + base64.b64encode(ct).decode()


def decrypt(text: str, key: bytes) -> str:
    """入参：IV明文(前16字符) + Base64(密文)。"""
    try:
        iv_str, b64_ct = text[:16], text[16:]
        ct = base64.b64decode(b64_ct)
    except Exception as exc:
        raise AesError("密文格式非法") from exc
    if not ct or len(ct) % 16:
        raise AesError("密文长度非法")
    plain = _crypt(ct, key, iv_str.encode("utf-8"), False)
    return _pkcs7_unpad(plain).decode("utf-8")
