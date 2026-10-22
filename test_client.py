"""模拟「算力交易运营平台」按规范完整调用三方系统南向接口的自测脚本。

用法：先启动服务（uvicorn app.main:app（start.sh 拉起，端口 12359）），再运行本脚本：
    python3 test_client.py [BASE_URL]      # 默认 http://127.0.0.1:12359

覆盖场景：
  1. SM3 算法自测向量
  2. 认证方式1：错误口令 / 正确口令换 token，后续请求 Bearer 认证
  3. 11.1.2 资源上报 collect（含规格过滤）
  4. 11.1.3/11.1.4 预占、重复预占拒绝、释放、释放幂等
  5. 11.1.5/11.1.6 开通（含预占-开通主机一致性校验）、轮询开通结果、敏感字段解密
  6. 11.1.7 监控采集
  7. 11.1.8 暂停/恢复/预销户/撤销预销户/销户
  8. 11.1.9/11.1.10 批量预占 / 批量释放
  9. 认证方式2：AES 密钥认证（thirdOSid|Timestamp|Nonce）
 10. 认证方式3：Hmac-SM3 MAC 认证
"""
import base64
import hashlib
import json
import os
import sys
import time
import uuid

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:12359"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import config                                    # noqa: E402
from app.security.sm3 import hmac_sm3_hex, sm3_hex        # noqa: E402
from app.security.aes import decrypt as aes_decrypt       # noqa: E402

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    tag = "✅" if cond else "❌"
    PASS, FAIL = PASS + cond, FAIL + (not cond)
    print(f"  {tag} {name}" + (f"  —— {detail}" if detail and not cond else ""))


def post(path, payload=None, headers=None, expect_http=200):
    h = {"Content-Type": "application/json;charset=UTF-8",
         "Accept": "application/json;charset=UTF-8"}
    h.update(headers or {})
    r = requests.post(BASE + path, data=json.dumps(payload or {}), headers=h, timeout=15)
    body = r.json()
    return r.status_code, body


print(f"目标服务：{BASE}\n" + "=" * 64)

# ── 0. SM3 自测向量 ──────────────────────────────────────────────────────
print("[0] SM3 标准测试向量")
check('SM3("abc")', sm3_hex(b"abc") ==
      "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0")

# ── 1. 认证方式1：用户名/口令 ────────────────────────────────────────────
print("[1] 认证方式1：用户名/口令换令牌")
code, body = post("/api/v1/authentication/token",
                  {"username": config.AUTH_USERNAME, "password": "wrong-pass"})
check("错误口令被拒绝(401)", code == 401, f"got {code} {body}")

code, body = post("/api/v1/authentication/token",
                  {"thirdOSid": config.THIRD_OS_ID,
                   "username": config.AUTH_USERNAME, "password": config.AUTH_PASSWORD})
check("认证成功 code=0", body.get("code") == "0" and code == 200, str(body))
data = body.get("data", {})
TOKEN = data.get("accessToken", "")
check("返回 issueAt/expireAt/accessToken",
      all(k in data for k in ("issueAt", "expireAt", "accessToken")))
BEARER = {"Authorization": f"Bearer {TOKEN}"}

# ── 2. 算力资源上报 ──────────────────────────────────────────────────────
print("[2] 11.1.2 算力资源上报 collect")
code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10, "specification": {}}, BEARER)
hosts = body.get("data", {}).get("hosts", [])
check(f"可用主机上报（{len(hosts)}台）", body.get("code") == "0" and len(hosts) >= 1,
      f"got {len(hosts)}")

if hosts:
    _model = (hosts[0].get("specification") or {}).get("gpuModel")
else:
    _model = None
_want = sum(1 for h in hosts
            if (h.get("specification") or {}).get("gpuModel") == _model) if _model else 0
code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10, "specification": {"gpuModel": _model}}, BEARER)
filtered = body["data"]["hosts"]
check(f"按规格过滤 gpuModel={_model}（{_want}台）", len(filtered) == _want,
      f"got {len(filtered)}")
check("主机属性完整(areaCode/hostRoomName/specification)",
      all(h.get("areaCode") and h.get("hostRoomName") and h.get("specification")
          for h in filtered))

code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10}, {})  # 无 Authorization
check("缺少认证头被拒绝(401)", code == 401, f"got {code}")

