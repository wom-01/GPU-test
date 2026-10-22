"""docker-gpu-manage (DGM) 真实数据源适配层。

数据归属：
  - 主机台账 / SSH 凭证 / 节点状态：DGM 库 compute_node（只读，绝不在本服务改写）
  - 监控数据：DGM 库 instance 聚合（容器级 CPU/内存/GPU 显存使用率）
  - 预占 / 开通单：网关库（pteroca）jusuan_reservation / jusuan_open_order 表
  - 资源池镜像：网关库 host_inventory 表（供 PteroCa 商城等系统读取）

可用性语义：
  可售 = is_on_shelf=1 且 docker_status='connected' 且未被有效预占/开通占用
"""
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import pymysql

from . import config
from .security.aes import encrypt
from .store import BizError, gen_password


def _bj_dt():
    # 北京时间的 naive datetime（服务器时区为 UTC，直接 now() 会慢 8 小时）
    return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


def _now():
    return _bj_dt().strftime("%Y-%m-%d %H:%M:%S")


def _connect(db_conf: dict) -> pymysql.connections.Connection:
    return pymysql.connect(host=db_conf["host"], port=db_conf["port"],
                           user=db_conf["user"], password=db_conf["password"],
                           database=db_conf["database"], charset="utf8mb4",
                           autocommit=True, cursorclass=pymysql.cursors.DictCursor)


def _gpu_spec(name: str, gpu_name: str, gpu_count, gpu_mem):
    """DGM 字段 → 聚算规格。gpu_name 缺失时从节点名推断（节点命名即机型）。"""
    model = (gpu_name or "").strip()
    if model in ("4090",):
        model = "RTX 4090"
    elif model in ("5090",):
        model = "RTX 5090"
    elif model in ("l40s", "L40S"):
        model = "L40S"
    elif model in ("h20",):
        model = "H20"
    elif model in ("a100", "A100"):
        model = "A100 80GB" if "80" in (name or "") else "A100"
    brand = "NVIDIA" if model else None
    if not model:
        low = (name or "").lower()
        if "5090" in low:
            model = "RTX 5090"
        elif "4090" in low:
            model = "RTX 4090"
        elif "a100" in low:
            model = "A100 80GB" if "80" in low else "A100"
        elif "l40s" in low:
            model = "L40S"
        elif "pro6000" in low or "6000" in low:
            model = "RTX Pro 6000"
        elif "h20" in low:
            model = "H20"
        brand = "NVIDIA" if model else None
    try:
        count = int(gpu_count) if gpu_count else None
    except (TypeError, ValueError):
        count = None
    total_mem = str(gpu_mem) if gpu_mem else None
    return brand, (model or None), count, total_mem


def _row_to_report(row: dict) -> dict:
    """compute_node 行 → 规范 collect 响应中的主机完整属性。"""
    brand, model, count, total_mem = _gpu_spec(
        row.get("name") or "", row.get("gpu_name"), row.get("gpu_count"),
        row.get("memory_capacity"))
    status_map = {"connected": "normal", "disconnected": "abnormal",
                  "not_configured": "maintenance"}
    room = (row.get("region") or "默认区域").strip()
    cpu = int(row["cpu"] or 0)
    mem = int(row["memory"] or 0)
    disk = int(row["data_disk"] or 0)
    by_count = config.HOST_TEST_BY_GPU_COUNT.get(
        count if count in config.HOST_TEST_BY_GPU_COUNT else 8, {})
    gpu_extra = config.GPU_MODEL_SPECS.get(model or "", {})
    return {
        "nodeId": row["id"],
        "hostName": row.get("name") or f"node-{row['id']}",
        "hostIp": row.get("private_ip") or row.get("public_ip") or f"unassigned-{row['id']}",
        "publicIp": row.get("public_ip") or None,
        "areaCode": config.AREA_CODE_MAP.get(room, config.AREA_CODE_DEFAULT),
        "hostRoomName": room,
        "status": status_map.get((row.get("docker_status") or "").lower(), "unknown"),
        "hostType": "physical",
        # 交付凭证来源（不进入对外报文）
        "_sshPort": int(row["ssh_port"] or 22),
        "_sshUsername": row.get("username") or "",
        "_sshPassword": row.get("password") or "",
        "_onShelf": bool(row.get("is_on_shelf")),
        "specification": {
            "cpuNum": cpu, "cpuArch": "x86_64",
            "cpuModel": by_count.get("cpuModel"),
            "osName": config.HOST_TEST_DEFAULTS["osName"],
            "osImageSource": config.HOST_TEST_DEFAULTS["osImageSource"],
            "brand": by_count.get("brand"),
            "deviceModel": by_count.get("deviceModel") or row.get("name"),
            "memorySize": float(mem),
            "ssdDiskSize": config.HOST_TEST_DEFAULTS["ssdDiskSize"],
            "hardDiskSize": str(disk),
            "bandwidth": config.HOST_TEST_DEFAULTS["bandwidth"],
            "processorFrequency": by_count.get("processorFrequency"),
            "hostDescription": f"{model or row.get('name')} ×{count or 0} GPU 算力服务器（测试数据）",
            "gpuBrand": brand, "gpuModel": model, "gpuNum": count,
            "gpuTotalMemory": total_mem,
            **gpu_extra,
        },
    }


