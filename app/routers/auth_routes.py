"""11.1.1 第三方用户口令认证接口。

方向：算力交易运营平台 --> 三方系统
平台用 username/password 换取访问令牌，后续请求携带 Bearer <token>。
"""
import threading
import time
import collections
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from .. import config
from ..schemas import TokenRequest, api_ok
from ..security import jwt_hs256

router = APIRouter()

# 认证接口防爆破：同一 IP 每 60 秒内最多失败 10 次。
# 只统计"失败"的尝试——正常取令牌（含演示时反复点击）不会触发限流，
# 密码错误的爆破行为仍然会被拦截。
_RATE_LIMIT, _RATE_WINDOW = 10, 60
_fails: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_fails_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    ip = request.client.host if request.client else "unknown"
    if ip in ("127.0.0.1", "::1"):            # 本地代理转发：信任其追加的真实来源
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
    return ip


def _retry_after(ip: str) -> int:
    """返回 0 表示未超限；否则返回还需等待的秒数。"""
    now = time.monotonic()
    with _fails_lock:
        q = _fails[ip]
        while q and now - q[0] > _RATE_WINDOW:
            q.popleft()
        if len(q) < _RATE_LIMIT:
            return 0
        return max(1, int(_RATE_WINDOW - (now - q[0])) + 1)


def _record_failure(ip: str) -> None:
    with _fails_lock:
        _fails[ip].append(time.monotonic())


def _clear_failures(ip: str) -> None:
    with _fails_lock:
        _fails.pop(ip, None)


@router.post("/api/v1/authentication/token",
             tags=["① 认证 · 第一步先调我"],
             summary="获取 accessToken（长期有效）")
def issue_token(req: TokenRequest, request: Request):
    ip = _client_ip(request)
    wait = _retry_after(ip)
    if wait:                                  # 连续失败过多：临时锁定该 IP
        raise HTTPException(status_code=429, detail="认证失败次数过多，请稍后再试",
                            headers={"Retry-After": str(wait)})
    if req.username != config.AUTH_USERNAME or req.password != config.AUTH_PASSWORD:
        _record_failure(ip)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    _clear_failures(ip)                       # 成功即清零，恢复正常使用

    ttl = config.TOKEN_TTL_SECONDS if req.validHours is None else int(req.validHours * 3600)
    token = jwt_hs256.issue(secret=config.JWT_SECRET[:32],
                            subject=config.THIRD_OS_ID,
                            ttl_seconds=ttl,
                            extra_claims={"user": {"username": req.username}})
    fmt = "%Y-%m-%d %H:%M:%S"
    now = datetime.now(timezone(timedelta(hours=8)))  # 北京时间
    return api_ok("认证成功", {
        "issueAt": now.strftime(fmt),
        "expireAt": (now + timedelta(seconds=ttl)).strftime(fmt),
        "accessToken": token["accessToken"],
    })
