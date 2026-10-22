"""统一认证入口：按 Authorization 头自动识别规范支持的三种认证方式。

  方式1  Bearer <jwt>            —— 用户名/口令认证换发的令牌
  方式2  <Base64 AES 密文>        —— 密钥对称加密认证，明文 thirdOSid|Timestamp|Nonce
  方式3  MAC id="..",access_token="..",nonce="..",mac="..",algorithm="hmac-sm3"

Hmac-SM3 签名串（双方约定，规范未细化，以本文档定义为准）：
    method + "\n" + path + "\n" + access_token + "\n" + nonce + "\n" + sha256_hex(body)
"""
import base64
import collections
import hashlib
import hmac
import re
import threading
import time

from fastapi import Header, Request

from .. import config
from . import aes, jwt_hs256
from .sm3 import hmac_sm3_hex


class AuthError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


_nonce_lock = threading.Lock()
_seen_nonces = collections.OrderedDict()


def _check_and_cache_nonce(nonce: str) -> bool:
    """nonce 只允许出现一次；返回 False 表示重放。"""
    with _nonce_lock:
        if nonce in _seen_nonces:
            return False
        _seen_nonces[nonce] = True
        while len(_seen_nonces) > config.NONCE_CACHE_SIZE:
            _seen_nonces.popitem(last=False)
        return True


def _auth_token(header_value: str) -> str:
    token = header_value[len("Bearer "):].strip()
    try:
        jwt_hs256.verify(config.AES_KEY[:32], token)  # 用 AES_KEY 前 32 字节作 JWT 签名密钥
    except jwt_hs256.JwtError as exc:
        raise AuthError(f"令牌校验失败：{exc}")
    except Exception as exc:  # 畸形 token（base64/编码坏掉等）一律按认证失败处理
        raise AuthError(f"令牌格式非法：{exc}")
    return config.THIRD_OS_ID


def _auth_aes(header_value: str) -> str:
    try:
        plain = aes.decrypt(header_value.strip(), config.AES_KEY)
    except aes.AesError as exc:
        raise AuthError(f"密钥认证密文解密失败：{exc}")
    except Exception as exc:
        raise AuthError(f"密钥认证密文格式非法：{exc}")
    parts = plain.split("|")
    if len(parts) != 3:
        raise AuthError("密文明文格式非法，应为 thirdOSid|Timestamp|Nonce")
    third_os_id, ts, nonce = parts
    if third_os_id != config.THIRD_OS_ID:
        raise AuthError("thirdOSid 不匹配")
    try:
        ts_val = float(ts)
    except ValueError as exc:
        raise AuthError("时间戳非法") from exc
    if abs(time.time() - ts_val) > config.TIMESTAMP_WINDOW_SECONDS:
        raise AuthError("时间戳超出允许窗口，疑似重放")
    if not _check_and_cache_nonce(nonce):
        raise AuthError("Nonce 重复使用，疑似重放")
    return third_os_id


_MAC_PARAM = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def _auth_mac(header_value: str, request: Request) -> str:
    params = dict(_MAC_PARAM.findall(header_value[len("MAC "):]))
    missing = [k for k in ("id", "access_token", "nonce", "mac") if k not in params]
    if missing:
        raise AuthError(f"MAC 头缺少参数：{','.join(missing)}")
    if params.get("algorithm", "hmac-sm3") != "hmac-sm3":
        raise AuthError("仅支持 algorithm=hmac-sm3")
    if params["id"] != config.THIRD_OS_ID:
        raise AuthError("MAC id 不匹配")
    if not _check_and_cache_nonce("mac:" + params["nonce"]):
        raise AuthError("Nonce 重复使用，疑似重放")

    body = request.scope.get("_cached_body") or b""
    canonical = "\n".join([
        request.method,
        request.url.path,
        params["access_token"],
        params["nonce"],
        hashlib.sha256(body).hexdigest(),
    ])
    expect = hmac_sm3_hex(config.MAC_KEY, canonical.encode())
    if not hmac.compare_digest(expect, params["mac"].lower()):
        raise AuthError("Hmac-SM3 签名校验失败")
    return params["id"]


async def require_auth(request: Request,
                       authorization: str | None = Header(None)) -> str:
    """FastAPI 依赖：校验通过返回 thirdOSid，失败抛 AuthError(401)。"""
    if not authorization:
        raise AuthError("缺少 Authorization 头")

    # 提前读取原始请求体：Starlette 会缓存（request._body），
    # 供 MAC 验签使用，后续 Pydantic 解析 JSON 时复用同一份缓存。
    request.scope["_cached_body"] = await request.body()

    mode = config.AUTH_MODE
    if mode != "all":
        allowed = {"token": "Bearer ", "aes": "", "mac": "MAC "}
        if mode == "token" and not authorization.startswith("Bearer "):
            raise AuthError("当前仅启用令牌认证（Bearer）")
        if mode == "mac" and not authorization.startswith("MAC "):
            raise AuthError("当前仅启用国密 SM3 认证（MAC）")

    if authorization.startswith("Bearer "):
        return _auth_token(authorization)
    if authorization.startswith("MAC "):
        return _auth_mac(authorization, request)
    if mode in ("all", "aes"):
        return _auth_aes(authorization)
    raise AuthError("Authorization 头格式无法识别")
