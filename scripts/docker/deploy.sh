#!/bin/bash

# KBXY Monsters Pro Docker 部署脚本
# 用于orbstack或其他Docker环境

set -e

PROJECT_NAME="kbxy-monsters-pro"
DOCKER_DATA_DIR="./docker-data"
SOURCE_DATA_DIR="./data"

echo "🚀 开始部署 $PROJECT_NAME..."

# 检查Docker是否运行
if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker未运行，请启动Docker后重试"
    exit 1
fi

# 停止并清理现有容器
echo "🧹 清理现有容器..."
docker-compose down -v 2>/dev/null || true

# 创建Docker数据目录
echo "📁 准备数据目录..."
mkdir -p "$DOCKER_DATA_DIR/backup"
mkdir -p "$DOCKER_DATA_DIR/images"

# 复制现有数据库和备份（如果存在）
if [ -d "$SOURCE_DATA_DIR" ]; then
    echo "📦 复制现有数据..."
    if [ -f "$SOURCE_DATA_DIR/kbxy-dev.db" ]; then
        cp "$SOURCE_DATA_DIR/kbxy-dev.db" "$DOCKER_DATA_DIR/"
        echo "✅ 数据库文件已复制"
    fi
    
    if [ -d "$SOURCE_DATA_DIR/backup" ]; then
        cp -r "$SOURCE_DATA_DIR/backup"/* "$DOCKER_DATA_DIR/backup/" 2>/dev/null || true
        echo "✅ 备份文件已复制"
    fi
else
    echo "⚠️  未找到源数据目录，将创建空的数据目录"
fi

# 复制图片文件（如果存在）
echo "🖼️  复制图片文件..."
if [ -d "server/images" ]; then
    cp -r server/images/* "$DOCKER_DATA_DIR/images/" 2>/dev/null || true
    image_count=$(find "$DOCKER_DATA_DIR/images" -name "*.png" | wc -l)
    echo "✅ 图片文件已复制 (${image_count} 个文件)"
else
    echo "⚠️  未找到图片目录，将跳过图片复制"
fi

# 设置权限
chmod -R 755 "$DOCKER_DATA_DIR"

echo "📊 数据目录准备完成："
ls -la "$DOCKER_DATA_DIR"

# 构建镜像
echo "🔨 构建Docker镜像..."
docker-compose build --no-cache

# 启动服务
echo "🚀 启动服务..."
docker-compose up -d

# 等待服务启动
echo "⏳ 等待服务启动..."
sleep 10

# 检查服务状态
echo "🔍 检查服务状态..."
docker-compose ps

# 等待健康检查
echo "🏥 等待健康检查..."
timeout=60
while [ $timeout -gt 0 ]; do
    if docker-compose ps | grep -q "healthy"; then
        echo "✅ 所有服务启动成功！"
        break
    fi
    echo "⏳ 等待中... ($timeout秒)"
    sleep 5
    timeout=$((timeout - 5))
done

if [ $timeout -le 0 ]; then
    echo "⚠️  健康检查超时，请检查服务状态"
    docker-compose logs
    exit 1
fi

echo ""
echo "🎉 部署完成！"
echo "📱 前端访问地址: http://localhost:8080"
echo "🔧 后端API地址: http://localhost:8000"
echo ""
echo "📝 常用命令："
echo "  查看日志: docker-compose logs -f"
echo "  停止服务: docker-compose down"
echo "  重启服务: docker-compose restart"
echo "  查看状态: docker-compose ps"
echo ""
echo "💾 数据目录: $DOCKER_DATA_DIR"
echo "🔄 备份位置: $DOCKER_DATA_DIR/backup"