#!/bin/bash

# 快速启动脚本
echo "🚀 KBXY Monsters Pro 快速启动..."

# 检查是否已存在docker-data目录
if [ ! -d "./docker-data" ]; then
    echo "📁 初始化数据目录..."
    ./scripts/docker/deploy.sh
else
    echo "📁 使用现有数据目录..."
    echo "🔨 重新构建并启动..."
    docker-compose down -v 2>/dev/null || true
    docker-compose up -d --build
    
    echo "⏳ 等待服务启动..."
    sleep 10
    
    echo "✅ 启动完成！"
    echo "📱 前端: http://localhost:8080"
    echo "🔧 后端: http://localhost:8000"
fi