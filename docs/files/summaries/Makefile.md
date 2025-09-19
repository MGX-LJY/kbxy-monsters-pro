# Makefile

## 概述
项目构建和开发工具的自动化脚本，提供统一的开发工作流命令，支持前端、后端及数据库的快速启动和环境管理。

## 环境配置

### 默认环境设置
- **默认环境**: `test` (通过 `export APP_ENV ?= test` 设置)
- **环境覆盖**: 可通过命令行参数覆盖，如 `make server APP_ENV=dev`
- **Shell配置**: 使用 `/bin/bash` 作为默认shell

## 核心命令

### install
**功能**: 安装项目依赖
**操作流程**:
1. 创建Python虚拟环境 (`.venv`)
2. 激活虚拟环境并安装后端依赖 (`server/requirements.txt`)
3. 安装前端依赖 (`cd client && npm i`)

**使用**: `make install`

### server
**功能**: 启动FastAPI后端开发服务器
**特性**:
- 端口: 8000
- 自动重载: 监听 `server` 目录变化
- 排除重载: `.venv/*`, `*/site-packages/*`, `**/__pycache__/*`
- 环境显示: 启动时显示当前 `APP_ENV` 值

**使用**: 
- `make server` (默认test环境)
- `make server APP_ENV=dev` (开发环境)

### client
**功能**: 启动React前端开发服务器
**操作**: 切换到client目录并运行 `npm run dev`
**默认端口**: 5173 (由Vite配置决定)

**使用**: `make client`

### dev
**功能**: 开发环境指导命令
**作用**: 显示开发提示信息，指导开发者在两个终端中分别运行前后端服务
**输出**: "Open two terminals: \`make server\` and \`make client\`"

**使用**: `make dev`

### seed
**功能**: 执行数据库种子数据脚本
**操作**: 运行 `python scripts/seed.py`
**用途**: 初始化或重置开发/测试数据

**使用**: `make seed`

## 开发工作流

### 标准开发流程
1. **初始化**: `make install` - 安装所有依赖
2. **启动开发**:
   - 终端1: `make server APP_ENV=dev` - 启动后端
   - 终端2: `make client` - 启动前端
3. **数据初始化**: `make seed` - 如需初始化数据

### 环境管理
- **开发环境**: `APP_ENV=dev` - 使用开发数据库
- **测试环境**: `APP_ENV=test` - 使用测试数据库（默认）
- **环境切换**: 通过命令行参数动态切换

## 技术特性

### 自动重载优化
- **智能监听**: 只监听源代码目录变化
- **排除机制**: 避免监听依赖包和缓存文件
- **性能优化**: 减少不必要的重启

### PHONY声明
所有命令都声明为 `.PHONY`，确保命令总是执行，不受同名文件影响。

## 集成特点

### 环境变量集成
- 与 `server/app/config.py` 的环境配置完全兼容
- 支持数据库文件的环境隔离
- 灵活的环境覆盖机制

### 开发体验优化
- 统一的命令接口
- 清晰的工作流指导
- 自动化的依赖管理
- 即时的环境反馈

这个Makefile为整个项目提供了标准化的开发工作流，是开发者日常工作的入口点。