"""轻量 JWT（HS256）实现，用于认证方式1 签发访问令牌。

无第三方依赖；声明格式与规范示例一致（iat / exp / sub / user）。
"""
import base64
import hashlib
import hmac
import json
import time


class JwtError(Exception):
    """令牌非法：格式错误、签名不符或已过期。"""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue(secret: bytes, subject: str, ttl_seconds: int,
          extra_claims: dict | None = None) -> dict:
    """签发令牌，返回 {"accessToken", "issueAt"(epoch), "expireAt"(epoch)}。"""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": subject, "iat": now, "exp": now + ttl_seconds}
    if extra_claims:
        payload.update(extra_claims)
    signing_input = (_b64url(json.dumps(header, separators=(",", ":")).encode())
                     + "." +
                     _b64url(json.dumps(payload, separators=(",", ":")).encode()))
    sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return {"accessToken": signing_input + "." + _b64url(sig),
            "issueAt": now, "expireAt": now + ttl_seconds}


def verify(secret: bytes, token: str) -> dict:
    """校验签名与有效期，返回 claims；失败抛 JwtError。"""
    parts = token.split(".")
    if len(parts) != 3:
        raise JwtError("令牌格式非法")
    signing_input = parts[0] + "." + parts[1]
    expect = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(expect, _b64url_decode(parts[2])):
        raise JwtError("令牌签名校验失败")
    claims = json.loads(_b64url_decode(parts[1]))
    if claims.get("exp", 0) < time.time():
        raise JwtError("令牌已过期")
    return claims
