"""业务存储层。

按 config.STORE_BACKEND 选择实现：
  - "dgm"  → DgmStore（docker-gpu-manage 真实台账/监控 + MySQL 持久化预占/开通单）
  - "demo" → ComputeStore（内置演示数据，内存态，无外部依赖）

两者对路由层暴露同一接口：
  pick_hosts / reserve / release / get_reservation /
  create_open / get_open / finish_open / build_credentials / mark_open_failed /
  apply_order_action / get_report / monitor_for
"""
import secrets
import string
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional

from . import config


class BizError(Exception):
    """业务规则错误，路由层转成 code != 0 的响应。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _host_key(host_room: str, host_ip: str) -> tuple:
    return (host_room, host_ip)


def _now() -> str:
    # 固定北京时间（服务器时区为 UTC，直接 now() 会慢 8 小时）
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def gen_password(length: int = 14) -> str:
    """生成满足规范口令策略的主机初始密码（含大小写/数字/特殊符号）。"""
    pools = [string.ascii_lowercase, string.ascii_uppercase,
             string.digits, "!@#$%^&*=-_"]
    chars = [secrets.choice(p) for p in pools]
    chars += [secrets.choice("".join(pools)) for _ in range(length - len(chars))]
    return "".join(chars)


class HostRecord:
    def __init__(self, report: dict):
        self.report = report
        self.reserved_by: Optional[str] = None
        self.opened_by: Optional[str] = None
        self.paused: bool = False
        self.pre_cancel_at: Optional[str] = None

    @property
    def available(self) -> bool:
        return (self.report["status"] == "normal"
                and self.reserved_by is None
                and self.opened_by is None)


class ComputeStore:
    """演示实现：进程内字典。"""

    def __init__(self):
        self._lock = threading.RLock()
        self.hosts: dict[tuple, HostRecord] = {}
        self.reservations: dict[str, list[tuple]] = {}
        self.opens: dict[str, dict] = {}

    # ── 台账 ─────────────────────────────────────────────────────────────
    def seed_hosts(self, reports: list[dict]) -> None:
        with self._lock:
            for r in reports:
                self.hosts[_host_key(r["hostRoomName"], r["hostIp"])] = HostRecord(r)

    def get_report(self, host_room: str, host_ip: str) -> dict:
        rec = self.hosts.get(_host_key(host_room, host_ip))
        if rec is None:
            raise LookupError(f"主机不存在：机房[{host_room}] IP[{host_ip}]")
        return rec.report

    def pick_hosts(self, spec_filter: dict, limit: int) -> list[dict]:
        def match(rec: HostRecord) -> bool:
            for k, want in spec_filter.items():
                if want is None:
                    continue
                got = rec.report["specification"].get(k)
                if got is None or str(got) != str(want):
                    return False
            return True

        with self._lock:
            return [r.report for r in self.hosts.values()
                    if match(r) and r.available][:limit]

    # ── 预占 / 释放 ──────────────────────────────────────────────────────
    def reserve(self, reserve_id: str, hosts: list[dict]) -> None:
        keys = [_host_key(h["hostRoomName"], h["hostIp"]) for h in hosts]
        with self._lock:
            if reserve_id in self.reservations:
                return
            missing, unavailable, recs = [], [], []
            for h, k in zip(hosts, keys):
                rec = self.hosts.get(k)
                if rec is None:
                    missing.append(f"机房[{h['hostRoomName']}] IP[{h['hostIp']}]")
                elif not rec.available:
                    status = rec.report["status"]
                    why = ("状态" + status) if status != "normal" else (
                        "已被预占" if rec.reserved_by else "已开通")
                    unavailable.append(f"IP[{h['hostIp']}]（{why}）")
                else:
                    recs.append(rec)
            if missing:
                raise BizError("404", "主机不存在：" + "；".join(missing))
            if unavailable:
                raise BizError("409", "主机不可预占：" + "；".join(unavailable))
            for rec in recs:
                rec.reserved_by = reserve_id
            self.reservations[reserve_id] = keys

    def release(self, reserve_id: str) -> None:
        with self._lock:
            keys = self.reservations.pop(reserve_id, None)
            if keys is None:
                return
            for k in keys:
                rec = self.hosts.get(k)
                if rec is not None and rec.reserved_by == reserve_id:
                    rec.reserved_by = None

    def get_reservation(self, reserve_id: str) -> list[tuple]:
        with self._lock:
            return self.reservations.get(reserve_id, [])

    # ── 开通 ─────────────────────────────────────────────────────────────
    def create_open(self, order: dict) -> None:
        with self._lock:
            if order["openId"] in self.opens:
                raise BizError("409", f"openId 已存在：{order['openId']}")
            self.opens[order["openId"]] = {
                "openId": order["openId"], "reserveId": order["reserveId"],
                "userId": order["userId"], "orderStartTime": order["orderStartTime"],
                "nodeKeys": order["nodeKeys"], "openCode": "4", "openMsg": "开通中",
                "credentials": None, "finished_at": None,
                "paused": False, "cancelled": False, "preCancelAt": None,
            }

    def get_open(self, open_id: str) -> dict:
        order = self.opens.get(open_id)
        if order is None:
            raise BizError("404", f"开通事件不存在：openId[{open_id}]")
        return order

    def finish_open(self, open_id: str, credentials_cipher: list[dict]) -> None:
        with self._lock:
            order = self.opens[open_id]
            order["openCode"] = "0"
            order["openMsg"] = "开通成功"
            order["finished_at"] = _now()
            order["credentials"] = credentials_cipher
            for k in order["nodeKeys"]:
                rec = self.hosts.get(k)
                if rec is not None:
                    rec.reserved_by = None
                    rec.opened_by = open_id

    def build_credentials(self, node_keys: list[tuple]) -> list[dict]:
        """演示环境：生成模拟 SSH 交付信息（接入真实开机后替换）。"""
        creds = []
        for room, ip in node_keys:
            rep = self.get_report(room, ip)
            creds.append({
                "publicIp": rep["publicIp"] or ip,
                "publicSshPort": str(secrets.randbelow(20000) + 20000),
                "username": "dbcloud",
                "password": gen_password(),
                "_ok": True, "_host": rep["hostName"],
            })
        return creds

    def mark_open_failed(self, open_id: str, msg: str) -> None:
        with self._lock:
            order = self.opens[open_id]
            order["openCode"] = "2"
            order["openMsg"] = msg[:250]
            order["finished_at"] = _now()

    def provision_open(self, open_id: str, node_keys: list[tuple]) -> None:
        """demo：生成模拟凭证并直接完成开通。"""
        from .security.aes import encrypt
        creds = self.build_credentials(node_keys)
        cipher = [{k: (encrypt(v, config.AES_KEY) if k in
                       ("publicSshPort", "username", "password") else v)
                   for k, v in c.items() if not k.startswith("_")} for c in creds]
        self.finish_open(open_id, cipher)

    def refresh_open(self, open_id: str) -> None:
        """demo：开通结果由 provision_open 同步写好，无需刷新。"""

    def sweep_expired(self) -> list[str]:
        """demo：内存态无持久订单，未实现到期扫描。"""
        return []

    # ── 订单操作 ─────────────────────────────────────────────────────────
    def apply_order_action(self, open_id: str, action: str) -> str:
        with self._lock:
            order = self.get_open(open_id)
            if order["cancelled"]:
                raise BizError("409", "订单已销户，无法继续操作")
            if order["openCode"] != "0":
                raise BizError("409", f"订单尚未开通成功（openCode={order['openCode']}）")

            if action == "104":
                order["paused"] = True
                return "暂停成功"
            if action == "105":
                order["paused"] = False
                return "恢复成功"
            if action == "107":
                order["preCancelAt"] = _now()
                return (f"预销户受理成功，{config.PRE_CANCEL_RETENTION_DAYS}"
                        f"天内可撤销，期满未撤销将正式销户")
            if action == "108":
                order["preCancelAt"] = None
                return "撤销预销户成功，订单已恢复"
            if action == "109":
                order["cancelled"] = True
                order["credentials"] = None
                order["paused"] = False
                for k in order["nodeKeys"]:
                    rec = self.hosts.get(k)
                    if rec is not None:
                        rec.opened_by = None
                        rec.paused = False
                        rec.pre_cancel_at = None
                return "销户成功，主机资源已回收"
            raise BizError("400", f"不支持的 orderType：{action}")

    # ── 监控（演示伪随机）────────────────────────────────────────────────
    def monitor_for(self, rep: dict) -> dict:
        import time
        seed = rep["hostIp"]
        minute = int(time.time() // 60)
        def usage(prefix):
            return f"{(abs(hash(f'{prefix}-{seed}-{minute}')) % 55) + 25}%"
        rec = self.hosts.get(_host_key(rep["hostRoomName"], rep["hostIp"]))
        spec = rep["specification"]
        gpu_total = spec.get("gpuTotalMemory")
        return {
            "hostName": rep["hostName"], "hostIp": rep["hostIp"],
            "publicIp": rep["publicIp"] or rep["hostIp"],
            "areaCode": rep["areaCode"], "hostRoomName": rep["hostRoomName"],
            "status": "maintenance" if (rec and rec.paused) else rep["status"],
            "usageCPU": usage("cpu"), "cpuNum": int(spec.get("cpuNum") or 0),
            "usageMemory": usage("mem"), "memorySize": float(spec.get("memorySize") or 0),
            "usagehardDisk": usage("hd"),
            "hardDiskSize": float(spec.get("hardDiskSize") or 0),
            "gpuNum": spec.get("gpuNum"),
            "usageGpu": usage("gpu") if spec.get("gpuNum") else None,
            "gpuTotalMemory": gpu_total,
            "gpuUsedMemory": str(round(float(gpu_total) * 0.1, 1)) if gpu_total else None,
            **({"npuPhysicalCardNum": spec.get("npuPhysicalCardNum"),
                "usageNpu": usage("npu"),
                "npuTotalMemory": spec.get("npuTotalMemory"),
                "npuUsedMemory": str(round(float(spec.get("npuTotalMemory")) * 0.1, 1))}
               if spec.get("npuPhysicalCardNum") else {}),
            "updateTime": _now(),
        }


def build_store():
    """按配置选择数据源；DGM 不可用时回退演示模式并明确告警。"""
    if config.STORE_BACKEND == "dgm":
        try:
            from .dgm_store import DgmStore
            store = DgmStore()
            print(f"[store] 数据源=dgm，真实节点 {len(store.reports)} 台", flush=True)
            return store
        except Exception as exc:    # noqa: BLE001
            print(f"[store] ⚠️ DGM 数据源不可用（{exc}），回退 demo 演示数据", flush=True)
    return ComputeStore()


store = build_store()
