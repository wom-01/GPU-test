#!/usr/bin/env python3
"""规范第 11 章 · 逐接口逐参数严格测试

依据《第三方在线并网对接技术规范 v3.0》第 11 章（10 个接口）：
  - 请求：规范列出的必填 + 可选参数全部传入
  - 负例：每个必填参数逐个缺失，期望被拒绝
  - 响应：规范必填字段逐个校验 存在 / 非空 / 类型 / 枚举 / 格式
结果分级：✅ 符合  ❌ 不符合（必填缺失/为空/业务失败）  ⚠ 偏差（类型与规范表不一致）
"""
import base64, json, re, sys, time, urllib.error, urllib.request, uuid

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:12359").rstrip("/") + "/api/v1"
import os
USER, PWD = os.environ.get("AUTH_USERNAME", "jusuan_ops"), os.environ["AUTH_PASSWORD"]
THIRD_OS_ID = os.environ.get("THIRD_OS_ID", "")
AES_KEY = os.environ["AES_KEY"].encode()
ROOM = os.environ.get("TEST_HOST_ROOM", "测试机房")
OPEN_HOST = os.environ.get("TEST_HOST_IP", "127.0.0.1")
BATCH_HOSTS = [os.environ.get("TEST_BATCH_HOST_IP_1", "127.0.0.2"),
               os.environ.get("TEST_BATCH_HOST_IP_2", "127.0.0.3")]
RUN = time.strftime("%m%d%H%M%S")

stats = {"ok": 0, "bad": 0, "warn": 0}
problems = []


def mark(level, title, detail=""):
    icon = {"ok": "✅", "bad": "❌", "warn": "⚠️ "}[level]
    stats[level] += 1
    print(f"  {icon} {title}" + (f"  —— {detail}" if detail else ""))
    if level != "ok":
        problems.append((level, title, detail))


def post(path, body, token=None, raw_auth=None):
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    if raw_auth:
        h["Authorization"] = raw_auth
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), h)
    try:
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, json.loads(r.read()), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt), e.headers.get("Content-Type", "")
        except ValueError:
            return e.code, {"raw": txt[:120]}, e.headers.get("Content-Type", "")


def biz_ok(status, d):
    return status == 200 and str(d.get("code")) == "0"


def java_decrypt(miwen):
    iv, body = miwen[:16], miwen[16:]
    c = AES.new(AES_KEY, AES.MODE_CBC, iv.encode())
    return unpad(c.decrypt(base64.b64decode(body)), 16).decode()


# 类型判断：规范数据类型 → Python 判定
def type_ok(v, t):
    t = t.lower()
    if t == "string":
        return isinstance(v, str)
    if t in ("integer", "int", "long"):
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "float":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t in ("object", "struct"):
        return isinstance(v, dict)
    if t in ("array", "list"):
        return isinstance(v, list)
    return True


def check_obj(where, obj, spec):
    """spec: [(字段, 必填, 类型, 枚举或正则或None)]"""
    for name, required, typ, rule in spec:
        if name not in obj or obj[name] is None or obj[name] == "":
            if required:
                state = "缺失" if name not in obj else f"为空({obj[name]!r})"
                mark("bad", f"{where}.{name}（必填）", state)
            continue
        v = obj[name]
        if not type_ok(v, typ):
            mark("warn", f"{where}.{name}", f"规范 {typ}，实际 {type(v).__name__}={v!r}")
            continue
        if isinstance(rule, (set, tuple, list)) and str(v) not in rule:
            mark("bad", f"{where}.{name}", f"值 {v!r} 不在枚举 {sorted(rule)}")
            continue
        if isinstance(rule, str) and not re.fullmatch(rule, str(v)):
            mark("bad", f"{where}.{name}", f"值 {v!r} 格式不符")
            continue
        if required:
            mark("ok", f"{where}.{name}", repr(v)[:50])


