# kbxy-monsters-pro 组件关系图

## 组件层次结构

```
kbxy-monsters-pro
├── Frontend Components (前端组件层)
│   ├── Application Layer (应用层)
│   │   ├── App.tsx (根应用组件)
│   │   ├── ErrorBoundary.tsx (错误边界)
│   │   └── SettingsContext.tsx (全局设置)
│   ├── Page Layer (页面层)
│   │   └── MonstersPage.tsx (主页面)
│   ├── Layout Components (布局组件)
│   │   ├── TopBar.tsx (顶部导航栏)
│   │   ├── SideDrawer.tsx (侧边抽屉)
│   │   └── Modal.tsx (模态框容器)
│   ├── Business Components (业务组件)
│   │   ├── MonsterCardGrid.tsx (妖怪卡片网格)
│   │   ├── AddMonsterDrawer.tsx (添加妖怪抽屉)
│   │   ├── ImportWizard.tsx (导入向导)
│   │   ├── FilterChips.tsx (筛选标签)
│   │   └── TypeChartModal.tsx (属性相性表)
│   ├── UI Components (通用UI组件)
│   │   ├── Pagination.tsx (分页控件)
│   │   ├── SkeletonCardGrid.tsx (骨架屏网格)
│   │   ├── SkeletonRows.tsx (骨架屏行)
│   │   ├── Toast.tsx (消息提示)
│   │   └── SettingsButton.tsx (设置按钮)
│   └── Data Layer (数据层)
│       ├── api.ts (API客户端)
│       ├── types.ts (类型定义)
│       └── main.tsx (应用入口)
├── Backend Components (后端组件层)
│   ├── Application Layer (应用层)
│   │   ├── main.py (FastAPI应用)
│   │   ├── config.py (配置管理)
│   │   └── middleware.py (中间件)
│   ├── API Layer (API层)
│   │   ├── monsters.py (妖怪API)
│   │   ├── skills.py & skills_admin.py (技能API)
│   │   ├── types.py (属性API)
│   │   ├── images.py (图片API)
│   │   ├── crawl.py (爬虫API)
│   │   ├── warehouse.py (仓库API)
│   │   ├── collections.py (收藏API)
│   │   ├── derive.py (派生计算API)
│   │   ├── tags.py (标签API)
│   │   ├── backup.py (备份API)
│   │   ├── health.py (健康检查)
│   │   ├── roles.py (角色管理)
│   │   └── utils.py (工具函数)
│   ├── Service Layer (业务服务层)
│   │   ├── monsters_service.py (妖怪服务)
│   │   ├── crawler_service.py (爬虫服务)
│   │   ├── derive_service.py (派生计算服务)
│   │   ├── skills_service.py (技能服务)
│   │   ├── types_service.py (属性服务)
│   │   ├── tags_service.py (标签服务)
│   │   ├── warehouse_service.py (仓库服务)
│   │   ├── collection_service.py (收藏服务)
│   │   ├── image_service.py (图片服务)
│   │   └── normalization.py (数据标准化)
│   └── Data Layer (数据层)
│       ├── models.py (数据模型)
│       ├── schemas.py (数据验证)
│       └── db.py (数据库连接)
├── Desktop Tools (桌面工具)
│   ├── upscaler_gui.py (GUI图片放大工具)
│   ├── upscale_batch.py (批量图片处理)
│   └── upscale.py (核心放大引擎)
└── Scripts & Utils (脚本工具)
    ├── backup_sqlite.py (数据库备份)
    ├── restore_sqlite.py (数据库恢复)
    ├── seed_from_export.py (数据导入)
    ├── sqlite_stress_write.py (性能测试)
    ├── start-bg.sh (后台启动)
    └── stop-bg.sh (后台停止)
```

## 详细组件说明

### 1. **Frontend Application Layer** - 前端应用层
这是前端应用的核心基础设施层，负责整个应用的生命周期管理、错误处理和全局状态管理。

**主要组件：**
- **App.tsx**: React应用的根组件，负责路由配置、全局Provider设置和应用初始化
- **ErrorBoundary.tsx**: 错误边界组件，捕获React组件树中的JavaScript错误，防止整个应用崩溃
- **SettingsContext.tsx**: 全局设置上下文，管理用户偏好设置、主题配置和应用状态
- **main.tsx**: 应用入口点，负责React应用的DOM挂载和初始化配置

**关键职责：**
- 应用生命周期管理
- 全局错误处理和恢复
- 用户设置持久化
- 路由和导航管理
- 全局状态初始化

### 2. **Backend Service Layer** - 后端业务服务层
这是后端的核心业务逻辑层，封装了所有的业务规则、数据处理逻辑和外部系统集成。