# ── 3. 预占 / 释放 ───────────────────────────────────────────────────────
print("[3] 11.1.3/11.1.4 预占与释放")
RID = "RS" + uuid.uuid4().hex[:10].upper()
TARGET = hosts[0]
HOST_A = {"hostIp": TARGET["hostIp"], "hostRoomName": TARGET["hostRoomName"]}
code, body = post("/api/v1/compute/resource/reserve/notify",
                  {"reserveId": RID, "hosts": [HOST_A]}, BEARER)
check("预占成功", body.get("code") == "0", str(body))

code, body = post("/api/v1/compute/resource/reserve/notify",
                  {"reserveId": "RS-OTHER", "hosts": [HOST_A]}, BEARER)
check("重复预占同一主机被拒绝", body.get("code") != "0", str(body))

code, body = post("/api/v1/compute/resource/reserve/notify",
                  {"reserveId": "RS-GHOST", "hosts": [{"hostIp": "10.0.0.99",
                                                       "hostRoomName": "机房X"}]}, BEARER)
check("预占不存在主机被拒绝", body.get("code") == "404", str(body))

code, body = post("/api/v1/compute/resource/reserve/release",
                  {"reserveId": RID, "description": "用户取消订购"}, BEARER)
check("预占释放成功", body.get("code") == "0")
code, body = post("/api/v1/compute/resource/reserve/release",
                  {"reserveId": RID}, BEARER)
check("重复释放视为成功(幂等)", body.get("code") == "0")

# ── 4. 开通流程（异步 + 轮询）────────────────────────────────────────────
print("[4] 11.1.5/11.1.6 开通与结果查询")
OID = "OP" + uuid.uuid4().hex[:10].upper()

code, body = post("/api/v1/compute/resource/reserve/notify",
                  {"reserveId": RID, "hosts": [HOST_A]}, BEARER)
check("重新预占", body.get("code") == "0")

if hosts and len(hosts) > 1:
    _other = hosts[1]
    MISMATCH_HOSTS = [{"hostIp": _other["hostIp"],
                       "hostRoomName": _other["hostRoomName"]}]
else:
    MISMATCH_HOSTS = [{"hostIp": "10.99.99.99", "hostRoomName": "机房X"}]
code, body = post("/api/v1/compute/resource/host/open",
                  {"openId": OID, "reserveId": RID, "userId": "9900012345",
                   "orderStartTime": "2026-10-20 12:00:00",
                   "hosts": MISMATCH_HOSTS}, BEARER)
check("预占-开通主机不一致被拒绝", body.get("code") in ("400", "404"), str(body))

code, body = post("/api/v1/compute/resource/host/open",
                  {"openId": OID, "reserveId": RID, "userId": "9900012345",
                   "orderStartTime": "2026-10-20 12:00:00", "hosts": [HOST_A]}, BEARER)
check("开通请求受理", body.get("code") == "0", str(body))

open_code = None
for _ in range(20):
    code, body = post("/api/v1/compute/resource/host/open/query",
                      {"openId": OID}, BEARER)
    host0 = body["data"]["hosts"][0]
    open_code = host0["openCode"]
    if open_code == "0":
        break
    time.sleep(1)
check(f"轮询开通结果 openCode=0 (实际{open_code})", open_code == "0")

code, body = post("/api/v1/compute/resource/host/open/query", {"openId": OID}, BEARER)
h0 = body["data"]["hosts"][0]
plain = {k: aes_decrypt(h0[k], config.AES_KEY)
         for k in ("publicSshPort", "username", "password")}
check("敏感字段为 AES 密文且可解密",
      h0["password"] != plain["password"] and plain["username"] == "dbcloud",
      str(plain))
print(f"     交付凭证(解密后)：ssh {plain['username']}@{h0['publicIp']}:"
      f"{plain['publicSshPort']}  密码={plain['password']}")

code, body = post("/api/v1/compute/resource/host/open/query",
                  {"openId": "OP-NOT-EXIST"}, BEARER)
check("查询不存在的开通事件返回404", body.get("code") == "404")

# ── 5. 监控数据采集 ──────────────────────────────────────────────────────
print("[5] 11.1.7 监控数据采集")
code, body = post("/api/v1/compute/resource/host/monitor/collect",
                  {"thirdOSid": config.THIRD_OS_ID, "providerName": config.PROVIDER_NAME,
                   "hosts": [dict(HOST_A)]}, BEARER)
m = body["data"]["hosts"][0]
check("监控数据字段齐备", all(k in m for k in
      ("usageCPU", "usageMemory", "usageGpu", "gpuUsedMemory", "updateTime")), str(m))

