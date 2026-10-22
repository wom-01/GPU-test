#!/bin/bash
# 聚算并网南向接口 启动脚本
cd "$(dirname "$0")"
set -a; [ -f .env ] && . ./.env; set +a
if pgrep -f "^[^ ]*python[^ ]* -m uvicorn app.main:app" > /dev/null; then
    echo "已在运行: $(pgrep -f 'uvicorn app.main:app')"
    exit 0
fi
nohup setsid "$(dirname "$0")/.venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 12359 \
    >> "$(dirname "$0")/server.log" 2>&1 &
sleep 2
curl -s -m 5 http://127.0.0.1:12359/healthz > /dev/null && echo "启动成功 (0.0.0.0:12359)" || echo "启动失败，请查看 server.log"
