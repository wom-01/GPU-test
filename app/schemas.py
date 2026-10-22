"""接口出入参数据模型（依据《接口要求》第 11 章接口定义）。

命名遵循规范 10.3：lowerCamelCase；日期格式 yyyy-MM-dd HH:mm:ss（字符串）。
规范中数值/字符串类型混用的字段（如 ssdDiskSize）统一用宽松联合类型接收。
"""
from enum import Enum
from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

NumOrStr = Union[int, float, str]


# ── 通用返回对象（规范 10.4）─────────────────────────────────────────────
def api_ok(message: str = "操作成功", data=None) -> dict:
    return {"code": "0", "message": message, "data": data if data is not None else {}}


def api_fail(code: str, message: str, data=None) -> dict:
    return {"code": code, "message": message, "data": data if data is not None else {}}


# ── 主机规格（collect 请求为过滤条件，上报响应中为完整属性）──────────────
class Specification(BaseModel):
    bandwidth: Optional[NumOrStr] = None          # 带宽 Mbps
    memorySize: Optional[NumOrStr] = None         # 内存 GB
    ssdDiskSize: Optional[NumOrStr] = None        # SSD GB
    hardDiskSize: Optional[NumOrStr] = None       # 硬盘 GB
    cpuNum: Optional[int] = None
    cpuArch: Optional[Literal["x86_64", "arm64"]] = None
    cpuModel: Optional[str] = None
    osName: Optional[str] = None
    osImageSource: Optional[str] = None
    brand: Optional[str] = None
    deviceModel: Optional[str] = None
    processorFrequency: Optional[NumOrStr] = None  # GHz
    hostDescription: Optional[str] = None
    gpuBrand: Optional[str] = None
    gpuModel: Optional[str] = None
    gpuNum: Optional[int] = None
    gpuTotalMemory: Optional[NumOrStr] = None      # GB
    gpuCudaCoreNum: Optional[int] = None
    gpuTensorCoreNum: Optional[int] = None
    gpuRTCoreNum: Optional[int] = None
    gpuMemoryBandwidth: Optional[NumOrStr] = None  # GB/s
    gpuFP16Computing: Optional[NumOrStr] = None    # TFLOPS
    gpuFP16TensorComputing: Optional[NumOrStr] = None
    gpuFP32Computing: Optional[NumOrStr] = None
    gpuTF32TensorComputing: Optional[NumOrStr] = None
    gpuFP64Computing: Optional[NumOrStr] = None
    gpuFP64TensorComputing: Optional[NumOrStr] = None
    npuBrand: Optional[str] = None
    npuModel: Optional[str] = None
    npuPhysicalCardNum: Optional[NumOrStr] = None
    npuTotalMemory: Optional[NumOrStr] = None


class HostRef(BaseModel):
    """主机引用：hostRoomName + hostIp 唯一标识一台主机（规范第 2 章）。"""
    hostIp: str
    hostRoomName: str


class HostReport(BaseModel):
    """collect 接口返回的主机完整属性。"""
    hostName: str
    hostIp: str
    publicIp: Optional[str] = None
    areaCode: str
    hostRoomName: str
    status: Literal["normal", "abnormal", "maintenance", "unknown"]
    hostType: Literal["physical", "virtual"]
    specification: Specification


# ── 11.1.1 认证接口 ─────────────────────────────────────────────────────
class TokenRequest(BaseModel):
    thirdOSid: Optional[str] = None
    username: str
    password: str
    validHours: Optional[float] = Field(default=None, ge=0.5, le=876000,
                                        description="令牌有效期（小时），缺省长期有效")


# ── 11.1.2 算力资源上报 ─────────────────────────────────────────────────
class CollectRequest(BaseModel):
    scaleNum: int = Field(gt=0, description="预期并网上报主机规模数量(台)")
    specification: Specification = Field(description="主机规格（必填，可传空对象）")


# ── 11.1.3 / 11.1.4 预占 / 释放 ─────────────────────────────────────────
class ReserveNotifyRequest(BaseModel):
    reserveId: str
    hosts: list[HostRef]


class ReserveReleaseRequest(BaseModel):
    reserveId: str
    description: Optional[str] = None


# ── 11.1.5 开通 ─────────────────────────────────────────────────────────
class HostOpenRequest(BaseModel):
    openId: str
    reserveId: str
    userId: str = Field(description="算力使用方用户标识（集团编码）")
    orderStartTime: str = Field(description="订单生效时间 yyyy-MM-dd HH:mm:ss")
    hosts: list[HostRef]


# ── 11.1.6 开通结果查询 ─────────────────────────────────────────────────
class OpenQueryRequest(BaseModel):
    openId: str
    description: Optional[str] = None


class OpenHostResult(BaseModel):
    publicIp: str
    publicSshPort: str   # 敏感字段，AES 加密后返回
    username: str        # 敏感字段，AES 加密后返回
    password: str        # 敏感字段，AES 加密后返回
    openCode: Literal["0", "2", "3", "4"]
    openMsg: str


# ── 11.1.7 监控数据采集 ─────────────────────────────────────────────────
class MonitorHostRef(BaseModel):
    hostName: Optional[str] = None
    hostIp: str
    publicIp: Optional[str] = None
    hostType: Optional[Literal["physical", "virtual"]] = None
    areaCode: Optional[str] = None
    hostRoomName: str


class MonitorCollectRequest(BaseModel):
    thirdOSid: Optional[str] = None
    providerName: Optional[str] = None
    hosts: list[MonitorHostRef]


class MonitorHostData(BaseModel):
    hostName: str
    hostIp: str
    publicIp: str
    areaCode: str
    hostRoomName: str
    status: str
    usageCPU: str
    cpuNum: int
    usageMemory: str
    memorySize: float
    usageSSDDisk: Optional[str] = None
    ssdDiskSize: Optional[float] = None
    usagehardDisk: str
    hardDiskSize: float
    gpuNum: Optional[int] = None
    usageGpu: Optional[str] = None
    gpuTotalMemory: Optional[str] = None
    gpuUsedMemory: Optional[str] = None
    npuPhysicalCardNum: Optional[int] = None
    usageNpu: Optional[str] = None
    npuTotalMemory: Optional[str] = None
    npuUsedMemory: Optional[str] = None
    updateTime: str


# ── 11.1.8 订单操作（暂停/恢复/预销户/撤销预销户/销户）──────────────────
class OrderType(str, Enum):
    PAUSE = "104"
    RESUME = "105"
    PRE_CANCEL = "107"
    REVOKE_PRE_CANCEL = "108"
    CANCEL = "109"


class OrderUpdateRequest(BaseModel):
    openId: str
    orderType: OrderType


# ── 11.1.9 / 11.1.10 批量预占 / 批量释放 ────────────────────────────────
class BatchReserveItem(HostRef):
    reserveId: str


class BatchReserveNotifyRequest(BaseModel):
    hosts: list[BatchReserveItem]


class BatchReserveReleaseRequest(BaseModel):
    reserveIds: str = Field(description="多个 reserveId 以英文逗号分隔")
    description: Optional[str] = None
