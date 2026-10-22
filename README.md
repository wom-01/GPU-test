# 界云算力 · 聚算交易服务平台并网对接 API（三方系统侧实现）

依据《聚算交易服务平台-第三方在线并网对接技术规范 v3.0》及《算力并网-第11章-接口要求》实现，
本服务扮演规范中的 **三方系统（算力提供方）** 角色，供算力交易运营平台回调调用。

## 快速启动

```bash
cp .env.example .env
# 编辑 .env，填入通过安全渠道取得的认证与数据库配置
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# 自测（另开终端，模拟平台方完整调用链）
python3 test_client.py http://127.0.0.1:8000
# Swagger 文档
# http://127.0.0.1:8000/docs
```

## 接口清单（方向：运营平台 → 三方系统）

| # | 接口 | 路径 | 同步/异步 |
|---|------|------|-----------|
| 11.1.1 | 用户口令认证（换令牌） | `POST /api/v1/authentication/token` | 同步，无需认证 |
| 11.1.2 | 算力资源上报 | `POST /api/v1/compute/resource/host/collect` | 同步 |
| 11.1.3 | 算力主机预占 | `POST /api/v1/compute/resource/reserve/notify` | 同步 |
| 11.1.4 | 预占释放 | `POST /api/v1/compute/resource/reserve/release` | 同步（幂等） |
| 11.1.5 | 算力主机开通 | `POST /api/v1/compute/resource/host/open` | 异步受理 |
| 11.1.6 | 开通结果查询 | `POST /api/v1/compute/resource/host/open/query` | 同步（平台轮询，1分钟/次，超时30分钟） |
| 11.1.7 | 监控数据采集 | `POST /api/v1/compute/resource/host/monitor/collect` | 同步（平台1分钟/次） |
| 11.1.8 | 暂停/恢复/预销户/撤销预销户/销户 | `POST /api/v1/compute/resource/host/order/update` | 同步 |
| 11.1.9 | 批量预占 | `POST /api/v1/compute/resource/batch/reserve/notify` | 同步 |
| 11.1.10 | 批量预占释放 | `POST /api/v1/compute/resource/batch/reserve/release` | 同步 |

统一返回对象（规范 10.4）：`{"code": "0", "message": "操作成功", "data": {...}}`，
`code` 为字符串，`"0"` 成功、其他为异常（HTTP 状态码遵循规范 10.2）。

## 认证方式（规范第 3 章，三种同开、按 Authorization 头自动识别）

### 方式1：用户名/口令（Bearer 令牌）

```
POST /api/v1/authentication/token
{"username": "<AUTH_USERNAME>", "password": "<AUTH_PASSWORD>"}
→ {"code":"0","data":{"issueAt":"...","expireAt":"...","accessToken":"<JWT-HS256>"}}

Authorization: Bearer <accessToken>
```

### 方式2：密钥对称加密（AES）

明文 `thirdOSid|Timestamp(秒级epoch)|Nonce`，使用 AES-CBC/PKCS7 加密。Authorization 密文
格式为 `IV明文（16字符）+ Base64（密文）`，与客户提供的 `AESCBCUtil.java` 一致。
服务端校验时间窗口（默认 ±300s）+ Nonce 一次性（防重放）。

### 方式3：国密 Hmac-SM3（MAC）

```
Authorization: MAC id="<thirdOSid>",access_token="<会话标识>",nonce="<随机数>",
               mac="<签名>",algorithm="hmac-sm3"

签名串（双方约定，规范未细化处以此为准，可按平台要求调整）：
    METHOD \n PATH \n access_token \n nonce \n sha256_hex(requestBody)
mac = Hmac-SM3(key=MAC_KEY, msg=签名串) 的 hex 小写
```

## 敏感字段加密（规范第 9 章）

开通结果查询（11.1.6）中的 `publicSshPort` / `username` / `password` 以
`IV明文（16字符）+ Base64（AES-CBC密文）` 返回，密钥与方式2相同（`AES_KEY`）。

## 配置

所有配置支持环境变量覆盖（见 `app/config.py`）：
`THIRD_OS_ID` / `AUTH_USERNAME` / `AUTH_PASSWORD` / `AES_KEY`（16/24/32字节）/
`MAC_KEY` / `TOKEN_TTL_SECONDS` / `AUTH_MODE`（all|token|aes|mac）等。

## 业务规则实现对照