class DgmStore:
    """与 store.ComputeStore 同接口的真实数据实现。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._dgm = config.DGM_DB
        self._gw = config.GATEWAY_DB
        self.reports: dict[str, dict] = {}      # (room, ip) -> report
        self._spec_map: dict | None = None       # specId -> 型号串缓存
        self.refresh()                           # 启动即拉一次台账

    # ── DGM / 网关库连接 ─────────────────────────────────────────────────
    def _q_dgm(self, sql, args=None, one=False):
        with _connect(self._dgm) as conn, conn.cursor() as cur:
            cur.execute(sql, args or ())
            rows = cur.fetchall()
            return (rows[0] if rows else None) if one else rows

    def _q_gw(self, sql, args=None, one=False, write=False):
        conn = _connect(self._gw)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, args or ())
                if write:
                    conn.commit()
                    return cur.rowcount
                rows = cur.fetchall()
                return (rows[0] if rows else None) if one else rows
        finally:
            conn.close()

    # ── DGM integration API ───────────────────────────────────────────────
    def _api(self, method: str, path: str, payload: dict | None = None) -> dict:
        """调 DGM 对接 API；非 2xx/业务失败抛 RuntimeError。"""
        if not config.DGM_INTEGRATION_KEY:
            raise RuntimeError("未配置 DGM_INTEGRATION_KEY")
        req = urllib.request.Request(
            config.DGM_API_URL + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={"X-Integration-Key": config.DGM_INTEGRATION_KEY,
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"DGM API 不可达：{exc}") from exc
        if body.get("code") not in (0, "0"):
            raise RuntimeError(f"DGM API 业务失败：{body.get('msg')}")
        return body.get("data") or {}

    def _match_spec(self, rep: dict) -> int:
        """节点 → DGM 售卖套餐 specId（按 GPU 型号/节点名归一化匹配）。"""
        if self._spec_map is None:
            products = self._api("GET", "/integration/products")
            self._spec_map = {}
            for p in products:
                spec_id = p.get("ID", p.get("id"))
                if spec_id is None:
                    continue
                key = ((p.get("gpuModel") or "") + " " + (p.get("name") or "")).lower()
                self._spec_map[spec_id] = key
        model = ((rep["specification"].get("gpuModel") or "") + " "
                 + (rep["hostName"] or "")).lower()

        def norm(s):
            return (s.replace(" ", "").replace("rtx", "").replace("80gb", "80")
                     .replace("-", "") or "")
        want = norm(model)
        for spec_id, key in self._spec_map.items():
            if want and (norm(key) in want or want in norm(key)):
                return spec_id
        raise RuntimeError(
            f"节点[{rep['hostName']}] 没有匹配的 DGM 售卖套餐，请先在 DGM 配置 product_spec")

    # ── 台账同步（DGM → 内存 + host_inventory 镜像）─────────────────────
    def refresh(self):
        rows = self._q_dgm(
            "SELECT * FROM compute_node WHERE deleted_at IS NULL")
        reports = {}
        for r in rows:
            rep = _row_to_report(r)
            reports[(rep["hostRoomName"], rep["hostIp"])] = rep
        with self._lock:
            self.reports = reports
        self._mirror_inventory(reports)

    def _mirror_inventory(self, reports: dict):
        """把台账镜像进网关库 host_inventory（不含 SSH 密码）。"""
        for rep in reports.values():
            spec = rep["specification"]
            self._q_gw(
                """INSERT INTO host_inventory
                   (node_id,name,region,host_room,host_ip,public_ip,area_code,
                    gpu_brand,gpu_model,gpu_num,gpu_total_memory_gb,
                    cpu_num,memory_size_gb,data_disk_gb,docker_status,is_on_shelf,sellable)
                   VALUES (%(nodeId)s,%(hostName)s,%(room)s,%(room)s,%(hostIp)s,
                           %(publicIp)s,%(areaCode)s,%(gpuBrand)s,%(gpuModel)s,%(gpuNum)s,
                           %(gpuTotalMemory)s,%(cpuNum)s,%(memorySize)s,%(hardDiskSize)s,
                           %(status)s,1,%(sellable)s)
                   ON DUPLICATE KEY UPDATE name=VALUES(name),region=VALUES(region),
                   host_room=VALUES(host_room),host_ip=VALUES(host_ip),
                   public_ip=VALUES(public_ip),area_code=VALUES(area_code),
                   gpu_brand=VALUES(gpu_brand),gpu_model=VALUES(gpu_model),
                   gpu_num=VALUES(gpu_num),gpu_total_memory_gb=VALUES(gpu_total_memory_gb),
                   cpu_num=VALUES(cpu_num),memory_size_gb=VALUES(memory_size_gb),
                   data_disk_gb=VALUES(data_disk_gb),docker_status=VALUES(docker_status),
                   is_on_shelf=1,sellable=VALUES(sellable)""",
                {"nodeId": rep["nodeId"], "hostName": rep["hostName"],
                 "room": rep["hostRoomName"], "hostIp": rep["hostIp"],
                 "publicIp": rep["publicIp"], "areaCode": rep["areaCode"],
                 "gpuBrand": spec["gpuBrand"], "gpuModel": spec["gpuModel"],
                 "gpuNum": spec["gpuNum"], "gpuTotalMemory": spec["gpuTotalMemory"],
                 "cpuNum": spec["cpuNum"], "memorySize": spec["memorySize"],
                 "hardDiskSize": spec["hardDiskSize"], "status": rep["status"],
                 "sellable": 1 if self._is_sellable(rep) else 0}, write=True)

    # ── 通用查询 ─────────────────────────────────────────────────────────
    def _is_sellable(self, rep: dict) -> bool:
        """与 DGM 交付口径一致：已连接/上架/凭证齐全 且未被占用。"""
        return (rep["status"] == "normal" and rep.get("_onShelf", True)
                and bool(rep["_sshUsername"]) and bool(rep["_sshPassword"])
                and not self._occupied(rep["nodeId"]))

    def _occupied(self, node_id) -> bool:
        """节点是否被有效预占/开通占用（网关库状态表判断）。"""
        res = self._q_gw(
            "SELECT 1 FROM jusuan_reservation WHERE released_at IS NULL "
            "AND JSON_CONTAINS(node_ids, %s) LIMIT 1",
            (json.dumps(node_id),), one=True)
        if res:
            return True
        op = self._q_gw(
            "SELECT 1 FROM jusuan_open_order WHERE cancelled=0 "
            "AND open_code IN ('0','4') "
            "AND JSON_CONTAINS(node_ids, %s) LIMIT 1",
            (json.dumps(node_id),), one=True)
        return op is not None

    def get_report(self, host_room: str, host_ip: str) -> dict:
        rep = self.reports.get((host_room, host_ip))
        if rep is None:
            raise LookupError(f"主机不存在：机房[{host_room}] IP[{host_ip}]")
        return rep

    def pick_hosts(self, spec_filter: dict, limit: int) -> list[dict]:
        def match(rep: dict) -> bool:
            for k, want in spec_filter.items():
                if want is None:
                    continue
                got = rep["specification"].get(k)
                if got is None or got == "":
                    continue    # 主机未上报的属性不参与筛选
                try:            # 数值字段按数值比较（256 与 256.0、"192" 与 192 视为相等）
                    if float(got) != float(want):
                        return False
                except (TypeError, ValueError):
                    if str(got).strip().lower() != str(want).strip().lower():
                        return False
            return self._is_sellable(rep)

        with self._lock:
            pool = list(self.reports.values())
        return [r for r in pool if match(r)][:limit]

    # ── 预占 / 释放 ──────────────────────────────────────────────────────
    def reserve(self, reserve_id: str, hosts: list[dict]) -> None:
        with self._lock:
            row = self._q_gw("SELECT released_at FROM jusuan_reservation "
                             "WHERE reserve_id=%s", (reserve_id,), one=True)
            if row and row["released_at"] is None:
                return    # 幂等：同一预占事件仍有效
            if row:
                # 已释放的 reserveId 再次预占：按新预占重新校验主机，不能直接返回成功
                self._q_gw("DELETE FROM jusuan_reservation WHERE reserve_id=%s",
                           (reserve_id,), write=True)
            keys = [(h["hostRoomName"], h["hostIp"]) for h in hosts]
            missing, unavailable, node_ids = [], [], []
            for h, k in zip(hosts, keys):
                rep = self.reports.get(k)
                if rep is None:
                    missing.append(f"机房[{h['hostRoomName']}] IP[{h['hostIp']}]")
                elif not rep.get("_onShelf", True):
                    unavailable.append(f"IP[{h['hostIp']}]（已下架）")
                elif not self._is_sellable(rep):
                    why = {"abnormal": "状态异常", "maintenance": "维护中"}.get(
                        rep["status"], "已被占用") if rep["status"] != "normal" else "已被占用"
                    unavailable.append(f"IP[{h['hostIp']}]（{why}）")
                else:
                    node_ids.append(rep["nodeId"])
            if missing:
                raise BizError("404", "主机不存在：" + "；".join(missing))
            if unavailable:
                raise BizError("409", "主机不可预占：" + "；".join(unavailable))
            self._q_gw(
                "INSERT INTO jusuan_reservation (reserve_id,node_ids) VALUES (%s,%s)",
                (reserve_id, json.dumps(node_ids)), write=True)

    def release(self, reserve_id: str) -> None:
        self._q_gw("UPDATE jusuan_reservation SET released_at=%s "
                   "WHERE reserve_id=%s AND released_at IS NULL",
                   (_now(), reserve_id), write=True)

    def get_reservation(self, reserve_id: str) -> list[tuple]:
        row = self._q_gw("SELECT node_ids FROM jusuan_reservation "
                         "WHERE reserve_id=%s AND released_at IS NULL",
                         (reserve_id,), one=True)
        if not row:
            return []
        ids = json.loads(row["node_ids"])
        out = []
        for k, rep in self.reports.items():
            if rep["nodeId"] in ids:
                out.append(k)
        return out

    # ── 开通 ─────────────────────────────────────────────────────────────
    def create_open(self, order: dict) -> None:
        if self._q_gw("SELECT 1 FROM jusuan_open_order WHERE open_id=%s",
                      (order["openId"],), one=True):
            raise BizError("409", f"openId 已存在：{order['openId']}")
        node_ids = [self.get_report(room, ip)["nodeId"]
                    for room, ip in order["nodeKeys"]]
        expires = (_bj_dt() + timedelta(days=config.DEFAULT_RENTAL_DAYS)
                   ).strftime("%Y-%m-%d %H:%M:%S")
        self._q_gw(
            """INSERT INTO jusuan_open_order
               (open_id,reserve_id,user_id,order_start_time,node_ids,open_code,
                open_msg,expires_at)
               VALUES (%s,%s,%s,%s,%s,'4','开通中',%s)""",
            (order["openId"], order["reserveId"], order["userId"],
             order["orderStartTime"], json.dumps(node_ids), expires), write=True)

    def get_open(self, open_id: str) -> dict:
        row = self._q_gw("SELECT * FROM jusuan_open_order WHERE open_id=%s",
                         (open_id,), one=True)
        if row is None:
            raise BizError("404", f"开通事件不存在：openId[{open_id}]")
        return {   # 与 demo 实现保持同一 camelCase 结构
            "openId": row["open_id"], "reserveId": row["reserve_id"],
            "userId": row["user_id"], "orderStartTime": row["order_start_time"],
            "nodeIds": json.loads(row["node_ids"]),
            "openCode": row["open_code"], "openMsg": row["open_msg"],
            "credentials": json.loads(row["credentials"]) if row["credentials"] else None,
            "paused": bool(row["paused"]), "cancelled": bool(row["cancelled"]),
            "preCancelAt": row["pre_cancel_at"],
            "expiresAt": row["expires_at"].strftime("%Y-%m-%d %H:%M:%S") if row.get("expires_at") else None,
            "dgmOrderIds": json.loads(row["dgm_order_ids"]) if row.get("dgm_order_ids") else [],
        }

    def finish_open(self, open_id: str, credentials_cipher: list[dict]) -> None:
        self._q_gw(
            "UPDATE jusuan_open_order SET open_code='0', open_msg='开通成功', "
            "credentials=%s, finished_at=%s WHERE open_id=%s",
            (json.dumps(credentials_cipher, ensure_ascii=False), _now(), open_id),
            write=True)

    def provision_open(self, open_id: str, node_keys: list[tuple]) -> None:
        """真实开通：向 DGM 按预占节点逐台下租赁订单（externalId=openId-nodeId 幂等）。

        DGM 按套餐分配已连接节点并返回整机 SSH 交付信息；全部下单成功即视为
        受理完成，交付凭证由 refresh_open() 在平台轮询时从 DGM 同步并加密落库。
        """
        if config.PROVISION_MODE != "api":
            return self._provision_static(open_id, node_keys)

        order = self.get_open(open_id)
        placed, failures = [], []
        for room, ip in node_keys:
            rep = self.get_report(room, ip)
            try:
                spec_id = self._match_spec(rep)
                data = self._api("POST", "/integration/orders", {
                    "externalId": f"{open_id}-{rep['nodeId']}",
                    "specId": spec_id,
                    "customerName": (order.get("userId") or "jusuan")[:90],
                    "phone": "10000000000",
                    "rentalHours": min(config.DEFAULT_RENTAL_DAYS * 24, 8760),
                    "operatingSystem": "ubuntu22.04",
                    "sshPassword": gen_password(),
                    "remark": f"聚算并网 openId={open_id} 预占={room}/{ip}",
                    "nodeId": rep["nodeId"],      # DGM 按预占的节点交付，不再按套餐任意分配
                })
                placed.append({"nodeId": rep["nodeId"], "dgmOrderId": data["ID"]})
            except (RuntimeError, LookupError) as exc:
                failures.append(f"{rep['hostName']}: {exc}")

        if failures:
            for p in placed:      # 回滚已下单的，避免半开通
                try:
                    self._api("POST", "/integration/orders/action",
                              {"id": p["dgmOrderId"], "action": "terminate"})
                except RuntimeError:
                    pass
            self.mark_open_failed(open_id, "；".join(failures)[:250])
            return
        self._q_gw("UPDATE jusuan_open_order SET dgm_order_ids=%s WHERE open_id=%s",
                   (json.dumps([p["dgmOrderId"] for p in placed]), open_id), write=True)

    def _provision_static(self, open_id: str, node_keys: list[tuple]) -> None:
        """回退模式：交付节点登记的既有 SSH 凭证（不走 DGM 下单）。"""
        creds = []
        for room, ip in node_keys:
            rep = self.get_report(room, ip)
            ok = bool(rep["_sshUsername"] and rep["_sshPassword"])
            creds.append({
                "publicIp": rep["publicIp"] or ip,
                "publicSshPort": str(rep["_sshPort"]),
                "username": rep["_sshUsername"],
                "password": rep["_sshPassword"],
                "_ok": ok, "_host": rep["hostName"],
            })
        missing = [c["_host"] for c in creds if not c["_ok"]]
        if missing:
            self.mark_open_failed(
                open_id, f"节点未配置SSH交付凭证，无法开通：{'、'.join(missing)}")
            return
        cipher = [{k: (encrypt(v, config.AES_KEY) if k in
                       ("publicSshPort", "username", "password") else v)
                   for k, v in c.items() if not k.startswith("_")} for c in creds]
        self.finish_open(open_id, cipher)

    _SENSITIVE = ("publicSshPort", "username", "password")

    def refresh_open(self, open_id: str) -> None:
        """平台轮询时从 DGM 同步开通状态并生成交付凭证（AES 密文落库）。"""
        if config.PROVISION_MODE != "api":
            return
        order = self.get_open(open_id)
        if order["openCode"] not in ("4",) or not order.get("dgmOrderIds") and not order.get("nodeIds"):
            return
        dgm_ids = order.get("dgmOrderIds") or []
        if not dgm_ids:
            return
        hosts, states = [], []
        for dgm_id in dgm_ids:
            dgm = self._api("GET", f"/integration/orders/{dgm_id}")
            states.append(dgm.get("status") or "pending")
            if dgm.get("status") == "active" and dgm.get("accessIp"):
                hosts.append({
                    "publicIp": str(dgm["accessIp"]),
                    "publicSshPort": str(dgm.get("sshPort") or 22),
                    "username": str(dgm.get("sshUsername") or "root"),
                    "password": str(dgm.get("sshPassword") or ""),
                })
        if states and all(s == "active" for s in states):
            cipher = [{k: (encrypt(v, config.AES_KEY) if k in self._SENSITIVE else v)
                       for k, v in h.items()} for h in hosts]
            self.finish_open(open_id, cipher)
        elif states and any(s in ("terminated", "completed", "cancelled") for s in states):
            errs = [dgm.get("provisionErr") or s for s in states]
            self.mark_open_failed(open_id, "；".join(errs)[:250])
        # 其余（pending/provisioning/suspended）保持开通中

    def mark_open_failed(self, open_id: str, msg: str) -> None:
        self._q_gw("UPDATE jusuan_open_order SET open_code='2', open_msg=%s, "
                   "finished_at=%s WHERE open_id=%s", (msg[:250], _now(), open_id),
                   write=True)

    # ── 订单操作 ─────────────────────────────────────────────────────────
    def _dgm_order_action(self, order: dict, dgm_action: str) -> None:
        """联动 DGM 订单动作（尽力而为：DGM 不可达不影响本地状态）。"""
        for dgm_id in order.get("dgmOrderIds") or []:
            try:
                self._api("POST", "/integration/orders/action",
                          {"id": dgm_id, "action": dgm_action})
            except RuntimeError as exc:
                print(f"[dgm] 订单 {dgm_id} {dgm_action} 联动失败：{exc}", flush=True)

    def apply_order_action(self, open_id: str, action: str) -> str:
        order = self.get_open(open_id)
        if order["cancelled"]:
            raise BizError("409", "订单已销户，无法继续操作")
        if order["openCode"] != "0":
            raise BizError("409", f"订单尚未开通成功（openCode={order['openCode']}）")

        if action == "104":
            self._q_gw("UPDATE jusuan_open_order SET paused=1 WHERE open_id=%s",
                       (open_id,), write=True)
            self._dgm_order_action(order, "suspend")
            return "暂停成功"
        if action == "105":
            self._q_gw("UPDATE jusuan_open_order SET paused=0 WHERE open_id=%s",
                       (open_id,), write=True)
            self._dgm_order_action(order, "resume")
            return "恢复成功"
        if action == "107":
            self._q_gw("UPDATE jusuan_open_order SET pre_cancel_at=%s WHERE open_id=%s",
                       (_now(), open_id), write=True)
            return (f"预销户受理成功，{config.PRE_CANCEL_RETENTION_DAYS}"
                    f"天内可撤销，期满未撤销将正式销户")
        if action == "108":
            self._q_gw("UPDATE jusuan_open_order SET pre_cancel_at=NULL WHERE open_id=%s",
                       (open_id,), write=True)
            return "撤销预销户成功，订单已恢复"
        if action == "109":
            self._q_gw("UPDATE jusuan_open_order SET cancelled=1, credentials=NULL, "
                       "paused=0 WHERE open_id=%s", (open_id,), write=True)
            self._dgm_order_action(order, "terminate")
            # 销户时自动释放关联预占，避免主机残留"已被占用"
            row = self._q_gw("SELECT node_ids FROM jusuan_open_order WHERE open_id=%s",
                             (open_id,), one=True)
            for nid in json.loads((row or {}).get("node_ids") or "[]"):
                self._q_gw(
                    "UPDATE jusuan_reservation SET released_at=%s "
                    "WHERE released_at IS NULL AND JSON_CONTAINS(node_ids, %s)",
                    (_now(), json.dumps(nid)), write=True)
            return "销户成功，主机资源已回收"
        raise BizError("400", f"不支持的 orderType：{action}")

    # ── 到期管理 ─────────────────────────────────────────────────────────
    def sweep_expired(self) -> list[str]:
        """到期未暂停的订单自动 suspend；到期超过冷静期自动 terminate+销户。"""
        actions = []
        rows = self._q_gw(
            "SELECT open_id, expires_at, paused FROM jusuan_open_order "
            "WHERE cancelled=0 AND open_code='0' AND expires_at IS NOT NULL")
        if not rows:
            return actions
        grace = (_bj_dt()
                 - timedelta(days=config.PRE_CANCEL_RETENTION_DAYS)).strftime(
                     "%Y-%m-%d %H:%M:%S")
        for row in rows:
            open_id = row["open_id"]
            expires = (row["expires_at"].strftime("%Y-%m-%d %H:%M:%S")
                       if hasattr(row["expires_at"], "strftime")
                       else str(row["expires_at"]))
            try:
                if expires <= grace:
                    self.apply_order_action(open_id, "109")
                    actions.append(f"{open_id} 到期超{config.PRE_CANCEL_RETENTION_DAYS}天 → 正式销户")
                elif expires <= _now() and not row["paused"]:
                    self.apply_order_action(open_id, "104")
                    actions.append(f"{open_id} 到期 → 自动暂停（冷静期后销户）")
            except BizError as exc:
                actions.append(f"{open_id} 处理失败：{exc.message}")
        return actions

    # ── 监控（DGM instance 容器聚合）────────────────────────────────────
    def monitor_for(self, rep: dict) -> dict:
        paused = bool(self._q_gw(
            "SELECT 1 FROM jusuan_open_order WHERE cancelled=0 AND paused=1 "
            "AND JSON_CONTAINS(node_ids, %s) LIMIT 1",
            (json.dumps(rep["nodeId"]),), one=True))
        agg = self._q_dgm(
            """SELECT COUNT(*) cnt,
                      AVG(cpu_usage_percent) cpu, AVG(memory_usage_percent) mem,
                      AVG(gpu_memory_usage_rate) gpu
               FROM instance WHERE node_id=%s AND deleted_at IS NULL""",
            (rep["nodeId"],), one=True)
        def pct(v, zero="0%"):
            return f"{round(float(v))}%" if v is not None else zero
        status = "maintenance" if paused else rep["status"]
        spec = rep["specification"]
        gpu_total = spec.get("gpuTotalMemory")
        gpu_used = None
        if gpu_total and agg and agg["gpu"] is not None:
            try:
                gpu_used = str(round(float(gpu_total) * float(agg["gpu"]) / 100, 1))
            except (TypeError, ValueError):
                gpu_used = None
        return {
            "hostName": rep["hostName"], "hostIp": rep["hostIp"],
            "publicIp": rep["publicIp"] or rep["hostIp"],
            "areaCode": rep["areaCode"], "hostRoomName": rep["hostRoomName"],
            "status": status,
            "usageCPU": pct(agg["cpu"]) if agg else "0%",
            "cpuNum": spec.get("cpuNum") or 0,
            "usageMemory": pct(agg["mem"]) if agg else "0%",
            "memorySize": float(spec.get("memorySize") or 0),
            "usagehardDisk": "0%",
            "hardDiskSize": float(spec.get("hardDiskSize") or 0),
            "gpuNum": spec.get("gpuNum"),
            "usageGpu": pct(agg["gpu"]) if (agg and agg["gpu"] is not None) else "0%",
            "gpuTotalMemory": gpu_total,
            "gpuUsedMemory": gpu_used if gpu_used else "0",
            "updateTime": _now(),
        }