**主要组件：**
- **monsters_service.py**: 妖怪数据管理的核心服务，处理CRUD操作、搜索筛选、数据验证
- **crawler_service.py**: 网络爬虫服务，负责从外部数据源获取妖怪信息并标准化处理
- **derive_service.py**: 派生属性计算服务，实现五维属性评估、等级换算、潜力分析
- **image_service.py**: 图片处理服务，集成AI放大技术、文件管理、格式转换

**关键职责：**
- 业务规则封装和执行
- 数据验证和标准化
- 外部系统集成
- 性能优化和缓存管理
- 错误处理和日志记录

### 3. **API Gateway Layer** - API网关层
这是前后端通信的桥梁，负责请求路由、数据验证、权限控制和响应格式化。

**主要组件：**
- **FastAPI Routes**: 各个功能模块的RESTful API端点定义
- **Middleware**: 跨切面关注点处理，包括CORS、日志、异常处理
- **Schema Validation**: 使用Pydantic进行请求/响应数据验证
- **Error Handling**: 统一的错误处理和响应格式化

**关键职责：**
- HTTP请求路由和分发
- 请求/响应数据验证
- 跨域资源共享处理
- API文档自动生成
- 统一错误响应格式

### 4. **Data Management Layer** - 数据管理层
这是系统的数据持久化和管理层，负责数据建模、存储、查询优化和数据完整性保证。

**主要组件：**
- **models.py**: SQLAlchemy ORM模型定义，包括Monster、Skill、Tag等核心实体
- **db.py**: 数据库连接管理、会话控制、连接池配置
- **schemas.py**: Pydantic数据验证模式，确保API数据类型安全
- **Migration Scripts**: 数据库版本控制和迁移脚本

**关键职责：**
- 数据模型定义和关系映射
- 数据库连接和事务管理
- 查询优化和索引策略
- 数据完整性和一致性保证
- 备份和恢复机制

## 组件依赖关系

```
Frontend Dependencies (前端依赖关系)
┌─────────────────────────────────────────────────────────────┐
│  App.tsx (应用根)                                           │
│  ├─ ErrorBoundary.tsx                                      │
│  ├─ SettingsContext.tsx                                    │
│  └─ MonstersPage.tsx                                       │
│      ├─ TopBar.tsx                                         │
│      │   ├─ SettingsButton.tsx                             │
│      │   └─ TypeChartModal.tsx                             │
│      ├─ FilterChips.tsx                                    │
│      ├─ MonsterCardGrid.tsx                                │
│      │   ├─ SkeletonCardGrid.tsx                           │
│      │   └─ Pagination.tsx                                 │
│      ├─ SideDrawer.tsx                                     │
│      │   ├─ AddMonsterDrawer.tsx                           │
│      │   ├─ ImportWizard.tsx                               │
│      │   └─ SkeletonRows.tsx                               │
│      ├─ Modal.tsx                                          │
│      └─ Toast.tsx                                          │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ (HTTP Requests)
┌─────────────────────────────────────────────────────────────┐
│  api.ts (API客户端)                                         │
│  ├─ types.ts (类型定义)                                     │
│  └─ React Query (状态管理)                                  │
└─────────────────────────────────────────────────────────────┘

Backend Dependencies (后端依赖关系)
┌─────────────────────────────────────────────────────────────┐
│  main.py (FastAPI应用)                                      │
│  ├─ middleware.py                                           │
│  ├─ config.py                                               │
│  └─ Routes (API路由层)                                      │
│      ├─ monsters.py → monsters_service.py                  │
│      ├─ skills.py → skills_service.py                      │
│      ├─ crawl.py → crawler_service.py                      │
│      ├─ images.py → image_service.py                       │
│      ├─ derive.py → derive_service.py                      │
│      ├─ warehouse.py → warehouse_service.py                │
│      ├─ collections.py → collection_service.py             │
│      ├─ types.py → types_service.py                        │
│      ├─ tags.py → tags_service.py                          │
│      └─ backup.py → (backup scripts)                       │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ (Database Operations)
┌─────────────────────────────────────────────────────────────┐
│  Service Layer (业务服务层)                                 │
│  ├─ normalization.py (数据标准化)                           │
│  └─ All *_service.py modules                               │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ (ORM Operations)
┌─────────────────────────────────────────────────────────────┐
│  Data Layer (数据层)                                        │
│  ├─ models.py (SQLAlchemy模型)                              │
│  ├─ schemas.py (Pydantic验证)                               │
│  └─ db.py (数据库连接)                                      │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼ (SQL Operations)
┌─────────────────────────────────────────────────────────────┐
│  SQLite Database (数据库)                                   │
│  ├─ monsters.db (主数据库)                                  │
│  ├─ indexes (性能索引)                                      │
│  └─ constraints (数据约束)                                  │
└─────────────────────────────────────────────────────────────┘

Desktop Tools Dependencies (桌面工具依赖)
┌─────────────────────────────────────────────────────────────┐
│  upscaler_gui.py (GUI工具)                                  │
│  ├─ upscale.py (核心引擎)                                   │
│  └─ tkinter (GUI框架)                                       │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  upscale_batch.py (批量工具)                                │
│  ├─ upscale.py (核心引擎)                                   │
│  └─ argparse (命令行解析)                                   │
└─────────────────────────────────────────────────────────────┘

Management Scripts Dependencies (管理脚本依赖)
┌─────────────────────────────────────────────────────────────┐
│  Database Scripts                                          │
│  ├─ backup_sqlite.py → SQLite Database                     │
│  ├─ restore_sqlite.py → Backup Files                       │
│  ├─ seed_from_export.py → External Data Sources            │
│  └─ sqlite_stress_write.py → Performance Testing           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  System Scripts                                            │
│  ├─ start-bg.sh → FastAPI Application                      │
│  └─ stop-bg.sh → Process Management                        │
└─────────────────────────────────────────────────────────────┘
```

