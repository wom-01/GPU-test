#!/bin/bash
# 聚算并网接口 · 客户演示实例（STORE_BACKEND=demo，端口 12360，数据与生产隔离）
cd "$(dirname "$0")"
if pgrep -f "uvicorn app.main:app.*12360" > /dev/null; then
    echo "演示实例已在运行"
    exit 0
fi
set -a; [ -f .env ] && . ./.env; set +a
export STORE_BACKEND=demo
nohup setsid python3 -m uvicorn app.main:app --host 0.0.0.0 --port 12360 \
    >> "$(dirname "$0")/demo.log" 2>&1 &
sleep 2
curl -s -m 5 http://127.0.0.1:12360/healthz > /dev/null && echo "演示实例启动成功: http://127.0.0.1:12360/docs" || echo "启动失败，请查看 demo.log"
