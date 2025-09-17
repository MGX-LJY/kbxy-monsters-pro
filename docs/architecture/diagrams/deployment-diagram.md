# kbxy-monsters-pro 部署架构图

## 部署概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        部署架构总览                               │
├─────────────────────────────────────────────────────────────────┤
│  开发环境 (Development)                                         │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 本地开发机器                                            │   │
│  │ ├─ Frontend: Vite Dev Server (5173)                    │   │
│  │ ├─ Backend: FastAPI Dev Server (8000)                  │   │
│  │ ├─ Database: SQLite Local File                         │   │
│  │ └─ AI Tools: Local Real-ESRGAN                         │   │
│  └─────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│  测试环境 (Testing/Staging)                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 测试服务器                                              │   │
│  │ ├─ Frontend: Nginx Static Files                        │   │
│  │ ├─ Backend: Uvicorn ASGI Server                        │   │
│  │ ├─ Database: SQLite + Backup Strategy                  │   │
│  │ └─ Process: Background Service Scripts                 │   │
│  └─────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────┤
│  生产环境 (Production)                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 生产服务器                                              │   │
│  │ ├─ Reverse Proxy: Nginx (80/443)                       │   │
│  │ ├─ Frontend: Static Files + CDN                        │   │
│  │ ├─ Backend: Uvicorn + Process Manager                  │   │
│  │ ├─ Database: SQLite + Auto Backup                      │   │
│  │ ├─ Storage: File System + Backup                       │   │
│  │ ├─ AI Service: GPU-enabled Processing                  │   │
│  │ ├─ Monitoring: Health Checks + Logging                 │   │
│  │ └─ Security: SSL/TLS + Firewall                        │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 详细部署架构

### 开发环境 (Development Environment)
```bash
# 开发环境架构
Local Development Machine
├── Node.js Environment
│   ├── Frontend Development
│   │   ├── Vite Dev Server (http://localhost:5173)
│   │   ├── HMR (Hot Module Replacement)
│   │   ├── TypeScript Compiler
│   │   └── TailwindCSS JIT Compiler
│   └── Package Management
│       ├── npm/yarn for dependencies
│       ├── Node modules caching
│       └── Development dependencies
├── Python Environment
│   ├── Backend Development
│   │   ├── FastAPI Dev Server (http://localhost:8000)
│   │   ├── Auto-reload on file changes
│   │   ├── Debug mode enabled
│   │   └── API documentation (http://localhost:8000/docs)
│   ├── Virtual Environment
│   │   ├── Python 3.9+ runtime
│   │   ├── Package isolation
│   │   └── Development dependencies
│   └── AI Tools
│       ├── Real-ESRGAN local setup
│       ├── GPU/CPU processing
│       └── Model files storage
├── Database Layer
│   ├── SQLite Database File
│   │   ├── monsters.db (development data)
│   │   ├── Fast local access
│   │   └── No network overhead
│   └── Database Tools
│       ├── SQLite browser/viewer
│       ├── Migration scripts
│       └── Seed data scripts
└── Development Tools
    ├── Version Control (Git)
    ├── IDE/Editor (VS Code)
    ├── Browser DevTools
    └── API Testing (Postman/Insomnia)

# 启动命令
cd client && npm run dev          # Frontend dev server
cd server && python -m uvicorn app.main:app --reload  # Backend dev server
```

### 测试环境 (Testing/Staging Environment)
```bash
# 测试环境架构
Testing Server (Ubuntu/CentOS)
├── Web Server Layer
│   ├── Nginx Configuration
│   │   ├── Static file serving (/var/www/kbxy-monsters)
│   │   ├── Reverse proxy to backend (proxy_pass)
│   │   ├── Gzip compression enabled
│   │   └── Access/Error logging
│   └── SSL/TLS Setup
│       ├── Let's Encrypt certificates
│       ├── HTTPS redirect (301)
│       └── Security headers
├── Application Layer
│   ├── Backend Service
│   │   ├── Uvicorn ASGI server
│   │   ├── Multiple worker processes
│   │   ├── Unix socket communication
│   │   └── Environment variables
│   ├── Process Management
│   │   ├── systemd service files
│   │   ├── Auto-restart on failure
│   │   ├── Log rotation
│   │   └── Resource limits
│   └── Python Environment
│       ├── Production dependencies only
│       ├── Virtual environment
│       └── Optimized bytecode
├── Data Layer
│   ├── SQLite Database
│   │   ├── Production-like data
│   │   ├── Performance indexes
│   │   └── Integrity constraints
│   ├── File Storage
│   │   ├── Upload directory structure
│   │   ├── Image processing cache
│   │   └── Backup storage
│   └── Backup Strategy
│       ├── Automated daily backups
│       ├── Backup rotation policy
│       └── Restore testing
└── Monitoring & Testing
    ├── Health Check Endpoints
    ├── Log Aggregation
    ├── Performance Monitoring
    └── Automated Testing Suite

# 部署脚本
./start-bg.sh                    # Start backend service
sudo systemctl reload nginx      # Reload nginx config
python scripts/backup_sqlite.py  # Backup database
```

