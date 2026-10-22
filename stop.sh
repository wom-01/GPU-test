#!/bin/bash
pkill -f "^[^ ]*python[^ ]* -m uvicorn app.main:app" && echo "已停止" || echo "未在运行"
