"""对接配置项。

实际部署时建议改为环境变量或配置中心下发，不要把密钥写死在代码里。
"""
import os

# 手写 .env 解析：不依赖 python-dotenv（系统 Python 未必装有），已有环境变量优先
_ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.isfile(_ENV_FILE):
    with open(_ENV_FILE, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# ── 第三方系统身份（在算力交易运营平台注册后由平台分配）──────────────────
THIRD_OS_ID = _env("THIRD_OS_ID", "")
PROVIDER_NAME = _env("PROVIDER_NAME", "示例算力 provider")

# ── 认证方式1：用户名/口令 ───────────────────────────────────────────────
# 平台注册三方系统时录入的运维账号，需具备待入网算力资源的管理权限。
# 口令策略（规范第3章）：长度≥8位，含数字/小写/大写/特殊符号至少3类。
AUTH_USERNAME = _env("AUTH_USERNAME", "")
AUTH_PASSWORD = _env("AUTH_PASSWORD", "")

# 签发的访问令牌有效期（秒），规范示例为 1 小时级别
TOKEN_TTL_SECONDS = int(_env("TOKEN_TTL_SECONDS", "7200"))

# ── 认证方式2：密钥对称加密认证 / 敏感字段加密 ───────────────────────────
# 双方约定的 AES 密钥，须为 16/24/32 字节（对应 AES-128/192/256）。
# 同时用于：Authorization 密文解密、开通结果中敏感字段的加解密。
AES_KEY = _env("AES_KEY", "").encode()

# 密文中的时间戳允许偏移（秒），超出视为重放
TIMESTAMP_WINDOW_SECONDS = int(_env("TIMESTAMP_WINDOW_SECONDS", "300"))
# Nonce 防重放缓存容量
NONCE_CACHE_SIZE = int(_env("NONCE_CACHE_SIZE", "100000"))

# ── 认证方式3：国密 SM3（Hmac-SM3）认证 ──────────────────────────────────
MAC_KEY = _env("MAC_KEY", "").encode()

# ── 启用的认证方式（all = 三种同开，按 Authorization 头自动识别）──────────
# 可选: "all" / "token" / "aes" / "mac"
AUTH_MODE = _env("AUTH_MODE", "all")

# ── 开通流程模拟参数 ─────────────────────────────────────────────────────
# 规范：开通为异步，平台每 1 分钟轮询结果，最大等待 30 分钟。
# 此处为演示环境模拟的开通耗时（秒），接入真实开机流程后替换 store.OpenService。
OPEN_DURATION_SECONDS = int(_env("OPEN_DURATION_SECONDS", "3"))

# 预销户冷静期（天），规范要求 15 天内保留用户数据
PRE_CANCEL_RETENTION_DAYS = int(_env("PRE_CANCEL_RETENTION_DAYS", "15"))

# ── 数据源适配 ───────────────────────────────────────────────────────────
# dgm  = 读 docker-gpu-manage 的真实主机台账/监控（推荐）
# demo = 内置演示数据（无外部依赖）
STORE_BACKEND = _env("STORE_BACKEND", "dgm")

# docker-gpu-manage MySQL（只读使用）
DGM_DB = {
    "host": _env("DGM_DB_HOST", "127.0.0.1"),
    "port": int(_env("DGM_DB_PORT", "3306")),
    "user": _env("DGM_DB_USER", "docker_gpu_manage"),
    "password": _env("DGM_DB_PASSWORD", ""),
    "database": _env("DGM_DB_NAME", "docker_gpu_manage"),
}

# 网关状态表（预占/开通单/资源池镜像）所在的库 —— PteroCa 库
GATEWAY_DB = {
    "host": _env("GATEWAY_DB_HOST", "127.0.0.1"),
    "port": int(_env("GATEWAY_DB_PORT", "3306")),
    "user": _env("GATEWAY_DB_USER", "pteroca"),
    "password": _env("GATEWAY_DB_PASSWORD", ""),
    "database": _env("GATEWAY_DB_NAME", "pteroca"),
}

# DGM region → 聚算规范区域编码（附录<常见区域编码列表>常用值）
AREA_CODE_MAP = {
    # 按运营平台《附录1 区域编码信息列表》的自有编码（非国标）
    "苏州园区移动数据中心": "512006",
    "江苏": "320000", "北京": "110000", "山东": "370000",
    "上海": "310000", "广东": "440000", "浙江": "330000", "四川": "510000",
}
AREA_CODE_DEFAULT = _env("AREA_CODE_DEFAULT", "000000")

# DGM 节点同步周期（秒）；0 = 仅启动时同步
DGM_SYNC_INTERVAL = int(_env("DGM_SYNC_INTERVAL", "60"))

# ── DGM 开机对接（integration API）────────────────────────────────────────
# api    = 调 DGM /integration/orders 真实下单分配节点（推荐）
# static = 交付节点登记的既有 SSH 凭证（旧行为，DGM API 不可用时回退）
PROVISION_MODE = _env("PROVISION_MODE", "api")
DGM_API_URL = _env("DGM_API_URL", "http://127.0.0.1:12357")
DGM_INTEGRATION_KEY = _env("DGM_INTEGRATION_KEY", "")

# 订单默认租期（天）：到期自动暂停，超过冷静期后正式销户
DEFAULT_RENTAL_DAYS = int(_env("DEFAULT_RENTAL_DAYS", "30"))
EXPIRY_CHECK_INTERVAL = int(_env("EXPIRY_CHECK_INTERVAL", "600"))


# ── 资源上报测试规格数据 ─────────────────────────────────────────────────
# DGM 台账没有这些属性时，用以下测试值补齐规范 11.1.2 的必填/可选字段。
# 拿到机器真实参数后，直接改这里（或在 DGM 节点上补全）即可，代码无需改动。
HOST_TEST_DEFAULTS = {
    "bandwidth": 1000,                       # Mbps
    "osName": "ubuntu22.04",
    "osImageSource": "Ubuntu官网",
    "ssdDiskSize": "960",                    # GB
}
# 按卡数区分整机测试参数：8 卡机 / 单卡机
HOST_TEST_BY_GPU_COUNT = {
    8: {"cpuModel": "Intel Xeon Platinum 8468", "processorFrequency": "2.1",
        "brand": "Supermicro", "deviceModel": "SYS-421GE-TNRT"},
    1: {"cpuModel": "Intel Xeon Silver 4410Y", "processorFrequency": "2.0",
        "brand": "Supermicro", "deviceModel": "SYS-741GE-TNRT"},
}
# GPU 单卡公开参数（CUDA/Tensor/RT 核心数、显存带宽 GB/s、算力 TFLOPS）
GPU_MODEL_SPECS = {
    "RTX 4090": {"gpuCudaCoreNum": 16384, "gpuTensorCoreNum": 512, "gpuRTCoreNum": 128,
                 "gpuMemoryBandwidth": "1008", "gpuFP16Computing": "82.6",
                 "gpuFP16TensorComputing": "330.3", "gpuFP32Computing": "82.6",
                 "gpuTF32TensorComputing": "82.6", "gpuFP64Computing": "1.29"},
    "RTX 5090": {"gpuCudaCoreNum": 21760, "gpuTensorCoreNum": 680, "gpuRTCoreNum": 170,
                 "gpuMemoryBandwidth": "1792", "gpuFP16Computing": "104.8",
                 "gpuFP16TensorComputing": "419", "gpuFP32Computing": "104.8",
                 "gpuTF32TensorComputing": "104.8", "gpuFP64Computing": "1.64"},
    "L40S": {"gpuCudaCoreNum": 18176, "gpuTensorCoreNum": 568, "gpuRTCoreNum": 142,
             "gpuMemoryBandwidth": "864", "gpuFP16Computing": "91.6",
             "gpuFP16TensorComputing": "362", "gpuFP32Computing": "91.6",
             "gpuTF32TensorComputing": "183", "gpuFP64Computing": "1.43"},
    "H20": {"gpuMemoryBandwidth": "4800", "gpuFP16TensorComputing": "148",
            "gpuFP32Computing": "44", "gpuTF32TensorComputing": "74",
            "gpuFP64Computing": "1", "gpuFP64TensorComputing": "1"},
}