### 生产环境 (Production Environment)
```bash
# 生产环境架构
Production Server (High-Performance)
├── Load Balancer & Reverse Proxy
│   ├── Nginx Main Configuration
│   │   ├── SSL/TLS termination
│   │   ├── Rate limiting
│   │   ├── DDoS protection
│   │   ├── Health check upstream
│   │   └── Failover configuration
│   ├── Performance Optimization
│   │   ├── Static file caching
│   │   ├── Browser caching headers
│   │   ├── Gzip/Brotli compression
│   │   └── HTTP/2 support
│   └── Security Features
│       ├── Firewall rules (UFW/iptables)
│       ├── SSL certificate auto-renewal
│       ├── Security headers (HSTS, CSP)
│       └── Access control lists
├── Application Services
│   ├── FastAPI Backend Cluster
│   │   ├── Multiple Uvicorn workers
│   │   ├── Worker process recycling
│   │   ├── Graceful shutdown handling
│   │   └── Resource monitoring
│   ├── Process Management
│   │   ├── systemd service units
│   │   ├── Docker containers (optional)
│   │   ├── Auto-scaling policies
│   │   └── Circuit breaker patterns
│   └── AI Processing Service
│       ├── GPU-accelerated Real-ESRGAN
│       ├── Queue-based processing
│       ├── Resource allocation
│       └── Batch processing optimization
├── Data & Storage Layer
│   ├── Database Management
│   │   ├── SQLite with WAL mode
│   │   ├── Connection pooling
│   │   ├── Query optimization
│   │   └── Performance indexes
│   ├── File Storage System
│   │   ├── Hierarchical directory structure
│   │   ├── CDN integration (optional)
│   │   ├── Image optimization pipeline
│   │   └── Distributed storage (optional)
│   └── Backup & Recovery
│       ├── Automated backup schedules
│       ├── Off-site backup storage
│       ├── Point-in-time recovery
│       └── Disaster recovery plans
├── Monitoring & Operations
│   ├── System Monitoring
│   │   ├── Resource usage (CPU, Memory, Disk)
│   │   ├── Network performance
│   │   ├── Service health checks
│   │   └── Alert management
│   ├── Application Monitoring
│   │   ├── API response times
│   │   ├── Error rate tracking
│   │   ├── User session analytics
│   │   └── Performance profiling
│   └── Logging & Alerting
│       ├── Centralized log collection
│       ├── Log analysis and search
│       ├── Real-time alerting
│       └── Incident response automation
└── Security & Compliance
    ├── Access Control
    │   ├── SSH key-based authentication
    │   ├── VPN access for administration
    │   ├── Role-based permissions
    │   └── Audit logging
    ├── Data Protection
    │   ├── Encryption at rest
    │   ├── Encryption in transit
    │   ├── Data anonymization
    │   └── GDPR compliance measures
    └── Security Hardening
        ├── OS security updates
        ├── Application vulnerability scanning
        ├── Penetration testing
        └── Security incident response

# 生产部署命令
sudo systemctl start kbxy-monsters-backend  # Start main service
sudo systemctl enable kbxy-monsters-backend # Enable auto-start
sudo nginx -t && sudo systemctl reload nginx # Reload web server
sudo systemctl status kbxy-monsters-backend  # Check service status
```

## 配置管理

