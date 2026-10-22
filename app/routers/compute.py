"""业务接口（11.1.2 ~ 11.1.10），方向均为：算力交易运营平台 --> 三方系统。

除认证接口外全部挂 require_auth 依赖；业务规则错误统一返回
HTTP 200 + {"code": 非0, "message": ...}，认证错误为 HTTP 401。
数据源由 store 层适配（dgm 真实数据 / demo 演示数据），路由层无感知。
"""
import threading
from datetime import datetime

from fastapi import APIRouter, Depends

from .. import config
from ..schemas import (BatchReserveNotifyRequest, BatchReserveReleaseRequest,
                       CollectRequest, HostOpenRequest, MonitorCollectRequest,
                       MonitorHostData, OpenQueryRequest, OrderUpdateRequest,
                       ReserveNotifyRequest, ReserveReleaseRequest,
                       api_ok)
from ..security.auth import require_auth
from ..store import BizError, store

router = APIRouter()

def _host_ref(hosts: list) -> list[dict]:
    return [{"hostIp": h.hostIp, "hostRoomName": h.hostRoomName} for h in hosts]


# ── 11.1.2 算力资源上报 ─────────────────────────────────────────────────
@router.post("/api/v1/compute/resource/host/collect",
             tags=["② 资源上报"],
             summary="算力资源上报：拉取三方系统可售主机")
def collect(req: CollectRequest, third_os_id: str = Depends(require_auth)):
    picked = store.pick_hosts(req.specification.model_dump(), req.scaleNum)
    reports = [{k: v for k, v in r.items()
                if not k.startswith("_") and k != "nodeId"}
               for r in picked]
    return api_ok("操作成功", {"hosts": reports})


# ── 11.1.3 预占（同步）──────────────────────────────────────────────────
@router.post("/api/v1/compute/resource/reserve/notify",
             tags=["③ 预占与开通"],
             summary="算力主机预占（同步，防超卖）")
def reserve_notify(req: ReserveNotifyRequest,
                   third_os_id: str = Depends(require_auth)):
    store.reserve(req.reserveId, _host_ref(req.hosts))
    return api_ok("预占成功")


# ── 11.1.4 预占释放 ─────────────────────────────────────────────────────
@router.post("/api/v1/compute/resource/reserve/release",
             tags=["③ 预占与开通"],
             summary="预占释放（幂等，找不到记录也返回成功）")
def reserve_release(req: ReserveReleaseRequest,
                    third_os_id: str = Depends(require_auth)):
    store.release(req.reserveId)
    return api_ok("释放成功")


# ── 11.1.5 开通（异步：受理后立即返回，结果由 11.1.6 轮询）──────────────
@router.post("/api/v1/compute/resource/host/open",
             tags=["③ 预占与开通"],
             summary="算力主机开通（异步：向 DGM 真实下单）")