def negative(name, path, full_body, required_keys, token, nested=None):
    """逐个去掉必填参数，期望被拒绝（HTTP 非 200 或业务码非 0）"""
    for k in required_keys:
        body = json.loads(json.dumps(full_body))
        if nested:
            for item in body[nested]:
                item.pop(k, None)
            label = f"{nested}[].{k}"
        else:
            body.pop(k, None)
            label = k
        st, d, _ = post(path, body, token)
        if biz_ok(st, d):
            mark("bad", f"负例 缺失 {label}", "未被拒绝，返回成功")
        else:
            mark("ok", f"负例 缺失 {label}", f"HTTP {st} / {d.get('code', '')} {str(d.get('message', d.get('detail', '')))[:40]}")


def section(t):
    print(f"\n{'─' * 96}\n{t}\n{'─' * 96}")


print("=" * 96)
print(f"规范第 11 章 · 逐接口逐参数严格测试   {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 96)

# ═══ 11.1.1 认证 ═══════════════════════════════════════════════════════════
section("11.1.1 第三方用户口令认证  POST /authentication/token")
body = {"thirdOSid": THIRD_OS_ID, "username": USER, "password": PWD}
st, d, ctype = post("/authentication/token", body)
if biz_ok(st, d):
    mark("ok", "全参数请求（thirdOSid+username+password）", d.get("message"))
else:
    mark("bad", "全参数请求", f"HTTP {st} {d}")
mark("ok" if "charset=utf-8" in ctype.lower() else "bad", "响应头 Content-Type 声明 UTF-8", ctype)
check_obj("data", d.get("data", {}), [
    ("issueAt", True, "string", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
    ("expireAt", True, "string", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
    ("accessToken", True, "string", None),
])
TOKEN = d["data"]["accessToken"]
st2, d2, _ = post("/authentication/token", {"username": USER, "password": PWD})
mark("ok" if biz_ok(st2, d2) else "bad", "可选参数 thirdOSid 不传", d2.get("message"))
negative("认证", "/authentication/token", body, ["username", "password"], None)
st3, d3, _ = post("/authentication/token", {"username": USER, "password": "wrong"})
mark("ok" if not biz_ok(st3, d3) else "bad", "负例 错误口令", f"HTTP {st3}")

# ═══ 11.1.2 资源上报 ═══════════════════════════════════════════════════════
section("11.1.2 算力资源上报  POST /compute/resource/host/collect")
collect_req = {"scaleNum": 80, "specification": {
    "bandwidth": 100, "memorySize": 256.0, "ssdDiskSize": "1024", "hardDiskSize": "0",
    "cpuNum": 64, "gpuBrand": "NVIDIA", "gpuModel": "RTX 4090", "gpuNum": 8,
    "gpuTotalMemory": "192", "gpuCudaCoreNum": 16384, "gpuTensorCoreNum": 512,
    "gpuRTCoreNum": 128, "gpuMemoryBandwidth": "1008", "gpuFP16Computing": "82.6",
    "gpuFP16TensorComputing": "165.2", "gpuFP32Computing": "82.6",
    "gpuTF32TensorComputing": "82.6", "gpuFP64Computing": "1.3",
    "gpuFP64TensorComputing": "1.3", "npuBrand": "Huawei", "npuModel": "Ascend 910B",
    "npuPhysicalCardNum": "8", "npuTotalMemory": "512"}}
st, d, _ = post("/compute/resource/host/collect", collect_req, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "全参数请求（scaleNum + specification 全部 23 个子字段）",
     f"HTTP {st} {d.get('message')} 返回 {len(d.get('data', {}).get('hosts', []))} 台")
st, d, _ = post("/compute/resource/host/collect", {"scaleNum": 80, "specification": {}}, TOKEN)
hosts = d.get("data", {}).get("hosts", [])
mark("ok" if biz_ok(st, d) and hosts else "bad", "仅必填参数（specification 为空对象）",
     f"返回 {len(hosts)} 台")
negative("采集", "/compute/resource/host/collect", collect_req, ["scaleNum", "specification"], TOKEN)
st, d, _ = post("/compute/resource/host/collect", {"scaleNum": 80, "specification": {}})
mark("ok" if not biz_ok(st, d) else "bad", "负例 无鉴权", f"HTTP {st}")

HOST_SPEC = [
    ("hostName", True, "string", None), ("hostIp", True, "string", None),
    ("publicIp", False, "string", None), ("areaCode", True, "string", None),
    ("hostRoomName", True, "string", None),
    ("status", True, "string", {"normal", "abnormal", "maintenance", "unknown"}),
    ("hostType", True, "string", {"physical", "virtual"}),
    ("specification", True, "object", None)]
SPEC_SPEC = [
    ("bandwidth", True, "long", None), ("memorySize", True, "float", None),
    ("ssdDiskSize", False, "string", None), ("hardDiskSize", True, "string", None),
    ("cpuNum", True, "integer", None), ("cpuArch", True, "string", {"x86_64", "arm64"}),
    ("cpuModel", True, "string", None), ("osName", True, "string", None),
    ("osImageSource", False, "string", None), ("brand", False, "string", None),
    ("deviceModel", True, "string", None), ("processorFrequency", True, "string", None),
    ("hostDescription", False, "string", None),
    ("gpuBrand", False, "string", None), ("gpuModel", False, "string", None),
    ("gpuNum", False, "integer", None), ("gpuTotalMemory", False, "string", None),
    ("gpuCudaCoreNum", False, "integer", None), ("gpuTensorCoreNum", False, "integer", None),
    ("gpuRTCoreNum", False, "integer", None), ("gpuMemoryBandwidth", False, "string", None),
    ("gpuFP16Computing", False, "string", None), ("gpuFP16TensorComputing", False, "string", None),
    ("gpuFP32Computing", False, "string", None), ("gpuTF32TensorComputing", False, "string", None),
    ("gpuFP64Computing", False, "string", None), ("gpuFP64TensorComputing", False, "string", None),
    ("npuBrand", False, "string", None), ("npuModel", False, "string", None),
    ("npuPhysicalCardNum", False, "string", None), ("npuTotalMemory", False, "string", None)]
for h in hosts:
    tag = f"{h.get('hostIp')}"
    print(f"  ▸ 主机 {tag} {h.get('hostName')}")
    check_obj(tag, h, HOST_SPEC)
    check_obj(f"{tag}.spec", h.get("specification") or {}, SPEC_SPEC)
    extra = set(h) - {f[0] for f in HOST_SPEC}
    if extra:
        mark("warn", f"{tag} 出现规范外字段", sorted(extra))
    gpu_opt = [f[0] for f in SPEC_SPEC if f[0].startswith("gpu")]
    have = [f for f in gpu_opt if (h.get("specification") or {}).get(f) not in (None, "")]
    print(f"     GPU 可选属性上报 {len(have)}/{len(gpu_opt)}：缺 {sorted(set(gpu_opt) - set(have))}")

# ═══ 11.1.3 预占 / 11.1.4 预占释放 ════════════════════════════════════════
section("11.1.3 预占  POST /compute/resource/reserve/notify")
RS = f"RS-STRICT-{RUN}"
rbody = {"reserveId": RS, "hosts": [{"hostIp": OPEN_HOST, "hostRoomName": ROOM}]}
negative("预占", "/compute/resource/reserve/notify", rbody, ["reserveId", "hosts"], TOKEN)
negative("预占", "/compute/resource/reserve/notify", rbody, ["hostIp", "hostRoomName"], TOKEN, nested="hosts")
st, d, _ = post("/compute/resource/reserve/notify", rbody, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "全参数预占", d.get("message"))
st, d, _ = post("/compute/resource/reserve/notify", rbody, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "同一 reserveId 重复预占（幂等）", d.get("message"))
st, d, _ = post("/compute/resource/reserve/notify",
                {"reserveId": RS + "-X", "hosts": [{"hostIp": OPEN_HOST, "hostRoomName": ROOM}]}, TOKEN)
mark("ok" if not biz_ok(st, d) else "bad", "负例 他人重复预占同一主机（防超卖）", d.get("message"))
st, d, _ = post("/compute/resource/reserve/notify",
                {"reserveId": RS + "-N", "hosts": [{"hostIp": "10.0.0.1", "hostRoomName": ROOM}]}, TOKEN)
mark("ok" if not biz_ok(st, d) else "bad", "负例 不存在的主机", d.get("message"))

section("11.1.4 预占释放  POST /compute/resource/reserve/release")
negative("释放", "/compute/resource/reserve/release", {"reserveId": RS}, ["reserveId"], TOKEN)
st, d, _ = post("/compute/resource/reserve/release", {"reserveId": RS, "description": "严格测试-释放"}, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "全参数释放（reserveId + description）", d.get("message"))
st, d, _ = post("/compute/resource/reserve/release", {"reserveId": RS}, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "重复释放（幂等）", d.get("message"))
st, d, _ = post("/compute/resource/reserve/notify", rbody, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "已释放的 reserveId 再次预占", d.get("message"))

# ═══ 11.1.5 开通 ═══════════════════════════════════════════════════════════
section("11.1.5 开通  POST /compute/resource/host/open")
OP = f"OP-STRICT-{RUN}"
obody = {"openId": OP, "reserveId": RS, "userId": "9900030001",
         "orderStartTime": time.strftime("%Y-%m-%d %H:%M:%S"),
         "hosts": [{"hostIp": OPEN_HOST, "hostRoomName": ROOM}]}
negative("开通", "/compute/resource/host/open", obody,
         ["openId", "reserveId", "userId", "orderStartTime", "hosts"], TOKEN)
negative("开通", "/compute/resource/host/open", obody, ["hostIp", "hostRoomName"], TOKEN, nested="hosts")
bad_time = dict(obody, openId=OP + "-T", orderStartTime="2026/10/22 10:00")
st, d, _ = post("/compute/resource/host/open", bad_time, TOKEN)
mark("ok" if not biz_ok(st, d) else "warn", "负例 orderStartTime 非 yyyy-MM-dd HH:mm:ss", d.get("message"))
mismatch = dict(obody, openId=OP + "-M", hosts=[{"hostIp": os.environ.get("TEST_MISMATCH_HOST_IP", "127.0.0.4"), "hostRoomName": ROOM}])
st, d, _ = post("/compute/resource/host/open", mismatch, TOKEN)
mark("ok" if not biz_ok(st, d) else "warn", "负例 hosts 与预占主机不一致", d.get("message"))
st, d, _ = post("/compute/resource/host/open", obody, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "全参数开通", d.get("message"))
st, d, _ = post("/compute/resource/host/open", obody, TOKEN)
mark("ok" if not biz_ok(st, d) else "warn", "同一 openId 重复开通", f"{d.get('code')} {d.get('message')}")

# ═══ 11.1.6 开通结果查询 ═══════════════════════════════════════════════════
section("11.1.6 开通结果查询  POST /compute/resource/host/open/query")
negative("查询", "/compute/resource/host/open/query", {"openId": OP}, ["openId"], TOKEN)
st, d, _ = post("/compute/resource/host/open/query", {"openId": "NOT-EXIST-" + RUN}, TOKEN)
mark("ok" if not biz_ok(st, d) else "bad", "负例 不存在的 openId", d.get("message"))
final = {}
for i in range(15):
    time.sleep(2)
    st, d, _ = post("/compute/resource/host/open/query", {"openId": OP, "description": "严格测试-查询"}, TOKEN)
    hs = d.get("data", {}).get("hosts", [])
    if hs:
        final = hs[0]
        if final.get("openCode") in ("0", "2"):
            break
print(f"  ▸ 轮询 {i + 1} 次，openCode={final.get('openCode')} {final.get('openMsg')}")
check_obj("hosts[0]", final, [
    ("publicIp", True, "string", None), ("publicSshPort", True, "string", None),
    ("username", True, "string", None), ("password", True, "string", None),
    ("openCode", True, "string", {"0", "2", "3", "4"}), ("openMsg", True, "string", None)])
opened = final.get("openCode") == "0"
if opened:
    for f in ("publicSshPort", "username", "password"):
        try:
            plain = java_decrypt(final[f])
            mark("ok", f"{f} 加密（Java AESCBCUtil 口径可解）", f"明文长度 {len(plain)}")
        except Exception as exc:
            mark("bad", f"{f} 加密", f"Java 口径解密失败：{exc}")
else:
    mark("bad", "开通结果", f"未开通成功：{final.get('openMsg')}")

# ═══ 11.1.7 监控采集 ═══════════════════════════════════════════════════════
section("11.1.7 监控数据采集  POST /compute/resource/host/monitor/collect")
mon_all = {"thirdOSid": THIRD_OS_ID, "providerName": "厦门界云聚算网络科技有限公司",
           "hosts": [{"hostName": h["hostName"], "hostIp": h["hostIp"],
                      "publicIp": h.get("publicIp"), "hostType": h["hostType"],
                      "areaCode": h["areaCode"], "hostRoomName": h["hostRoomName"]}
                     for h in hosts[:3]]}
negative("监控", "/compute/resource/host/monitor/collect", mon_all, ["hosts"], TOKEN)
negative("监控", "/compute/resource/host/monitor/collect", mon_all, ["hostIp", "hostRoomName"], TOKEN, nested="hosts")
st, d, _ = post("/compute/resource/host/monitor/collect", mon_all, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "全参数请求（thirdOSid+providerName+hosts 6 个子字段）",
     f"返回 {len(d.get('data', {}).get('hosts', []))} 台")
st2, d2, _ = post("/compute/resource/host/monitor/collect",
                  {"hosts": [{"hostIp": h["hostIp"], "hostRoomName": h["hostRoomName"]} for h in hosts[:1]]}, TOKEN)
mark("ok" if biz_ok(st2, d2) else "bad", "仅必填参数（hostIp+hostRoomName）", d2.get("message"))
MON_SPEC = [
    ("hostName", True, "string", None), ("hostIp", True, "string", None),
    ("publicIp", True, "string", None), ("areaCode", True, "string", None),
    ("hostRoomName", True, "string", None),
    ("status", True, "string", {"normal", "abnormal", "maintenance", "unknown"}),
    ("usageCPU", True, "string", r"\d+(\.\d+)?%"), ("cpuNum", True, "int", None),
    ("usageMemory", True, "string", r"\d+(\.\d+)?%"), ("memorySize", True, "float", None),
    ("usageSSDDisk", False, "string", None), ("ssdDiskSize", False, "float", None),
    ("usagehardDisk", True, "string", r"\d+(\.\d+)?%"), ("hardDiskSize", True, "float", None),
    ("gpuNum", False, "int", None), ("usageGpu", False, "string", None),
    ("gpuTotalMemory", False, "string", None), ("gpuUsedMemory", False, "string", None),
    ("npuPhysicalCardNum", False, "int", None), ("usageNpu", False, "string", None),
    ("npuTotalMemory", False, "string", None), ("npuUsedMemory", False, "string", None),
    ("updateTime", True, "string", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")]
for m in d.get("data", {}).get("hosts", []):
    tag = m.get("hostIp")
    print(f"  ▸ 主机 {tag}")
    check_obj(tag, m, MON_SPEC)
    gpu4 = ["gpuNum", "usageGpu", "gpuTotalMemory", "gpuUsedMemory"]
    miss = [f for f in gpu4 if m.get(f) in (None, "")]
    mark("bad" if miss else "ok", f"{tag} GPU 主机返回 GPU 监控 4 字段", f"缺 {miss}" if miss else "齐全")

# ═══ 11.1.8 订单操作 ═══════════════════════════════════════════════════════
section("11.1.8 预销户/撤销/销户/暂停/恢复  POST /compute/resource/host/order/update")
negative("订单", "/compute/resource/host/order/update", {"openId": OP, "orderType": "104"},
         ["openId", "orderType"], TOKEN)
st, d, _ = post("/compute/resource/host/order/update", {"openId": OP, "orderType": "999"}, TOKEN)
mark("ok" if not biz_ok(st, d) else "bad", "负例 非法 orderType=999", d.get("message"))
st, d, _ = post("/compute/resource/host/order/update", {"openId": "NOT-EXIST-" + RUN, "orderType": "104"}, TOKEN)
mark("ok" if not biz_ok(st, d) else "bad", "负例 不存在的 openId", d.get("message"))
if opened:
    for ot, label in [("104", "暂停"), ("105", "恢复"), ("107", "预销户"), ("108", "撤销预销户"),
                      ("107", "再次预销户"), ("109", "正式销户")]:
        st, d, _ = post("/compute/resource/host/order/update", {"openId": OP, "orderType": ot}, TOKEN)
        mark("ok" if biz_ok(st, d) else "bad", f"{ot} {label}", d.get("message"))
    st, d, _ = post("/compute/resource/host/order/update", {"openId": OP, "orderType": "105"}, TOKEN)
    mark("ok" if not biz_ok(st, d) else "bad", "负例 已销户订单再操作", d.get("message"))
    st, d, _ = post("/compute/resource/reserve/notify",
                    {"reserveId": RS + "-AFTER", "hosts": [{"hostIp": OPEN_HOST, "hostRoomName": ROOM}]}, TOKEN)
    mark("ok" if biz_ok(st, d) else "bad", "销户后主机可重新预占（预占已随销户释放）", d.get("message"))
    post("/compute/resource/reserve/release", {"reserveId": RS + "-AFTER"}, TOKEN)
else:
    post("/compute/resource/reserve/release", {"reserveId": RS}, TOKEN)
    mark("bad", "104/105/107/108/109", "开通未成功，无法测试订单操作")

# ═══ 11.1.9 批量预占 / 11.1.10 批量释放 ═══════════════════════════════════
section("11.1.9 批量预占  POST /compute/resource/batch/reserve/notify")
ids = [f"RS-STRICT-{RUN}-B{i}" for i in (1, 2)]
bbody = {"hosts": [{"reserveId": r, "hostIp": ip, "hostRoomName": ROOM} for r, ip in zip(ids, BATCH_HOSTS)]}
negative("批量预占", "/compute/resource/batch/reserve/notify", bbody, ["hosts"], TOKEN)
negative("批量预占", "/compute/resource/batch/reserve/notify", bbody,
         ["reserveId", "hostIp", "hostRoomName"], TOKEN, nested="hosts")
st, d, _ = post("/compute/resource/batch/reserve/notify", bbody, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "全参数批量预占（2 台）", d.get("message"))

section("11.1.10 批量预占释放  POST /compute/resource/batch/reserve/release")
negative("批量释放", "/compute/resource/batch/reserve/release", {"reserveIds": ",".join(ids)}, ["reserveIds"], TOKEN)
st, d, _ = post("/compute/resource/batch/reserve/release",
                {"reserveIds": ",".join(ids), "description": "严格测试-批量释放"}, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "全参数批量释放（reserveIds 逗号分隔 + description）", d.get("message"))
st, d, _ = post("/compute/resource/reserve/notify",
                {"reserveId": ids[0] + "-CHK", "hosts": [{"hostIp": BATCH_HOSTS[0], "hostRoomName": ROOM}]}, TOKEN)
mark("ok" if biz_ok(st, d) else "bad", "批量释放后主机确实可再预占", d.get("message"))
post("/compute/resource/reserve/release", {"reserveId": ids[0] + "-CHK"}, TOKEN)

# ═══ 认证方式 ②③ 覆盖（规范第 9 章，所有接口通用） ════════════════════════
section("附：AES 密钥认证（Java AESCBCUtil 口径）")
iv = uuid.uuid4().hex[:16]
c = AES.new(AES_KEY, AES.MODE_CBC, iv.encode())
from Crypto.Util.Padding import pad
plain = f"{THIRD_OS_ID}|{int(time.time())}|{uuid.uuid4().hex}"
hdr = iv + base64.b64encode(c.encrypt(pad(plain.encode(), 16))).decode()
st, d, _ = post("/compute/resource/host/collect", {"scaleNum": 1, "specification": {}}, raw_auth=hdr)
mark("ok" if biz_ok(st, d) else "bad", "AES 认证头调用资源上报", d.get("message"))

# ═══ 汇总 ═════════════════════════════════════════════════════════════════
print("\n" + "=" * 96)
print(f"汇总：✅ 符合 {stats['ok']}   ❌ 不符合 {stats['bad']}   ⚠️  偏差 {stats['warn']}")
print("=" * 96)
if problems:
    print("\n问题清单（去重）：")
    seen = set()
    for lvl, t, dt in problems:
        key = re.sub(r"^\d+\.\d+\.\d+\.\d+", "<host>", t)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {'❌' if lvl == 'bad' else '⚠️ '} {key}  —— {dt}")