### 环境配置
```yaml
# 开发环境配置 (config/development.yaml)
database:
  url: "sqlite:///./monsters_dev.db"
  echo: true
  pool_size: 5

api:
  host: "127.0.0.1"
  port: 8000
  debug: true
  reload: true

frontend:
  host: "127.0.0.1"
  port: 5173
  hmr: true

ai_service:
  model_path: "./models/Real-ESRGAN"
  device: "auto"  # auto-detect GPU/CPU
  batch_size: 1

logging:
  level: "DEBUG"
  format: "detailed"
  file: "./logs/development.log"

# 生产环境配置 (config/production.yaml)
database:
  url: "sqlite:///./data/monsters_prod.db"
  echo: false
  pool_size: 20
  pool_timeout: 30

api:
  host: "0.0.0.0"
  port: 8000
  debug: false
  workers: 4

frontend:
  build_dir: "/var/www/kbxy-monsters"
  cdn_url: "https://cdn.example.com"

ai_service:
  model_path: "/opt/models/Real-ESRGAN"
  device: "cuda"  # GPU acceleration
  batch_size: 8
  queue_size: 100

security:
  cors_origins: ["https://yourdomain.com"]
  allowed_hosts: ["yourdomain.com", "www.yourdomain.com"]
  ssl_required: true

monitoring:
  health_check_interval: 30
  metrics_endpoint: "/metrics"
  log_level: "INFO"

backup:
  schedule: "0 2 * * *"  # Daily at 2 AM
  retention_days: 30
  storage_path: "/backup/kbxy-monsters"
```

### 系统服务配置
```ini
# systemd服务配置 (/etc/systemd/system/kbxy-monsters-backend.service)
[Unit]
Description=KBXY Monsters Pro Backend Service
After=network.target
Wants=network.target

[Service]
Type=exec
User=kbxy-monsters
Group=kbxy-monsters
WorkingDirectory=/opt/kbxy-monsters-pro/server
ExecStart=/opt/kbxy-monsters-pro/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=kbxy-monsters-backend

# 环境变量
Environment=PYTHONPATH=/opt/kbxy-monsters-pro/server
Environment=ENVIRONMENT=production
Environment=DATABASE_URL=sqlite:///./data/monsters_prod.db

# 资源限制
LimitNOFILE=65535
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
```

### Nginx配置
```nginx
# Nginx虚拟主机配置 (/etc/nginx/sites-available/kbxy-monsters)
server {
    listen 80;
    server_name yourdomain.com www.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name yourdomain.com www.yourdomain.com;

    # SSL配置
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=63072000" always;

    # 前端静态文件
    location / {
        root /var/www/kbxy-monsters;
        try_files $uri $uri/ /index.html;
        
        # 缓存配置
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }

    # API代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时配置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        
        # 缓冲配置
        proxy_buffering on;
        proxy_buffer_size 4k;
        proxy_buffers 8 4k;
    }

    # 文件上传限制
    client_max_body_size 50M;
    
    # 访问日志
    access_log /var/log/nginx/kbxy-monsters_access.log;
    error_log /var/log/nginx/kbxy-monsters_error.log;
}
```

## 监控和日志

### 系统监控
```bash
# 性能监控脚本 (scripts/monitor.sh)
#!/bin/bash

# 系统资源监控
check_system_resources() {
    echo "=== System Resources ==="
    echo "CPU Usage: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d% -f1)"
    echo "Memory Usage: $(free | grep Mem | awk '{printf("%.2f%%"), $3/$2 * 100.0}')"
    echo "Disk Usage: $(df -h / | tail -1 | awk '{print $5}')"
    echo "Load Average: $(uptime | awk -F'load average:' '{ print $2 }')"
}

# 应用服务监控
check_application_health() {
    echo "=== Application Health ==="
    
    # 检查后端服务状态
    if systemctl is-active --quiet kbxy-monsters-backend; then
        echo "Backend Service: RUNNING"
    else
        echo "Backend Service: DOWN"
        systemctl restart kbxy-monsters-backend
    fi
    
    # 检查数据库连接
    if python -c "import sqlite3; sqlite3.connect('./data/monsters_prod.db').execute('SELECT 1')"; then
        echo "Database: ACCESSIBLE"
    else
        echo "Database: ERROR"
    fi
    
    # 检查API健康状态
    if curl -f http://localhost:8000/health > /dev/null 2>&1; then
        echo "API Health Check: PASS"
    else
        echo "API Health Check: FAIL"
    fi
}

# 日志分析
analyze_logs() {
    echo "=== Log Analysis ==="
    echo "Recent Errors (last 1 hour):"
    journalctl -u kbxy-monsters-backend --since "1 hour ago" --grep "ERROR" --no-pager
    
    echo "API Response Times (last 100 requests):"
    tail -100 /var/log/nginx/kbxy-monsters_access.log | awk '{print $10}' | sort -n | tail -10
}

# 执行监控检查
check_system_resources
check_application_health
analyze_logs
```