- **预占**：同步即时返回；全量成功或全量失败；`hostRoomName+hostIp` 唯一标识主机；已预占/已开通/非 normal 状态拒绝重复预占。
- **预占释放**：记录不存在同样视为成功（规范第 5 章「找不到对应预占资源记录时视为释放成功」）。
- **开通**：校验 `reserveId` 预占主机与 `hosts` 列表一致，不一致报错；受理后异步执行，
  结果经 11.1.6 轮询获取（`openCode`: 0成功/2失败/3尚未开通/4开通中）；开通成功后预占资源转为开通资源。
- **预销户**：15 天冷静期（`PRE_CANCEL_RETENTION_DAYS`）内保留数据、可撤销；期满 109 正式销户后主机初始化回收。
- **监控**：需返回 `updateTime`（空则平台用调用时刻）；usage* 为百分比字符串。
- **批量接口**：多个 `reserveId` 逗号分隔；批量预占失败自动回滚已成功部分。

## 数据源适配（已实现）

`STORE_BACKEND` 环境变量选择数据源，路由/报文/认证层完全无感知：

| 后端 | 台账来源 | 监控来源 | 开通交付 | 状态持久化 |
|---|---|---|---|---|
| `dgm`（默认） | DGM integration API + `compute_node` | DGM 库 `instance` 容器使用率聚合 | **调 DGM `/integration/orders` 真实下单**，分配节点并交付订单 SSH 信息（AES 加密后交付） | PteroCa 库 `jusuan_reservation` / `jusuan_open_order` |
| `demo` | 内置 3 台演示主机 | 伪随机使用率 | 模拟生成凭证 | 进程内存（重启复位） |

- 可售判定：`is_on_shelf=1` 且 `docker_status=connected` 且 SSH 凭证齐全且未被占用（与 DGM 交付口径一致）；开通失败(openCode=2)的节点自动回池
- 真实开通：`host/open` 向 DGM 下租赁订单（`externalId=openId-nodeId` 幂等，我方生成强随机 SSH 密码随单传入）；平台轮询时从 DGM 同步 `active` 状态与交付信息。**DGM 按套餐自动分配节点**（同型号内选择），交付以 DGM 分配结果为准
- 生命周期联动：暂停/恢复/销户(104/105/109)同步调 DGM `suspend/resume/terminate`；预销户(107/108)为本地语义
- 到期管理：订单默认租期 `DEFAULT_RENTAL_DAYS`（30天），到期自动暂停，超过 `PRE_CANCEL_RETENTION_DAYS`（15天）冷静期自动销户；后台任务每 `EXPIRY_CHECK_INTERVAL` 秒扫描
- DGM 对接密钥：systemd 单元中的 `DGM_INTEGRATION_API_KEY`（已同步至 `.env` 的 `DGM_INTEGRATION_KEY`）
- DGM 节点每 60 秒同步一次（`DGM_SYNC_INTERVAL`），并镜像到 PteroCa 库 `host_inventory` 表（含 areaCode/GPU 规格映射，供商城等系统读取；不含 SSH 密码）
- region → 聚算区域编码映射见 `config.AREA_CODE_MAP`
- DGM 节点未登记 SSH 用户名/密码的，开通将返回 `openCode=2` 并说明原因

冒烟测试：
```bash
API_BASE_URL=http://127.0.0.1:12359 python3 test_client.py
API_BASE_URL=http://127.0.0.1:12359 python3 smoke_real.py
```

`test_client.py` 和 `smoke_real.py` 会调用预占、开通及订单生命周期接口。请只对隔离的
演示环境或专用测试节点运行；默认使用本机地址，避免意外操作生产资源。连接生产环境前，
请明确设置 `API_BASE_URL`，并确认测试主机和清理流程。

## PteroCA 商城与客户中心

`PteroCA/` 包含界云算力商城与客户中心（Symfony / PteroCA）源码，包括主题模板、业务代码、数据库迁移、部署配置和本地前端资源。

```bash
cd PteroCA
composer install
cp .env.example .env
# 按部署环境填写 APP_SECRET、DATABASE_URL、邮件及其他服务配置
php bin/console doctrine:migrations:migrate
```

仓库不包含生产 `.env`、Composer `vendor/`、运行缓存/日志、用户上传文件、部署备份和生产数据库。`vendor/` 使用 `composer install` 根据 `composer.lock` 安装。
