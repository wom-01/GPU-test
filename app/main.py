"""聚算交易服务平台 · 第三方在线并网对接 —— 接口服务端入口。

运行：
    uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import json
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .routers import auth_routes, compute
from .security.auth import AuthError
from .store import BizError, store

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="界云算力 · 算力并网三方系统接口",
    description="第三方在线并网对接（v3.0 第11章接口要求）。"
                "认证：令牌 / AES 密钥 / Hmac-SM3 三选一。",
    version="0.6.0",
    docs_url=None,   # 使用下方自定义文档页（本地静态资源 + 中文布局）
    redoc_url=None,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth_routes.router)
app.include_router(compute.router)


# 在线调试的请求示例：一条可顺序执行的完整下单链路（预占→开通→查询→监控→订单操作）
_DEMO_HOST = {"hostIp": "203.0.113.11", "hostRoomName": "示例算力机房"}
REQUEST_EXAMPLES = {
    "/api/v1/authentication/token": {"username": "<AUTH_USERNAME>", "password": "<AUTH_PASSWORD>"},
    "/api/v1/compute/resource/host/collect": {"scaleNum": 10, "specification": {}},
    "/api/v1/compute/resource/reserve/notify": {"reserveId": "RS202610260001", "hosts": [_DEMO_HOST]},
    "/api/v1/compute/resource/reserve/release": {"reserveId": "RS202610260001", "description": "客户取消"},
    "/api/v1/compute/resource/host/open": {
        "openId": "OP202610260001", "reserveId": "RS202610260001", "userId": "9900030001",
        "orderStartTime": "2026-10-20 10:00:00", "hosts": [_DEMO_HOST]},
    "/api/v1/compute/resource/host/open/query": {"openId": "OP202610260001"},
    "/api/v1/compute/resource/host/monitor/collect": {"hosts": [_DEMO_HOST]},
    "/api/v1/compute/resource/host/order/update": {"openId": "OP202610260001", "orderType": "104"},
    "/api/v1/compute/resource/batch/reserve/notify": {"hosts": [
        {"reserveId": "RS202610260002", "hostIp": "203.0.113.12", "hostRoomName": "示例算力机房"},
        {"reserveId": "RS202610260003", "hostIp": "203.0.113.13", "hostRoomName": "示例算力机房"}]},
    "/api/v1/compute/resource/batch/reserve/release": {"reserveIds": "RS202610260002,RS202610260003"},
}


def custom_openapi():
    """声明 Bearer 安全方案，让 Swagger 页面出现 Authorize 按钮。"""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    schema = get_openapi(title=app.title, version=app.version,
                         description=app.description, routes=app.routes)
    schema.setdefault("components", {})["securitySchemes"] = {
        "bearerAuth": {
            "type": "http", "scheme": "bearer", "bearerFormat": "JWT",
            "description": "粘贴认证接口 /api/v1/authentication/token 返回的 accessToken（无需 Bearer 前缀）",
        }
    }
    for path, methods in schema.get("paths", {}).items():
        if path in REQUEST_EXAMPLES:
            for method in methods.values():
                body = method.get("requestBody", {}).get("content", {}).get("application/json")
                if body is not None:
                    body["example"] = REQUEST_EXAMPLES[path]
        if path == "/api/v1/authentication/token":
            continue                     # 认证接口本身无需令牌
        for method in methods.values():
            method.setdefault("security", [{"bearerAuth": []}])
            # Authorization 头由安全方案统一注入，不再作为普通参数重复展示
            params = [x for x in method.get("parameters", [])
                      if not (x.get("in") == "header" and x.get("name", "").lower() == "authorization")]
            if params:
                method["parameters"] = params
            else:
                method.pop("parameters", None)
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


@app.exception_handler(AuthError)
async def auth_error_handler(request: Request, exc: AuthError):
    return JSONResponse(status_code=401,
                        content={"code": "401", "message": exc.message, "data": {}})


@app.exception_handler(BizError)
async def biz_error_handler(request: Request, exc: BizError):
    return JSONResponse(status_code=200,
                        content={"code": exc.code, "message": exc.message, "data": {}})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400,
                        content={"code": "400", "message": f"请求参数非法：{exc.errors()[:3]}",
                                 "data": {}})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True, "thirdOSid": config.THIRD_OS_ID}


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@app.get("/docs", include_in_schema=False)
def docs_page():
    """接口中心页面：HTML/CSS/JS 为独立文件，服务端只注入一段 JSON 配置。"""
    cfg = {"mode": config.STORE_BACKEND}
    if config.STORE_BACKEND == "demo":   # 仅演示环境下发内置账号，生产页不含口令
        cfg.update(demoUser=config.AUTH_USERNAME, demoPass=config.AUTH_PASSWORD)
    cfg_json = json.dumps(cfg, ensure_ascii=False).replace("</", "<\\/")
    html = (TEMPLATE_DIR / "docs.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__DOCS_CFG__", cfg_json),
                        headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh_CN"><head><meta charset="UTF-8"><title>界云算力 · 算力并网接口</title>
<style>body{font-family:system-ui,sans-serif;max-width:640px;margin:60px auto;
color:#203746;line-height:1.7} h1{font-size:22px} code{background:#eef5f8;
padding:2px 6px;border-radius:4px} a{color:#087fc4}</style></head><body>
<h1>✅ 界云算力 · 算力并网三方系统接口</h1>
<p>服务运行正常。本服务是给<b>算力交易运营平台</b>回调调用的 API，浏览器直接访问根路径没有页面。</p>
<ul>
<li>接口可视化文档（Swagger）：<a href="/docs">/docs</a></li>
<li>接口基址：<code id="apiroot"></code></li>
<li>认证账号：<code>{config.AUTH_USERNAME or '通过交付渠道获取'}</code>（口令见交付渠道，POST /api/v1/authentication/token 换令牌）</li>
<li>健康检查：<a href="/healthz">/healthz</a></li>
</ul>
<p>联调自测：<code>python3 test_client.py 当前地址</code></p>
<script>document.getElementById("apiroot").textContent = location.origin + "/api/v1";</script>
</body></html>""")