### 日志管理
```yaml
# 日志配置 (logging.yaml)
version: 1
disable_existing_loggers: false

formatters:
  default:
    format: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
  detailed:
    format: '%(asctime)s - %(name)s - %(levelname)s - %(module)s - %(funcName)s - %(message)s'

handlers:
  console:
    class: logging.StreamHandler
    level: INFO
    formatter: default
    stream: ext://sys.stdout

  file:
    class: logging.handlers.RotatingFileHandler
    level: DEBUG
    formatter: detailed
    filename: /var/log/kbxy-monsters/application.log
    maxBytes: 10485760  # 10MB
    backupCount: 10

  error_file:
    class: logging.handlers.RotatingFileHandler
    level: ERROR
    formatter: detailed
    filename: /var/log/kbxy-monsters/error.log
    maxBytes: 10485760  # 10MB
    backupCount: 5

loggers:
  kbxy_monsters:
    level: DEBUG
    handlers: [console, file, error_file]
    propagate: false

  uvicorn:
    level: INFO
    handlers: [console, file]
    propagate: false

root:
  level: INFO
  handlers: [console, file]
```

## 扩展性设计

### 水平扩展策略
```bash
# 负载均衡配置 (nginx upstream)
upstream backend_servers {
    least_conn;
    server 127.0.0.1:8000 weight=3;
    server 127.0.0.1:8001 weight=3;
    server 127.0.0.1:8002 weight=2;
    
    # 健康检查
    keepalive 32;
    keepalive_requests 100;
    keepalive_timeout 60s;
}

# 多实例部署
# 实例1: 端口8000 (主要API服务)
# 实例2: 端口8001 (AI图片处理专用)
# 实例3: 端口8002 (数据爬取和导入专用)
```

### 容器化部署 (可选)
```dockerfile
# Dockerfile.backend
FROM python:3.9-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建非root用户
RUN useradd --create-home --shell /bin/bash app
USER app

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  backend:
    build:
      context: ./server
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    environment:
      - ENVIRONMENT=production
      - DATABASE_URL=sqlite:///./data/monsters_prod.db
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./client/dist:/var/www/kbxy-monsters
      - ./ssl:/etc/ssl
    depends_on:
      - backend
    restart: unless-stopped
```

### 数据库扩展选项
```python
# 数据库扩展配置 (database_scaling.py)
# 选项1: SQLite读写分离
DATABASES = {
    'write': {
        'url': 'sqlite:///./data/monsters_write.db',
        'pool_size': 10,
    },
    'read': {
        'url': 'sqlite:///./data/monsters_read.db',
        'pool_size': 20,
    }
}

# 选项2: 迁移到PostgreSQL (高并发场景)
DATABASE_URL = "postgresql://user:password@localhost/kbxy_monsters"

# 选项3: 分布式缓存 (Redis)
CACHE_CONFIG = {
    'redis_url': 'redis://localhost:6379/0',
    'cache_ttl': 3600,  # 1 hour
    'max_connections': 20,
}
```

### 性能优化配置
```python
# 性能优化设置 (performance.py)
# API响应缓存
CACHE_MIDDLEWARE = {
    'monsters_list': 300,  # 5分钟缓存
    'types_chart': 3600,   # 1小时缓存
    'skills_data': 1800,   # 30分钟缓存
}

# 数据库查询优化
DATABASE_OPTIMIZATION = {
    'connection_pool_size': 20,
    'connection_pool_overflow': 30,
    'query_cache_size': 1000,
    'prepared_statements': True,
}

# 静态文件CDN
CDN_CONFIG = {
    'enabled': True,
    'base_url': 'https://cdn.example.com',
    'cache_duration': 31536000,  # 1年
}
```