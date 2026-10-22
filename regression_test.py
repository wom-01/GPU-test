#!/usr/bin/env python3
"""聚算并网南向接口 · 全量接口测试 v2"""
import json, time, urllib.request, urllib.error

import os
BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:12359")
USER, PWD = os.environ.get("AUTH_USERNAME", "jusuan_ops"), os.environ["AUTH_PASSWORD"]
HOST = {"hostIp": os.environ.get("TEST_HOST_IP", "127.0.0.1"),
        "hostRoomName": os.environ.get("TEST_HOST_ROOM", "测试机房")}
RUN = time.strftime("%m%d%H%M%S")
RS1, OP1 = f"RS-T{RUN}", f"OP-T{RUN}"
NEGATIVE = set()
PASS = FAIL = 0

def call(name, method, path, body=None, token=None, note="", want_ok=True):
    global PASS, FAIL
    req = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + token} if token else {})})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            code, d = r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        code, d = e.code, json.loads(e.read().decode())
    ms = int((time.time() - t0) * 1000)
    biz = d.get("code", d.get("detail", d.get("ok", "-")))
    msg = d.get("message", d.get("detail", ""))
    ok = (str(biz) == "0" or biz is True) if want_ok else (str(biz) != "0")
    mark = "✅" if ok else "❌"
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"{mark} {name:<16} HTTP {code} | 业务码 {biz} | {ms}ms | {msg}")
    if note: print(f"   └ 备注: {note}")
    return d

print("=" * 72)
print("聚算并网南向接口 · 全量测试 v2  ", time.strftime("%Y-%m-%d %H:%M:%S"))
print("=" * 72, "\n")

# 0. 健康检查（无鉴权）
call("健康检查", "GET", "/healthz", note='期望 {"ok":true}')

# 1. 认证
d = call("① 认证", "POST", "/api/v1/authentication/token",
         {"thirdOSid": os.environ.get("THIRD_OS_ID", ""), "username": USER, "password": PWD},
         note="换取 2h JWT")
token = d["data"]["accessToken"]

# 2. 负例：错误密码
NEGATIVE.add("认证-负例")
call("认证-负例", "POST", "/api/v1/authentication/token",
     {"thirdOSid": "x", "username": USER, "password": "wrong-password"},
     note="期望 401", want_ok=False)
NEGATIVE.discard("认证-负例")

# 3. 负例：无令牌
NEGATIVE.add("鉴权-负例")
call("鉴权-负例", "POST", "/api/v1/compute/resource/host/collect",
     {"scaleNum": 10, "specification": {}}, note="期望 401", want_ok=False)
NEGATIVE.discard("鉴权-负例")

# 4. 主机采集
d = call("② 主机采集", "POST", "/api/v1/compute/resource/host/collect",
         {"scaleNum": 10, "specification": {}}, token,
         note=f"主机池: {[h['hostIp']+'/'+h['hostName'] for h in d.get('data',{}).get('hosts',[])]}")

# 5. 预占
call("③ 预占", "POST", "/api/v1/compute/resource/reserve/notify",
     {"reserveId": RS1, "hosts": [HOST]}, token)

# 6. 负例：不存在的预占单开通
NEGATIVE.add("开通-负例")
call("开通-负例", "POST", "/api/v1/compute/resource/host/open",
     {"openId": "OP-BAD", "reserveId": "RS-NOT-EXIST", "userId": "9900030001",
      "orderStartTime": "2026-10-21 10:00:00", "hosts": [HOST]},
     token, note="期望拒绝", want_ok=False)
NEGATIVE.discard("开通-负例")

# 7. 开通
call("④ 开通", "POST", "/api/v1/compute/resource/host/open",
     {"openId": OP1, "reserveId": RS1, "userId": "9900030001",
      "orderStartTime": "2026-10-21 10:00:00", "hosts": [HOST]}, token)

# 8. 轮询开通结果（最多 30s）
print("⑤ 开通结果轮询:", flush=True)
final = None
for i in range(10):
    d = call(f"  轮询#{i+1}", "POST", "/api/v1/compute/resource/host/open/query",
             {"openId": OP1}, token)
    hosts = (d.get("data") or {}).get("hosts") or [{}]
    oc = hosts[0].get("openCode", "?")
    print(f"   └ openCode={oc} ({hosts[0].get('openMsg','')})")
    if oc != "4":
        final = hosts[0]; break
    time.sleep(3)
if final:
    print(f"   最终: openCode={final.get('openCode')} | publicIp={final.get('publicIp')}:{final.get('publicSshPort')} | 用户={final.get('username')}\n")

# 9. 监控采集
call("⑥ 监控采集", "POST", "/api/v1/compute/resource/host/monitor/collect",
     {"hosts": [HOST]}, token)

# 10. 订单生命周期：暂停→恢复
call("⑦ 订单暂停(104)", "POST", "/api/v1/compute/resource/host/order/update",
     {"openId": OP1, "orderType": "104"}, token)
call("⑧ 订单恢复(105)", "POST", "/api/v1/compute/resource/host/order/update",
     {"openId": OP1, "orderType": "105"}, token)

# 11. 批量预占
call("⑨ 批量预占", "POST", "/api/v1/compute/resource/batch/reserve/notify",
     {"hosts": [
        {"reserveId": f"RS-T{RUN}-B1", "hostIp": os.environ.get("TEST_BATCH_HOST_IP_1", "127.0.0.2"), "hostRoomName": HOST["hostRoomName"]},
        {"reserveId": f"RS-T{RUN}-B2", "hostIp": os.environ.get("TEST_BATCH_HOST_IP_2", "127.0.0.3"), "hostRoomName": HOST["hostRoomName"]}]}, token)

# 12. 批量预占释放
call("⑩ 批量预占释放", "POST", "/api/v1/compute/resource/batch/reserve/release",
     {"reserveIds": f"RS-T{RUN}-B1,RS-T{RUN}-B2"}, token)

# 13. 预销户 → 撤销预销户 → 正式销户（同时清理现场）
call("⑪ 预销户(107)", "POST", "/api/v1/compute/resource/host/order/update",
     {"openId": OP1, "orderType": "107"}, token)
call("⑫ 撤销预销户(108)", "POST", "/api/v1/compute/resource/host/order/update",
     {"openId": OP1, "orderType": "108"}, token)
call("⑬ 正式销户(109)", "POST", "/api/v1/compute/resource/host/order/update",
     {"openId": OP1, "orderType": "109"}, token)

# 14. 销户后同一主机可立即重新预占（验证 109 自动释放预占）
call("⑭ 销户后重新预占", "POST", "/api/v1/compute/resource/reserve/notify",
     {"reserveId": f"RS-T{RUN}-R", "hosts": [HOST]}, token)
call("⑮ 释放复测预占", "POST", "/api/v1/compute/resource/reserve/release",
     {"reserveId": f"RS-T{RUN}-R"}, token)

print()
print("=" * 72)
print(f"测试完成：通过 {PASS} / 失败 {FAIL}")
print("=" * 72)
