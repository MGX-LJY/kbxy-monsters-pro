#!/bin/bash

# Docker环境检查脚本
# 用于诊断Docker部署问题

echo "🔍 KBXY Monsters Pro Docker环境检查"
echo "=================================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查函数
check_ok() {
    echo -e "${GREEN}✅ $1${NC}"
}

check_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

check_error() {
    echo -e "${RED}❌ $1${NC}"
}

# 1. 检查Docker是否安装并运行
echo "📦 检查Docker环境..."
if command -v docker >/dev/null 2>&1; then
    check_ok "Docker已安装"
    if docker info >/dev/null 2>&1; then
        check_ok "Docker服务正在运行"
    else
        check_error "Docker服务未运行，请启动Docker"
        exit 1
    fi
else
    check_error "Docker未安装"
    exit 1
fi

# 2. 检查docker-compose
echo ""
echo "🐋 检查Docker Compose..."
if command -v docker-compose >/dev/null 2>&1; then
    check_ok "docker-compose已安装"
else
    check_error "docker-compose未安装"
    exit 1
fi

# 3. 检查配置文件
echo ""
echo "📄 检查配置文件..."
if [ -f "docker-compose.yml" ]; then
    check_ok "docker-compose.yml存在"
    
    # 验证配置
    if docker-compose config >/dev/null 2>&1; then
        check_ok "docker-compose配置有效"
    else
        check_error "docker-compose配置无效"
        docker-compose config
    fi
else
    check_error "docker-compose.yml不存在"
    exit 1
fi

# 4. 检查Dockerfile
echo ""
echo "🏗️  检查Dockerfile..."
if [ -f "server/Dockerfile" ]; then
    check_ok "后端Dockerfile存在"
else
    check_error "server/Dockerfile不存在"
fi

if [ -f "client/Dockerfile" ]; then
    check_ok "前端Dockerfile存在"
else
    check_error "client/Dockerfile不存在"
fi

# 5. 检查数据目录
echo ""
echo "💾 检查数据目录..."
if [ -d "data" ]; then
    check_ok "源数据目录存在"
    if [ -f "data/kbxy-dev.db" ]; then
        size=$(du -h data/kbxy-dev.db | cut -f1)
        check_ok "数据库文件存在 (${size})"
    else
        check_warning "数据库文件不存在，将创建新的"
    fi
    
    if [ -d "data/backup" ]; then
        backup_count=$(ls data/backup/*.zip 2>/dev/null | wc -l)
        check_ok "备份目录存在 (${backup_count} 个备份文件)"
    else
        check_warning "备份目录不存在"
    fi
else
    check_warning "源数据目录不存在，将使用空数据库"
fi

if [ -d "docker-data" ]; then
    check_ok "Docker数据目录已存在"
else
    check_warning "Docker数据目录不存在，将自动创建"
fi

# 6. 检查端口占用
echo ""
echo "🌐 检查端口占用..."
if lsof -i :8000 >/dev/null 2>&1; then
    process=$(lsof -i :8000 | tail -n 1 | awk '{print $1, $2}')
    check_warning "端口8000被占用: $process"
else
    check_ok "端口8000可用"
fi

if lsof -i :8080 >/dev/null 2>&1; then
    process=$(lsof -i :8080 | tail -n 1 | awk '{print $1, $2}')
    check_warning "端口8080被占用: $process"
else
    check_ok "端口8080可用"
fi

# 7. 检查网络连接
echo ""
echo "🌍 检查网络连接..."
if curl -s --max-time 5 https://registry-1.docker.io >/dev/null; then
    check_ok "Docker Hub连接正常"
else
    check_error "无法连接Docker Hub，可能需要配置镜像源"
    echo "    解决方案：参考 DOCKER_DEPLOY.md 中的网络问题解决部分"
fi

# 8. 检查现有容器
echo ""
echo "📋 检查现有容器..."
if docker-compose ps | grep -q "kbxy"; then
    check_warning "发现现有KBXY容器"
    docker-compose ps
else
    check_ok "没有现有KBXY容器"
fi

# 9. 磁盘空间检查
echo ""
echo "💿 检查磁盘空间..."
available=$(df . | tail -1 | awk '{print $4}')
if [ "$available" -gt 1048576 ]; then  # 1GB in KB
    check_ok "磁盘空间充足"
else
    check_warning "磁盘空间可能不足"
fi

# 10. 内存检查
echo ""
echo "🧠 检查系统资源..."
if [ "$(uname)" = "Darwin" ]; then
    # macOS
    memory=$(sysctl -n hw.memsize)
    memory_gb=$((memory / 1024 / 1024 / 1024))
    if [ "$memory_gb" -ge 4 ]; then
        check_ok "系统内存充足 (${memory_gb}GB)"
    else
        check_warning "系统内存较少 (${memory_gb}GB)"
    fi
else
    # Linux
    memory=$(free -g | awk '/^Mem:/{print $2}')
    if [ "$memory" -ge 4 ]; then
        check_ok "系统内存充足 (${memory}GB)"
    else
        check_warning "系统内存较少 (${memory}GB)"
    fi
fi

echo ""
echo "🎯 检查完成！"
echo ""

# 提供建议
echo "💡 建议："
echo "1. 如果网络连接有问题，请配置Docker镜像源"
echo "2. 如果端口被占用，请先停止占用进程或修改端口配置"
echo "3. 确保有足够的磁盘空间用于镜像构建"
echo "4. 参考 DOCKER_DEPLOY.md 获取详细部署说明"
echo ""
echo "🚀 准备就绪后，运行: ./docker-start.sh"