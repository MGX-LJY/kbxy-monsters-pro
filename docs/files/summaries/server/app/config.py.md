# server/app/config.py

## 概述
应用程序配置管理模块，基于Pydantic提供类型安全的配置项管理，支持环境变量和多环境配置。

## 核心配置类

### Settings类
基于Pydantic的BaseModel，提供配置项的类型检查和验证。

## 配置项详解

### 基本配置
- **app_name**: 应用名称，默认"kbxy-monsters-pro"
- **app_env**: 应用环境，从环境变量APP_ENV读取，默认"dev"
- **cors_origins**: CORS允许的来源列表，默认localhost:5173

### 数据库配置
- **kbxy_db_path**: 自定义数据库路径，从环境变量KBXY_DB_PATH读取
- **sqlite_busy_timeout_ms**: SQLite写锁等待时间（毫秒），默认4000ms
- **sqlite_connect_timeout_s**: 连接超时时间（秒），默认5s

## 环境管理

### 支持环境
- **dev**: 开发环境，使用`kbxy-dev.db`
- **test**: 测试环境，使用`kbxy-test.db`
- **其他**: 任何非"test"的值都回落到"dev"

### 路径解析机制
1. **自定义路径**: 如果设置KBXY_DB_PATH环境变量
   - 绝对路径：直接使用
   - 相对路径：相对于`<project-root>/data/`
2. **默认路径**: 使用环境对应的默认文件名，存放在`<project-root>/data/`

## 关键方法

### normalized_env()
**功能**: 标准化环境名称
**逻辑**: 只有"test"环境返回"test"，其他均返回"dev"

### default_db_filename()
**功能**: 获取环境对应的默认数据库文件名
**返回**: 基于标准化环境的默认文件名

### resolved_local_db_path()
**功能**: 计算最终的数据库文件绝对路径
**处理逻辑**:
1. 检查KBXY_DB_PATH环境变量
2. 处理相对/绝对路径
3. 确保路径在项目data目录下
4. 返回解析后的绝对路径

## 项目结构集成

### 路径管理
- **PROJECT_ROOT**: 自动计算项目根目录（向上两层）
- **数据目录**: 统一使用`<project-root>/data/`存储数据库文件
- **环境隔离**: 不同环境使用不同的数据库文件

### SQLite优化
- **忙等待控制**: 通过busy_timeout避免频繁的数据库锁冲突
- **连接超时**: 防止连接建立时的长时间阻塞
- **环境变量控制**: 允许在不同部署环境中调整性能参数

## 使用特点

### 类型安全
- 使用Pydantic确保配置类型正确性
- 支持环境变量的自动类型转换

### 灵活配置
- 支持环境变量覆盖默认值
- 智能路径解析支持多种路径格式

### 生产就绪
- 合理的默认值配置
- 完整的路径处理逻辑
- SQLite性能优化参数

这个配置模块为整个应用提供了统一、类型安全的配置管理，是应用架构的基础设施。