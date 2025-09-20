# KBXY Monsters Pro Docker部署指南

## 🎯 概述

本项目已完全Docker化，支持orbstack和标准Docker环境。所有现有数据库和备份数据将自动迁移到Docker volume中。

## 📁 文件结构

```
├── docker-compose.yml      # Docker Compose配置
├── docker-start.sh         # 快速启动脚本  
├── docker-stop.sh          # 停止脚本
├── scripts/docker/
│   ├── deploy.sh           # 完整部署脚本
│   └── init-data.sh        # 数据初始化脚本
├── server/
│   ├── Dockerfile          # 后端镜像
│   └── init-data.sh        # 容器内数据初始化
├── client/
│   └── Dockerfile          # 前端镜像
└── docker-data/            # 数据持久化目录(自动创建)
    ├── kbxy-dev.db         # 数据库文件
    ├── backup/             # 备份文件
    └── images/             # 图片文件
        └── monsters/       # 怪兽图片(893个)
```

## 🚀 快速启动

### 方法1: 使用快速启动脚本
```bash
# 给脚本执行权限
chmod +x docker-start.sh docker-stop.sh

# 启动服务
./docker-start.sh
```

### 方法2: 使用完整部署脚本
```bash
# 完整部署(包含数据迁移)
chmod +x scripts/docker/deploy.sh
./scripts/docker/deploy.sh
```

### 方法3: 手动部署
```bash
# 1. 创建数据目录并复制现有数据
mkdir -p docker-data/backup
cp data/kbxy-dev.db docker-data/ 2>/dev/null || true
cp -r data/backup/* docker-data/backup/ 2>/dev/null || true

# 2. 启动服务
docker-compose up -d --build
```

## 📱 访问地址

- **前端**: http://localhost:8080
- **后端API**: http://localhost:8000
- **健康检查**: http://localhost:8000/health

## 🛠️ 常用命令

```bash
# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
docker-compose logs backend
docker-compose logs frontend

# 重启服务
docker-compose restart

# 停止服务
docker-compose down
# 或使用脚本
./docker-stop.sh

# 完全重置(删除容器和volume)
docker-compose down -v
```

## 🔧 常见问题解决

### 问题1: 依赖库缺失

**错误**: `ModuleNotFoundError: No module named 'PIL'`

**解决方案**: 确保 `server/requirements.txt` 包含所有必需依赖：
```
Pillow>=10.0.0  # 图像处理库
DrissionPage    # 网页爬虫
beautifulsoup4>=4.12.2
lxml>=5.2.0
```

**重新构建**: `docker-compose up --build -d`

### 问题2: Docker镜像拉取超时

如果遇到 "TLS handshake timeout" 错误，需要配置Docker镜像源：

#### orbstack用户
```bash
# 创建或编辑Docker daemon配置
mkdir -p ~/.docker
cat > ~/.docker/daemon.json << EOF
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerhub.azk8s.cn",
    "https://docker.mirrors.ustc.edu.cn"
  ]
}
EOF

# 重启orbstack
```

#### Docker Desktop用户
1. 打开Docker Desktop设置
2. 进入Docker Engine
3. 添加镜像源配置：
```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerhub.azk8s.cn"
  ]
}
```

#### 临时解决方案
```bash
# 使用代理
export HTTP_PROXY=http://your-proxy:port
export HTTPS_PROXY=http://your-proxy:port

# 或等待网络恢复后重试
docker-compose build --no-cache
```

## 💾 数据管理

### 数据持久化
- 数据库、备份和图片文件存储在 `./docker-data` 目录
- 数据库挂载到容器的 `/app/data` 路径
- 图片文件挂载到容器的 `/app/images` 路径
- 容器重启后所有数据不会丢失

### 数据迁移
部署脚本会自动将现有数据复制到 `./docker-data`：
- `data/kbxy-dev.db` → `docker-data/kbxy-dev.db`
- `data/backup/*` → `docker-data/backup/*`
- `server/images/*` → `docker-data/images/*` (893个怪兽图片)

### 手动备份
```bash
# 备份整个数据目录(包含数据库、备份和图片)
tar -czf backup-$(date +%Y%m%d).tar.gz docker-data/

# 仅备份数据库
cp docker-data/kbxy-dev.db backup-kbxy-$(date +%Y%m%d).db

# 仅备份图片文件
tar -czf images-backup-$(date +%Y%m%d).tar.gz docker-data/images/
```

## 🏥 健康检查

容器配置了健康检查：
- 检查间隔: 30秒
- 超时时间: 10秒
- 重试次数: 3次
- 启动等待: 30秒

检查命令: `curl -sf http://localhost:8000/health`

## 🔍 故障排查

### 1. 容器启动失败
```bash
# 查看详细日志
docker-compose logs backend
docker-compose logs frontend

# 检查容器状态
docker-compose ps
docker inspect <container_name>
```

### 2. 数据库连接问题
```bash
# 检查数据目录权限
ls -la docker-data/

# 进入容器查看
docker-compose exec backend bash
ls -la /app/data/
```

### 3. 前端无法访问后端
```bash
# 检查网络连接
docker-compose exec frontend wget -O- http://backend:8000/health

# 检查端口映射
docker-compose ps
netstat -ln | grep :8000
```

### 4. 清理并重新开始
```bash
# 停止所有服务
docker-compose down -v

# 清理镜像(可选)
docker system prune -f

# 重新部署
./scripts/docker/deploy.sh
```

## 🔒 环境变量

可以通过环境变量自定义配置：

```bash
# 在 .env 文件中设置
APP_ENV=dev
KBXY_DB_PATH=/app/data/kbxy-dev.db
SQLITE_BUSY_TIMEOUT_MS=4000
SQLITE_CONNECT_TIMEOUT_S=5

# 或直接在命令行设置
APP_ENV=prod docker-compose up -d
```

## 🌟 orbstack优化建议

1. **启用资源限制**：
   ```yaml
   # 在docker-compose.yml中添加
   deploy:
     resources:
       limits:
         memory: 512M
   ```

2. **使用本地网络**：
   orbstack默认优化了本地网络性能

3. **文件同步**：
   数据目录使用bind mount确保最佳性能

## 📞 支持

如果遇到问题：
1. 查看本文档的故障排查部分
2. 检查Docker和orbstack是否正常运行
3. 确认网络连接正常
4. 查看容器日志获取详细错误信息

---

✅ **部署完成后，你的KBXY Monsters Pro将在Docker容器中运行，所有现有数据已安全迁移！**