### 依赖说明

**前端组件依赖层次：**
1. **App层级**: App.tsx作为顶层容器，依赖ErrorBoundary和SettingsContext提供基础服务
2. **页面层级**: MonstersPage.tsx作为主页面，聚合所有业务组件
3. **组件层级**: 各业务组件相对独立，通过props和context进行通信
4. **数据层级**: api.ts统一管理所有HTTP请求，React Query提供状态管理

**后端服务依赖层次：**
1. **应用层级**: main.py作为应用入口，集成所有路由和中间件
2. **API层级**: 各路由模块依赖对应的服务层处理业务逻辑
3. **服务层级**: 业务服务依赖数据层进行数据操作
4. **数据层级**: ORM模型和数据库连接管理所有数据持久化

**跨层通信机制：**
- **前后端通信**: 通过RESTful API和JSON数据格式
- **组件通信**: React Context、Props传递、事件回调
- **服务通信**: 直接函数调用和依赖注入
- **数据库通信**: SQLAlchemy ORM和原生SQL查询

## 数据流组件

### 前端数据流组件
```
User Interaction → Component State → API Request → Backend Processing
        ↓                ↓              ↓               ↓
   Event Handlers → React Hooks → api.ts → FastAPI Routes
        ↓                ↓              ↓               ↓
   State Updates → Re-rendering → Response → Service Layer
        ↓                ↓              ↓               ↓
   UI Updates → Effect Hooks → Data Update → Database
```

**组件级数据流：**
- **MonstersPage**: 管理页面级状态（搜索条件、分页信息、选中项）
- **MonsterCardGrid**: 处理列表数据展示和虚拟滚动
- **FilterChips**: 管理筛选条件状态和用户交互
- **AddMonsterDrawer**: 处理表单数据验证和提交

### 后端数据流组件
```
HTTP Request → Route Handler → Service Logic → Database Operation
     ↓              ↓              ↓               ↓
Request Validation → Business Rules → Data Validation → SQL Execution
     ↓              ↓              ↓               ↓
Data Extraction → Processing → ORM Operations → Result Set
     ↓              ↓              ↓               ↓
Response Formation → Serialization → Data Mapping → HTTP Response
```

**服务级数据流：**
- **monsters_service**: 处理妖怪数据的CRUD操作和复杂查询
- **crawler_service**: 管理外部数据获取和标准化流程
- **image_service**: 处理图片上传、AI处理和文件管理
- **derive_service**: 执行复杂的属性计算和数据分析

### 系统集成数据流组件
```
External APIs → Crawler Service → Normalization → Database Storage
     ↓               ↓               ↓               ↓
Data Sources → Data Extraction → Format Conversion → Persistent Storage
     ↓               ↓               ↓               ↓
Real-time Updates → Processing Queue → Validation Pipeline → Index Updates
     ↓               ↓               ↓               ↓
User Interface → State Synchronization → Cache Invalidation → UI Refresh
```

**集成组件：**
- **外部API集成**: 通过crawler_service与外部妖怪数据源集成
- **AI服务集成**: 通过image_service与Real-ESRGAN模型集成
- **文件系统集成**: 图片存储、备份文件、日志文件管理
- **数据库集成**: SQLite数据持久化和查询优化