@app.middleware("http")
async def force_utf8_charset(request, call_next):
    """所有 JSON 响应显式声明 charset=utf-8，避免平台侧按默认编码解码出现乱码。"""
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    if ctype.startswith("application/json") and "charset" not in ctype:
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response


@app.on_event("startup")
def init_store():
    """dgm 模式：启动后台同步线程；demo 模式：灌入演示主机。"""
    if config.STORE_BACKEND != "dgm":
        seed_demo_hosts()
        return

    def sync_loop():
        import time
        while True:
            time.sleep(config.DGM_SYNC_INTERVAL)
            try:
                store.refresh()
            except Exception as exc:    # noqa: BLE001
                print(f"[store] ⚠️ DGM 同步失败：{exc}", flush=True)

    if config.DGM_SYNC_INTERVAL > 0:
        threading.Thread(target=sync_loop, daemon=True).start()

    def expiry_loop():
        import time
        while True:
            time.sleep(max(config.EXPIRY_CHECK_INTERVAL, 60))
            try:
                for line in store.sweep_expired():
                    print(f"[expiry] {line}", flush=True)
            except Exception as exc:    # noqa: BLE001
                print(f"[expiry] ⚠️ 扫描失败：{exc}", flush=True)

    threading.Thread(target=expiry_loop, daemon=True).start()


