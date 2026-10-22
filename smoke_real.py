"""真实数据源（STORE_BACKEND=dgm）下的全流程冒烟测试。

与 test_client.py（演示数据回归）互补：本脚本不假设任何主机名/IP，
全部从 collect 动态取，验证 DGM 真实台账 + 网关状态表 + 凭证交付链路。

用法：python3 smoke_real.py [BASE_URL]   # 默认 http://127.0.0.1:12359
"""
import json
import sys
import time
import uuid

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else __import__("os").environ.get("API_BASE_URL", "http://127.0.0.1:12359")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from app import config                            # noqa: E402
from app.security.aes import decrypt as aes_dec   # noqa: E402

PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    PASS, FAIL = PASS + bool(cond), FAIL + (not cond)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  —— {detail}" if detail and not cond else ""))


def post(path, payload, token=None):
    h = {"Content-Type": "application/json;charset=UTF-8"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return requests.post(BASE + path, data=json.dumps(payload), headers=h, timeout=15).json()


def msg(body):
    return body.get("message", "")


print(f"目标：{BASE}（真实数据源）\n" + "=" * 60)

token = post("/api/v1/authentication/token",
             {"username": config.AUTH_USERNAME, "password": config.AUTH_PASSWORD}
             )["data"]["accessToken"]

# 1. collect：可售主机
hosts = post("/api/v1/compute/resource/host/collect",
             {"scaleNum": 20, "specification": {}}, token)["data"]["hosts"]
check(f"collect 返回真实可售主机（{len(hosts)} 台）", len(hosts) >= 1)
check("字段符合规范（hostRoomName/hostIp/areaCode/specification）",
      all(h.get("hostRoomName") and h.get("hostIp") and h.get("areaCode")
          and h.get("specification") for h in hosts))
if not hosts:
    print("无可售主机，终止"); sys.exit(1)

# 2. 预占第一台 → 重复预占拒绝 → 释放幂等
target = hosts[0]
ref = {"hostIp": target["hostIp"], "hostRoomName": target["hostRoomName"]}
rid = "RS-SMOKE-" + uuid.uuid4().hex[:8].upper()
check("预占成功", post("/api/v1/compute/resource/reserve/notify",
                       {"reserveId": rid, "hosts": [ref]}, token)["code"] == "0")
check("重复预占被拒", post("/api/v1/compute/resource/reserve/notify",
                            {"reserveId": "RS-SMOKE-OTHER", "hosts": [ref]}, token)["code"] != "0")
again = post("/api/v1/compute/resource/host/collect",
             {"scaleNum": 20, "specification": {}}, token)["data"]["hosts"]
check("预占后主机从可售列表消失",
      all(not (h["hostIp"] == ref["hostIp"] and h["hostRoomName"] == ref["hostRoomName"])
          for h in again))

# 3. 开通 → 轮询（凭证缺失的节点应得到 openCode=2 的明确失败原因）
oid = "OP-SMOKE-" + uuid.uuid4().hex[:8].upper()
check("开通受理", post("/api/v1/compute/resource/host/open",
                        {"openId": oid, "reserveId": rid, "userId": "9900012345",
                         "orderStartTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "hosts": [ref]}, token)["code"] == "0")
final = None
for _ in range(15):
    h0 = post("/api/v1/compute/resource/host/open/query", {"openId": oid}, token)["data"]["hosts"][0]
    final = h0
    if h0["openCode"] in ("0", "2"):
        break
    time.sleep(1)
check(f"开通有终态（openCode={final['openCode']}：{final['openMsg']}）",
      final["openCode"] in ("0", "2"))

if final["openCode"] == "0":
    plain = {k: aes_dec(final[k], config.AES_KEY) for k in ("publicSshPort", "username", "password")}
    check("交付凭证为AES密文且可解密（内容不回显）",
          all(plain.values()) and final["password"] != plain["password"])
    # 4. 监控
    m = post("/api/v1/compute/resource/host/monitor/collect",
             {"hosts": [dict(ref, hostName=target["hostName"])]}, token)["data"]["hosts"][0]
    check("监控字段齐备", all(k in m for k in ("usageCPU", "usageMemory", "updateTime")))
    # 5. 生命周期：104/105/107/108/109
    for ot, name in [("104", "暂停"), ("105", "恢复"), ("107", "预销户"),
                     ("108", "撤销预销户")]:
        check(f"{name}({ot})", post("/api/v1/compute/resource/host/order/update",
                                    {"openId": oid, "orderType": ot}, token)["code"] == "0")
    check("销户(109)", post("/api/v1/compute/resource/host/order/update",
                            {"openId": oid, "orderType": "109"}, token)["code"] == "0")
    check("销户后凭证已清除",
          post("/api/v1/compute/resource/host/open/query", {"openId": oid}, token)
          ["data"]["hosts"][0]["password"] == "")
else:
    print("  ℹ️ 该节点缺少SSH凭证（openCode=2 属预期），验证释放后回池")
    check("预占释放", post("/api/v1/compute/resource/reserve/release",
                           {"reserveId": rid}, token)["code"] == "0")
    hosts2 = post("/api/v1/compute/resource/host/collect",
                  {"scaleNum": 20, "specification": {}}, token)["data"]["hosts"]
    check("释放后主机回池", any(h["hostIp"] == ref["hostIp"] for h in hosts2))

    # 换一台继续完整生命周期
    rest = [h for h in hosts2 if h["hostIp"] != ref["hostIp"]]
    if rest:
        t2, ref2 = rest[0], {"hostIp": rest[0]["hostIp"], "hostRoomName": rest[0]["hostRoomName"]}
        rid2 = "RS-SMOKE-" + uuid.uuid4().hex[:8].upper()
        oid2 = "OP-SMOKE-" + uuid.uuid4().hex[:8].upper()
        post("/api/v1/compute/resource/reserve/notify", {"reserveId": rid2, "hosts": [ref2]}, token)
        post("/api/v1/compute/resource/host/open", {"openId": oid2, "reserveId": rid2,
                                                    "userId": "9900012345",
                                                    "orderStartTime": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                    "hosts": [ref2]}, token)
        for _ in range(15):
            f2 = post("/api/v1/compute/resource/host/open/query", {"openId": oid2}, token)["data"]["hosts"][0]
            if f2["openCode"] in ("0", "2"):
                break
            time.sleep(1)
        if f2["openCode"] == "0":
            for ot in ("104", "105", "107", "108"):
                post("/api/v1/compute/resource/host/order/update", {"openId": oid2, "orderType": ot}, token)
            check("第二台完整生命周期", post("/api/v1/compute/resource/host/order/update",
                                              {"openId": oid2, "orderType": "109"}, token)["code"] == "0")
        post("/api/v1/compute/resource/reserve/release", {"reserveId": rid2}, token)

# 6. 清理：确保测试预占全部释放
post("/api/v1/compute/resource/reserve/release", {"reserveId": rid}, token)

print("=" * 60)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
