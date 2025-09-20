#!/bin/bash

# 数据初始化脚本 - 用于Docker容器启动时初始化数据
# 将现有的数据库和备份文件复制到Docker volume中

set -e

DATA_DIR="/app/data"

echo "🚀 开始初始化数据..."

# 创建数据目录结构
mkdir -p "$DATA_DIR/backup"

# 检查是否已有数据库文件
if [ ! -f "$DATA_DIR/kbxy-dev.db" ]; then
    echo "📦 未找到现有数据库，正在导入初始数据..."
    
    # 检查是否有挂载的初始数据
    if [ -d "/app/docker-data" ]; then
        echo "🔗 发现挂载的数据目录，复制初始数据..."
        if [ -f "/app/docker-data/kbxy-dev.db" ]; then
            cp "/app/docker-data/kbxy-dev.db" "$DATA_DIR/"
            echo "✅ 数据库文件已复制"
        fi
        
        if [ -d "/app/docker-data/backup" ]; then
            cp -r "/app/docker-data/backup"/* "$DATA_DIR/backup/" 2>/dev/null || true
            echo "✅ 备份文件已复制"
        fi
    else
        echo "⚠️  未找到初始数据，将创建空数据库"
    fi
    
    # 设置权限
    chown -R 1000:1000 "$DATA_DIR"
    chmod -R 755 "$DATA_DIR"
    
    echo "🎉 数据初始化完成！"
else
    echo "✅ 发现现有数据库，跳过初始化"
fi

echo "📊 数据目录状态："
ls -la "$DATA_DIR"
if [ -d "$DATA_DIR/backup" ]; then
    echo "备份文件："
    ls -la "$DATA_DIR/backup"
fi