def seed_demo_hosts():
    """客户演示数据：多区域、多型号（GPU/NPU）、规格齐全、状态多样。"""

    def host(name, room, area, ip, pip, status, host_type, **spec):
        base = {"cpuArch": "x86_64", "osName": "Ubuntu 22.04",
                "osImageSource": "Ubuntu官网", "hostDescription": "AI训练/推理算力服务器"}
        base.update(spec)
        return {"hostName": name, "hostIp": ip, "publicIp": pip,
                "areaCode": area, "hostRoomName": room, "status": status,
                "hostType": host_type, "specification": base}

    nvidia = lambda m: {"gpuBrand": "NVIDIA", "gpuModel": m}
    huawei = {"npuBrand": "Huawei", "npuModel": "Ascend 910B",
              "npuPhysicalCardNum": 8, "npuTotalMemory": "464"}

    store.seed_hosts([
        # ── 江苏 · H20 集群（已预留给演示订单）──────────────────────────
        host("example-h20-01", "示例算力机房", "000000", "192.0.2.11", "198.51.100.11",
             "normal", "physical", cpuNum=96, cpuModel="Xeon 8558", memorySize=2048,
             ssdDiskSize=8640, hardDiskSize=0, bandwidth=100, brand="H3C",
             deviceModel="UniServer R5500 G6", processorFrequency="2.1",
             gpuNum=8, gpuTotalMemory="1128", gpuCudaCoreNum=10240,
             gpuTensorCoreNum=2048, gpuRTCoreNum=5, gpuMemoryBandwidth="900",
             gpuFP16Computing="1184", gpuFP16TensorComputing="1184",
             gpuFP32Computing="352", gpuTF32TensorComputing="592",
             gpuFP64Computing="8", gpuFP64TensorComputing="9", **nvidia("H20")),
        host("example-h20-02", "示例算力机房", "000000", "192.0.2.12", "198.51.100.12",
             "normal", "physical", cpuNum=96, cpuModel="Xeon 8558", memorySize=2048,
             ssdDiskSize=8640, hardDiskSize=0, bandwidth=100, brand="H3C",
             deviceModel="UniServer R5500 G6", processorFrequency="2.1",
             gpuNum=8, gpuTotalMemory="1128", gpuCudaCoreNum=10240,
             gpuTensorCoreNum=2048, gpuRTCoreNum=5, gpuMemoryBandwidth="900",
             gpuFP16Computing="1184", gpuFP16TensorComputing="1184",
             gpuFP32Computing="352", gpuTF32TensorComputing="592",
             gpuFP64Computing="8", gpuFP64TensorComputing="9", **nvidia("H20")),
        # ── 上海 · A100/A800 ─────────────────────────────────────────────
        host("example-a100-01", "示例算力机房", "000000", "192.0.2.21", "198.51.100.21",
             "normal", "physical", cpuNum=128, cpuModel="EPYC 7763", memorySize=1024,
             ssdDiskSize=3840, hardDiskSize=0, bandwidth=200, brand="浪潮",
             deviceModel="NF5688M6", processorFrequency="2.45",
             gpuNum=8, gpuTotalMemory="640", gpuCudaCoreNum=6912,
             gpuTensorCoreNum=432, gpuMemoryBandwidth="2039",
             gpuFP16Computing="78", gpuFP16TensorComputing="312",
             gpuFP32Computing="19.5", gpuTF32TensorComputing="156",
             gpuFP64Computing="9.7", gpuFP64TensorComputing="19.5", **nvidia("A100 80GB")),
        host("example-a800-01", "示例算力机房", "000000", "192.0.2.22", "198.51.100.22",
             "normal", "physical", cpuNum=128, cpuModel="EPYC 7763", memorySize=1024,
             ssdDiskSize=3840, hardDiskSize=0, bandwidth=200, brand="浪潮",
             deviceModel="NF5688M6", processorFrequency="2.45",
             gpuNum=8, gpuTotalMemory="640", gpuCudaCoreNum=6912,
             gpuTensorCoreNum=432, gpuMemoryBandwidth="2039",
             gpuFP16Computing="78", gpuFP16TensorComputing="312",
             gpuFP32Computing="19.5", gpuTF32TensorComputing="156",
             gpuFP64Computing="9.7", gpuFP64TensorComputing="19.5", **nvidia("A800 80GB")),
        # ── 广州 · 4090 / 深圳 · Pro6000 ────────────────────────────────
        host("example-4090-01", "示例算力机房", "000000", "192.0.2.31", "198.51.100.31",
             "normal", "physical", cpuNum=64, cpuModel="Xeon W9-3495X", memorySize=256,
             ssdDiskSize=1920, hardDiskSize=8000, bandwidth=100, brand="超微",
             deviceModel="AS-4125GS-TNRT", processorFrequency="2.9",
             gpuNum=8, gpuTotalMemory="192", gpuCudaCoreNum=16384,
             gpuTensorCoreNum=512, gpuRTCoreNum=128, gpuMemoryBandwidth="1008",
             gpuFP16Computing="165.2", gpuFP16TensorComputing="330.3",
             gpuFP32Computing="82.6", gpuFP64Computing="1.3", **nvidia("RTX 4090")),
        # ── 江苏 · 苏州园区 · 1 卡 4090（标准单卡规格）──────────────────
        host("example-4090-02", "示例算力机房", "000000", "192.0.2.32", "198.51.100.32",
             "normal", "physical", cpuNum=32, cpuModel="Xeon W9-3475X", memorySize=256,
             ssdDiskSize=1920, hardDiskSize=4000, bandwidth=100, brand="超微",
             deviceModel="AS-5014A-TT", processorFrequency="2.6",
             gpuNum=1, gpuTotalMemory="24", gpuCudaCoreNum=16384,
             gpuTensorCoreNum=512, gpuRTCoreNum=128, gpuMemoryBandwidth="1008",
             gpuFP16Computing="165.2", gpuFP16TensorComputing="330.3",
             gpuFP32Computing="82.6", gpuFP64Computing="1.3", **nvidia("RTX 4090")),
        host("example-p6000-01", "示例算力机房", "000000", "192.0.2.41", "198.51.100.41",
             "normal", "physical", cpuNum=96, cpuModel="Xeon 8468", memorySize=512,
             ssdDiskSize=3840, hardDiskSize=0, bandwidth=100, brand="戴尔",
             deviceModel="PowerEdge R760xa", processorFrequency="2.1",
             gpuNum=8, gpuTotalMemory="768", gpuCudaCoreNum=18816,
             gpuTensorCoreNum=588, gpuRTCoreNum=147, gpuMemoryBandwidth="1248",
             gpuFP16Computing="262.4", gpuFP16TensorComputing="524.9",
             gpuFP32Computing="131.2", gpuFP64Computing="2.1", **nvidia("RTX Pro 6000")),
        # ── 内蒙古 · 昇腾 NPU ────────────────────────────────────────────
        host("example-910b-01", "示例算力机房", "000000", "192.0.2.51", "198.51.100.51",
             "normal", "physical", cpuNum=128, cpuModel="Kunpeng 920", memorySize=1024,
             ssdDiskSize=3840, hardDiskSize=0, bandwidth=100, brand="华为",
             deviceModel="Atlas 800 训练服务器", processorFrequency="2.6",
             cpuArch="arm64", **huawei),
        # ── 南京 · L40S（维护中演示）────────────────────────────────────
        host("example-l40s-01", "示例算力机房", "000000", "192.0.2.61", "198.51.100.61",
             "maintenance", "physical", cpuNum=64, cpuModel="Xeon Gold 6430",
             memorySize=512, ssdDiskSize=1920, hardDiskSize=0, bandwidth=100,
             brand="联想", deviceModel="SR680 V3", processorFrequency="2.1",
             gpuNum=4, gpuTotalMemory="192", gpuCudaCoreNum=45312,
             gpuTensorCoreNum=1416, gpuRTCoreNum=354, gpuMemoryBandwidth="864",
             gpuFP16Computing="183.1", gpuFP16TensorComputing="366.2",
             gpuFP32Computing="91.6", **nvidia("L40S")),
        # ── 长沙 · 故障态演示（平台应自动剔除不可售）────────────────────
        host("example-4090-03", "示例算力机房", "000000", "192.0.2.71", "198.51.100.71",
             "abnormal", "physical", cpuNum=64, cpuModel="Xeon W9-3495X",
             memorySize=256, ssdDiskSize=1920, hardDiskSize=0, bandwidth=100,
             brand="超微", deviceModel="AS-4125GS-TNRT", processorFrequency="2.9",
             gpuNum=8, gpuTotalMemory="192", gpuCudaCoreNum=16384,
             gpuTensorCoreNum=512, gpuRTCoreNum=128, gpuMemoryBandwidth="1008",
             gpuFP16Computing="165.2", gpuFP16TensorComputing="330.3",
             gpuFP32Computing="82.6", **nvidia("RTX 4090")),
    ])

    # 预置两笔已开通的客户订单，让监控与业务量"看起来在跑"
    demo_orders = [
        ("OP-DEMO-0001", "USER-DEMO-0001", "2026-01-01 10:00:00",
         ("示例算力机房", "192.0.2.11"),
         [("publicIp", "198.51.100.11"), ("publicSshPort", "2222"),
          ("username", "example-user"), ("password", "<EXAMPLE_PASSWORD>")]),
        ("OP-DEMO-0002", "USER-DEMO-0002", "2026-01-02 14:30:00",
         ("示例算力机房", "192.0.2.21"),
         [("publicIp", "198.51.100.21"), ("publicSshPort", "2222"),
          ("username", "example-user"), ("password", "<EXAMPLE_PASSWORD>")]),
    ]
    for open_id, user_id, start_time, key, cred in demo_orders:
        room, ip = key
        rec = store.hosts.get((room, ip))
        if rec is None:
            continue
        order = {"openId": open_id, "reserveId": "RS-" + open_id[3:],
                 "userId": user_id, "orderStartTime": start_time,
                 "nodeKeys": [(room, ip)], "openCode": "4", "openMsg": "开通中",
                 "credentials": None, "finished_at": None,
                 "paused": False, "cancelled": False, "preCancelAt": None}
        store.opens[open_id] = order
        store.finish_open(open_id, [dict(cred)])
        rec.reserved_by, rec.opened_by = None, open_id