def host_open(req: HostOpenRequest, third_os_id: str = Depends(require_auth)):
    try:
        datetime.strptime(req.orderStartTime, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise BizError("400", "orderStartTime 格式须为 yyyy-MM-dd HH:mm:ss") from exc

    reserved = store.get_reservation(req.reserveId)
    if not reserved:
        raise BizError("404", f"预占事件不存在或已释放：reserveId[{req.reserveId}]")

    # 规范：校验 reserveId 预占主机与 hosts 列表一致性，不一致报错
    want = set(reserved)   # [(hostRoomName, hostIp), ...]
    got = {(h.hostRoomName, h.hostIp) for h in req.hosts}
    if want != got:
        diff = want ^ got
        raise BizError("400",
                       f"开通主机列表与预占记录不一致（差异：{sorted(diff)}）")

    store.create_open({"openId": req.openId, "reserveId": req.reserveId,
                       "userId": req.userId, "orderStartTime": req.orderStartTime,
                       "nodeKeys": sorted(got)})

    # 异步开通任务：dgm 模式下交付 DGM 登记的真实 SSH 凭证（AES 加密）
    node_keys = sorted(got)
    timer = threading.Timer(
        config.OPEN_DURATION_SECONDS,
        lambda: _finish_open(req.openId, node_keys))
    timer.daemon = True
    timer.start()
    return api_ok("开通请求受理成功")


def _finish_open(open_id: str, node_keys: list[tuple]) -> None:
    """异步开通任务：dgm 模式=向 DGM 下单分配节点；demo 模式=模拟凭证。"""
    try:
        store.provision_open(open_id, node_keys)
    except LookupError as exc:
        store.mark_open_failed(open_id, str(exc))
    except Exception as exc:    # noqa: BLE001 — 异步任务兜底，避免静默卡在“开通中”
        store.mark_open_failed(open_id, f"开通任务异常：{exc}")


# ── 11.1.6 开通结果查询 ─────────────────────────────────────────────────
@router.post("/api/v1/compute/resource/host/open/query",
             tags=["③ 预占与开通"],
             summary="开通结果查询（平台每 1 分钟轮询）")
def open_query(req: OpenQueryRequest, third_os_id: str = Depends(require_auth)):
    store.refresh_open(req.openId)   # dgm 模式：从 DGM 同步最新开通状态/凭证
    order = store.get_open(req.openId)
    if not order.get("credentials"):
        return api_ok("操作成功", {"hosts": [{
            "publicIp": "", "publicSshPort": "", "username": "", "password": "",
            "openCode": order["openCode"], "openMsg": order["openMsg"],
        }]})
    return api_ok("操作成功", {"hosts": [dict(c, openCode=order["openCode"],
                                             openMsg=order["openMsg"])
                                       for c in order["credentials"]]})


# ── 11.1.7 监控数据采集 ─────────────────────────────────────────────────
@router.post("/api/v1/compute/resource/host/monitor/collect",
             tags=["④ 监控采集"],
             summary="算力主机监控数据采集")
def monitor_collect(req: MonitorCollectRequest,
                    third_os_id: str = Depends(require_auth)):
    out = []
    for h in req.hosts:
        try:
            rep = store.get_report(h.hostRoomName, h.hostIp)
        except LookupError as exc:
            raise BizError("404", str(exc)) from exc
        data = store.monitor_for(rep)
        out.append(MonitorHostData(**data).model_dump(exclude_none=True))
    return api_ok("操作成功", {"hosts": out})


# ── 11.1.8 暂停/恢复/预销户/撤销预销户/销户 ─────────────────────────────
@router.post("/api/v1/compute/resource/host/order/update",
             tags=["⑤ 订单生命周期"],
             summary="订单操作：暂停104/恢复105/预销户107/撤销108/销户109")
def order_update(req: OrderUpdateRequest, third_os_id: str = Depends(require_auth)):
    msg = store.apply_order_action(req.openId, req.orderType.value)
    return api_ok(msg)


# ── 11.1.9 批量预占 ─────────────────────────────────────────────────────
@router.post("/api/v1/compute/resource/batch/reserve/notify",
             tags=["③ 预占与开通"],
             summary="算力主机批量预占")
def batch_reserve(req: BatchReserveNotifyRequest,
                  third_os_id: str = Depends(require_auth)):
    grouped: dict[str, list[dict]] = {}
    for item in req.hosts:
        grouped.setdefault(item.reserveId, []).append(
            {"hostIp": item.hostIp, "hostRoomName": item.hostRoomName})
    done = []
    try:
        for reserve_id, hosts in grouped.items():
            store.reserve(reserve_id, hosts)
            done.append(reserve_id)
    except BizError:
        for rid in done:            # 回滚已成功的部分
            store.release(rid)
        raise
    return api_ok(f"批量预占成功（{len(done)} 个预占事件）")


# ── 11.1.10 批量预占释放 ────────────────────────────────────────────────
@router.post("/api/v1/compute/resource/batch/reserve/release",
             tags=["③ 预占与开通"],
             summary="批量预占释放（reserveIds 逗号分隔）")
def batch_release(req: BatchReserveReleaseRequest,
                  third_os_id: str = Depends(require_auth)):
    ids = [x.strip() for x in req.reserveIds.split(",") if x.strip()]
    for rid in ids:
        store.release(rid)          # 记录不存在同样视为释放成功
    return api_ok(f"批量释放成功（{len(ids)} 个预占事件）")
