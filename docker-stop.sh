#!/bin/bash

# 停止Docker服务脚本
echo "🛑 停止 KBXY Monsters Pro 服务..."

docker-compose down

echo "✅ 服务已停止"
echo "💾 数据保存在 ./docker-data 目录中"