# ── 6. 订单操作：暂停/恢复/预销户/撤销/销户 ──────────────────────────────
print("[6] 11.1.8 订单操作")
for ot, name in [("104", "暂停"), ("105", "恢复"), ("107", "预销户"),
                 ("108", "撤销预销户")]:
    code, body = post("/api/v1/compute/resource/host/order/update",
                      {"openId": OID, "orderType": ot}, BEARER)
    check(f"{name}({ot})", body.get("code") == "0", str(body))

code, body = post("/api/v1/compute/resource/host/order/update",
                  {"openId": OID, "orderType": "109"}, BEARER)
check("销户(109)", body.get("code") == "0")
code, body = post("/api/v1/compute/resource/host/order/update",
                  {"openId": OID, "orderType": "104"}, BEARER)
check("销户后再暂停被拒绝", body.get("code") == "409", str(body))
code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10, "specification": {}}, BEARER)
check("销户后主机回收、可再次上报", len(body["data"]["hosts"]) == len(hosts))

# ── 7. 批量预占 / 批量释放 ───────────────────────────────────────────────
print("[7] 11.1.9/11.1.10 批量预占与释放")
R1, R2 = "RS-B1", "RS-B2"
code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10, "specification": {}}, BEARER)
free = body["data"]["hosts"]
if len(free) >= 2:
    _bhosts = [{"reserveId": R1, "hostIp": free[0]["hostIp"],
                "hostRoomName": free[0]["hostRoomName"]},
               {"reserveId": R2, "hostIp": free[1]["hostIp"],
                "hostRoomName": free[1]["hostRoomName"]}]
else:
    _bhosts = [{"reserveId": R1, "hostIp": HOST_A["hostIp"],
                "hostRoomName": HOST_A["hostRoomName"]}]
code, body = post("/api/v1/compute/resource/batch/reserve/notify",
                  {"hosts": _bhosts}, BEARER)
check("批量预占 2 个事件", body.get("code") == "0", str(body))
code, body = post("/api/v1/compute/resource/batch/reserve/release",
                  {"reserveIds": f"{R1},{R2}", "description": "批量取消"}, BEARER)
check("批量释放", body.get("code") == "0")

# ── 8. 认证方式2：AES 密钥认证 ───────────────────────────────────────────
print("[8] 认证方式2：AES 密钥认证")
ts = str(int(time.time()))
nonce = uuid.uuid4().hex
from app.security.aes import encrypt as aes_encrypt                 # noqa: E402
cipher = aes_encrypt(f"{config.THIRD_OS_ID}|{ts}|{nonce}", config.AES_KEY)
code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10, "specification": {}},
                  {"Authorization": cipher})
check("AES 密钥认证通过", body.get("code") == "0" and code == 200, str(body))

stale = aes_encrypt(f"{config.THIRD_OS_ID}|{int(time.time()) - 9999}|{uuid.uuid4().hex}",
                    config.AES_KEY)
code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10, "specification": {}}, {"Authorization": stale})
check("过期时间戳被拒绝(防重放)", code == 401, f"got {code}")

code, body = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 10, "specification": {}}, {"Authorization": cipher})
check("同一 Nonce 重放被拒绝", code == 401, f"got {code}")

# ── 9. 认证方式3：Hmac-SM3 MAC 认证 ─────────────────────────────────────
print("[9] 认证方式3：Hmac-SM3 MAC 认证")
path = "/api/v1/compute/resource/host/collect"
payload = json.dumps({"scaleNum": 10, "specification": {}})
nonce = uuid.uuid4().hex
access_token = "mac-session-" + uuid.uuid4().hex[:8]
canonical = "\n".join(["POST", path, access_token, nonce,
                       hashlib.sha256(payload.encode()).hexdigest()])
mac = hmac_sm3_hex(config.MAC_KEY, canonical.encode())
mac_header = (f'MAC id="{config.THIRD_OS_ID}",access_token="{access_token}",'
              f'nonce="{nonce}",mac="{mac}",algorithm="hmac-sm3"')
r = requests.post(BASE + path, data=payload,
                  headers={"Authorization": mac_header,
                           "Content-Type": "application/json;charset=UTF-8"}, timeout=15)
check("Hmac-SM3 认证通过", r.json().get("code") == "0", r.text)

bad = mac_header.replace('mac="%s"' % mac, 'mac="%s"' % ("0" * 64))
r = requests.post(BASE + path, data=payload,
                  headers={"Authorization": bad,
                           "Content-Type": "application/json;charset=UTF-8"}, timeout=15)
check("篡改签名被拒绝(401)", r.status_code == 401, r.text)

print("=" * 64)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
