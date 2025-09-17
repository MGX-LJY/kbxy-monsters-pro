# kbxy-monsters-pro 系统架构图

## 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户界面层 (UI Layer)                    │
├─────────────────────────────────────────────────────────────────┤
│  React Frontend          │        Desktop Tools               │
│  ┌──────────────────┐    │  ┌──────────────────────────────┐   │
│  │ React Components │    │  │  upscaler_gui.py            │   │
│  │ - MonstersPage   │    │  │  - GUI界面                   │   │
│  │ - CardGrid       │    │  │  - 图片选择                  │   │
│  │ - AddDrawer      │    │  │  - 批量处理                  │   │
│  │ - FilterChips    │    │  │                              │   │
│  │ - ImportWizard   │    │  │  upscale_batch.py           │   │
│  │ - SettingsCtx    │    │  │  - 命令行工具                │   │
│  └──────────────────┘    │  │  - 批量放大                  │   │
│           │               │  │  - 自动化处理                │   │
│           │               │  └──────────────────────────────┘   │
├───────────┼───────────────┼─────────────────────────────────────┤
│           │               │        网络通信层                   │
│           ▼               │                                     │
│  ┌──────────────────┐    │  ┌──────────────────────────────┐   │
│  │   HTTP Client    │    │  │      Real-ESRGAN API        │   │
│  │ - React Query    │◄───┼──┤ - AI图片处理                 │   │
│  │ - API调用        │    │  │ - GPU加速                    │   │
│  │ - 状态管理       │    │  │ - 超分辨率算法               │   │
│  └──────────────────┘    │  └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
           │                                     ▲
           ▼                                     │
┌─────────────────────────────────────────────────────────────────┐
│                      API网关层 (Gateway Layer)                  │
├─────────────────────────────────────────────────────────────────┤
│               FastAPI Application Server                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │    CORS      │ │  Middleware  │ │   Health     │            │
│  │   处理跨域    │ │   异常处理   │ │   健康检查    │            │
│  └──────────────┘ └──────────────┘ └──────────────┘            │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       API路由层 (Routes Layer)                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │ monsters   │ │   crawl    │ │   skills   │ │   types    │   │
│  │  妖怪管理   │ │  数据爬取   │ │  技能管理   │ │  属性管理   │   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │ warehouse  │ │collections │ │   derive   │ │   images   │   │
│  │  仓库管理   │ │  收藏管理   │ │  派生计算   │ │  图片处理   │   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│  │   backup   │ │    tags    │ │   utils    │ │   roles    │   │
│  │  备份恢复   │ │  标签管理   │ │  工具函数   │ │  角色管理   │   │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      业务逻辑层 (Service Layer)                  │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐    │
│  │ monsters_service│ │ crawler_service │ │ derive_service  │    │
│  │ - CRUD操作      │ │ - 网络爬虫      │ │ - 属性计算      │    │
│  │ - 属性验证      │ │ - 数据解析      │ │ - 五维评估      │    │
│  │ - 搜索筛选      │ │ - 重试机制      │ │ - 等级换算      │    │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘    │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐    │
│  │  skills_service │ │  types_service  │ │  tags_service   │    │
│  │ - 技能管理      │ │ - 属性克制      │ │ - 标签分类      │    │
│  │ - 效果计算      │ │ - 相性计算      │ │ - 关联管理      │    │
│  │ - 学习列表      │ │ - 伤害倍率      │ │ - 批量操作      │    │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘    │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐    │
│  │warehouse_service│ │collection_service│ │  image_service  │    │
│  │ - 持有状态      │ │ - 收藏管理      │ │ - 文件上传      │    │
│  │ - 获得记录      │ │ - 列表操作      │ │ - AI放大        │    │
│  │ - 统计分析      │ │ - 导入导出      │ │ - 格式转换      │    │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘    │
│  ┌─────────────────┐                                           │
│  │ normalization   │                                           │
│  │ - 数据标准化    │                                           │
│  │ - 格式统一      │                                           │
│  │ - 完整性检查    │                                           │
│  └─────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      数据访问层 (Data Layer)                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐    │
│  │    models.py    │ │   schemas.py    │ │      db.py      │    │
│  │ - SQLAlchemy    │ │ - Pydantic      │ │ - 数据库连接    │    │
│  │ - ORM映射       │ │ - 数据验证      │ │ - 会话管理      │    │
│  │ - 关系定义      │ │ - 序列化        │ │ - 连接池        │    │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       存储层 (Storage Layer)                    │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐    │
│  │   SQLite DB     │ │  File Storage   │ │   Log Files     │    │
│  │ - 关系数据      │ │ - 图片文件      │ │ - 操作日志      │    │
│  │ - 事务支持      │ │ - 缩略图        │ │ - 错误记录      │    │
│  │ - 索引优化      │ │ - 备份文件      │ │ - 性能监控      │    │
│  │ - ACID特性      │ │ - 临时文件      │ │ - 调试信息      │    │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## 详细组件架构

### 前端展示层架构
```
┌─────────────────────────────────────────────────────────────┐
│                    React应用架构                           │
├─────────────────────────────────────────────────────────────┤
│  App.tsx (根组件)                                          │
│  ├─ ErrorBoundary (错误边界)                              │
│  ├─ SettingsContext (全局状态)                            │
│  └─ Router                                                │
│      ├─ MonstersPage (主页面)                             │
│      │   ├─ TopBar (顶部导航)                             │
│      │   │   ├─ SearchBox                                │
│      │   │   ├─ SettingsButton                           │
│      │   │   └─ TypeChartModal                           │
│      │   ├─ FilterChips (筛选标签)                        │
│      │   ├─ MonsterCardGrid (卡片网格)                    │
│      │   │   ├─ VirtualList (虚拟滚动)                   │
│      │   │   └─ SkeletonCardGrid (骨架屏)                │
│      │   ├─ Pagination (分页控件)                         │
│      │   └─ SideDrawer (侧边抽屉)                         │
│      │       ├─ AddMonsterDrawer                         │
│      │       ├─ ImportWizard                             │
│      │       └─ SkeletonRows                             │
│      └─ Common Components                                 │
│          ├─ Modal (模态框)                                │
│          ├─ Toast (消息提示)                              │
│          └─ LoadingSpinner                               │
├─────────────────────────────────────────────────────────────┤
│  State Management (状态管理)                              │
│  ├─ React Query (服务端状态)                              │
│  │   ├─ QueryClient                                      │
│  │   ├─ useMonsters                                      │
│  │   ├─ useSkills                                        │
│  │   └─ useTypes                                         │
│  ├─ Context API (全局状态)                                │
│  │   ├─ SettingsContext                                  │
│  │   └─ ThemeContext                                     │
│  └─ Component State (组件状态)                            │
│      ├─ useState                                         │
│      ├─ useEffect                                        │
│      └─ useCallback                                      │
├─────────────────────────────────────────────────────────────┤
│  API Integration (API集成)                                │
│  ├─ api.ts (API客户端)                                    │
│  │   ├─ monstersApi                                      │
│  │   ├─ skillsApi                                        │
│  │   ├─ typesApi                                         │
│  │   └─ imagesApi                                        │
│  ├─ HTTP Client                                          │
│  │   ├─ fetch wrapper                                    │
│  │   ├─ error handling                                   │
│  │   └─ retry logic                                      │
│  └─ Type Definitions                                     │
│      ├─ types.ts                                         │
│      ├─ Monster interface                                │
│      ├─ Skill interface                                  │
│      └─ API response types                               │
└─────────────────────────────────────────────────────────────┘
```

### 后端服务层架构
```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI应用架构                         │
├─────────────────────────────────────────────────────────────┤
│  main.py (应用入口)                                        │
│  ├─ FastAPI app instance                                  │
│  ├─ CORS middleware                                       │
│  ├─ Exception handlers                                    │
│  └─ Router registration                                   │
├─────────────────────────────────────────────────────────────┤
│  Routes (路由层)                                           │
│  ├─ monsters.py                                           │
│  │   ├─ GET /monsters (列表查询)                          │
│  │   ├─ POST /monsters (创建妖怪)                         │
│  │   ├─ PUT /monsters/{id} (更新)                         │
│  │   └─ DELETE /monsters/{id} (删除)                      │
│  ├─ skills.py & skills_admin.py                           │
│  │   ├─ GET /skills (技能列表)                            │
│  │   ├─ POST /skills (创建技能)                           │
│  │   └─ PUT /skills/{id} (更新技能)                       │
│  ├─ types.py                                              │
│  │   ├─ GET /types (属性列表)                             │
│  │   └─ GET /types/chart (相性表)                         │
│  ├─ images.py                                             │
│  │   ├─ POST /images/upload (上传图片)                    │
│  │   ├─ POST /images/upscale (AI放大)                     │
│  │   └─ GET /images/{id} (获取图片)                       │
│  ├─ crawl.py                                              │
│  │   ├─ POST /crawl/start (开始爬取)                      │
│  │   └─ GET /crawl/status (爬取状态)                      │
│  ├─ backup.py                                             │
│  │   ├─ POST /backup/create (创建备份)                    │
│  │   └─ POST /backup/restore (恢复备份)                   │
│  ├─ warehouse.py                                          │
│  │   ├─ GET /warehouse (仓库状态)                         │
│  │   └─ PUT /warehouse/{id} (更新状态)                    │
│  ├─ collections.py                                        │
│  │   ├─ GET /collections (收藏列表)                       │
│  │   └─ POST /collections (添加收藏)                      │
│  ├─ derive.py                                             │
│  │   ├─ POST /derive/calculate (计算属性)                 │
│  │   └─ GET /derive/ranking (排行榜)                      │
│  ├─ tags.py                                               │
│  │   ├─ GET /tags (标签列表)                              │
│  │   └─ POST /tags (创建标签)                             │
│  ├─ utils.py                                              │
│  │   └─ 通用工具函数                                      │
│  ├─ roles.py                                              │
│  │   └─ 角色权限管理                                      │
│  └─ health.py                                             │
│      └─ GET /health (健康检查)                             │
├─────────────────────────────────────────────────────────────┤
│  Services (业务逻辑层)                                     │
│  ├─ monsters_service.py                                   │
│  │   ├─ create_monster()                                 │
│  │   ├─ get_monsters()                                   │
│  │   ├─ update_monster()                                 │
│  │   ├─ delete_monster()                                 │
│  │   └─ search_monsters()                                │
│  ├─ crawler_service.py                                    │
│  │   ├─ crawl_external_data()                            │
│  │   ├─ parse_monster_data()                             │
│  │   └─ validate_data()                                  │
│  ├─ image_service.py                                      │
│  │   ├─ upload_image()                                   │
│  │   ├─ upscale_image()                                  │
│  │   ├─ generate_thumbnail()                             │
│  │   └─ manage_storage()                                 │
│  ├─ derive_service.py                                     │
│  │   ├─ calculate_stats()                                │
│  │   ├─ evaluate_potential()                             │
│  │   └─ generate_ranking()                               │
│  ├─ skills_service.py                                     │
│  │   ├─ manage_skills()                                  │
│  │   ├─ calculate_damage()                               │
│  │   └─ learn_moves()                                    │
│  ├─ types_service.py                                      │
│  │   ├─ get_effectiveness()                              │
│  │   ├─ calculate_damage_multiplier()                    │
│  │   └─ type_chart_data()                                │
│  ├─ tags_service.py                                       │
│  │   ├─ manage_tags()                                    │
│  │   ├─ categorize_content()                             │
│  │   └─ bulk_operations()                                │
│  ├─ warehouse_service.py                                  │
│  │   ├─ track_ownership()                                │
│  │   ├─ update_status()                                  │
│  │   └─ generate_statistics()                            │
│  ├─ collection_service.py                                 │
│  │   ├─ manage_favorites()                               │
│  │   ├─ import_export()                                  │
│  │   └─ list_operations()                                │
│  └─ normalization.py                                      │
│      ├─ normalize_data()                                  │
│      ├─ validate_format()                                 │
│      └─ ensure_consistency()                              │
└─────────────────────────────────────────────────────────────┘
```

### 数据持久层架构
```
┌─────────────────────────────────────────────────────────────┐
│                    数据层架构                               │
├─────────────────────────────────────────────────────────────┤
│  ORM Layer (对象关系映射)                                  │
│  ├─ models.py                                             │
│  │   ├─ Monster Model                                     │
│  │   │   ├─ id: Integer (主键)                           │
│  │   │   ├─ name: String (名称)                          │
│  │   │   ├─ type1/type2: String (属性)                   │
│  │   │   ├─ hp/attack/defense: Integer (基础属性)        │
│  │   │   ├─ sp_attack/sp_defense/speed: Integer          │
│  │   │   ├─ image_url: String (图片链接)                 │
│  │   │   ├─ created_at/updated_at: DateTime              │
│  │   │   ├─ skills: Relationship (多对多)                │
│  │   │   └─ tags: Relationship (多对多)                  │
│  │   ├─ Skill Model                                      │
│  │   │   ├─ id: Integer (主键)                           │
│  │   │   ├─ name: String (技能名)                        │
│  │   │   ├─ type: String (属性)                          │
│  │   │   ├─ category: String (分类)                      │
│  │   │   ├─ power: Integer (威力)                        │
│  │   │   ├─ accuracy: Integer (命中)                     │
│  │   │   ├─ pp: Integer (使用次数)                       │
│  │   │   └─ description: Text (描述)                     │
│  │   ├─ Tag Model                                        │
│  │   │   ├─ id: Integer (主键)                           │
│  │   │   ├─ name: String (标签名)                        │
│  │   │   ├─ category: String (分类: buf/deb/util)        │
│  │   │   ├─ color: String (显示颜色)                     │
│  │   │   └─ description: Text (描述)                     │
│  │   ├─ Type Model                                       │
│  │   │   ├─ id: Integer (主键)                           │
│  │   │   ├─ name: String (属性名)                        │
│  │   │   ├─ color: String (属性颜色)                     │
│  │   │   └─ effectiveness: JSON (相性数据)               │
│  │   ├─ Collection Model                                 │
│  │   │   ├─ id: Integer (主键)                           │
│  │   │   ├─ user_id: String (用户标识)                   │
│  │   │   ├─ monster_id: Integer (外键)                   │
│  │   │   ├─ is_favorite: Boolean (收藏状态)              │
│  │   │   └─ added_at: DateTime (添加时间)                │
│  │   └─ Association Tables                               │
│  │       ├─ monster_skills (妖怪-技能关联)               │
│  │       ├─ monster_tags (妖怪-标签关联)                 │
│  │       └─ user_warehouse (用户仓库状态)                │
│  ├─ schemas.py (数据验证)                                 │
│  │   ├─ MonsterCreate/Update/Response                    │
│  │   ├─ SkillCreate/Update/Response                      │
│  │   ├─ TagCreate/Update/Response                        │
│  │   ├─ CollectionCreate/Update/Response                 │
│  │   └─ Pagination/Filter schemas                       │
│  └─ db.py (数据库配置)                                    │
│      ├─ database_url configuration                       │
│      ├─ SessionLocal factory                             │
│      ├─ Base class                                       │
│      ├─ get_db() dependency                              │
│      └─ connection pool settings                         │
├─────────────────────────────────────────────────────────────┤
│  Database Layer (数据库层)                                │
│  ├─ SQLite Database                                      │
│  │   ├─ monsters.db (主数据库文件)                       │
│  │   ├─ Indexes (性能优化索引)                           │
│  │   │   ├─ idx_monster_name                             │
│  │   │   ├─ idx_monster_type                             │
│  │   │   ├─ idx_skill_name                               │
│  │   │   └─ idx_tag_category                             │
│  │   ├─ Constraints (约束条件)                           │
│  │   │   ├─ Primary Keys                                 │
│  │   │   ├─ Foreign Keys                                 │
│  │   │   ├─ Unique Constraints                           │
│  │   │   └─ Check Constraints                            │
│  │   └─ Triggers (触发器)                                │
│  │       ├─ updated_at 自动更新                          │
│  │       ├─ 数据一致性检查                               │
│  │       └─ 审计日志记录                                 │
│  ├─ Backup Strategy (备份策略)                           │
│  │   ├─ backup_sqlite.py (备份脚本)                     │
│  │   ├─ restore_sqlite.py (恢复脚本)                    │
│  │   ├─ 定期自动备份                                    │
│  │   └─ 增量备份支持                                    │
│  └─ Migration System (迁移系统)                          │
│      ├─ 数据库版本控制                                   │
│      ├─ 自动迁移脚本                                     │
│      ├─ 回滚机制                                         │
│      └─ 数据完整性验证                                   │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈架构
```
┌─────────────────────────────────────────────────────────────┐
│                      技术栈分层架构                         │
├─────────────────────────────────────────────────────────────┤
│  前端技术栈                                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Presentation Layer (展示层)                        │   │
│  │ ├─ React 18 (用户界面框架)                         │   │
│  │ ├─ TypeScript (类型安全)                           │   │
│  │ ├─ TailwindCSS (样式框架)                          │   │
│  │ └─ Lucide React (图标库)                           │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ State Management (状态管理)                        │   │
│  │ ├─ React Query (服务端状态)                        │   │
│  │ ├─ Context API (全局状态)                          │   │
│  │ └─ React Hooks (组件状态)                          │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ Build Tools (构建工具)                             │   │
│  │ ├─ Vite (构建工具)                                 │   │
│  │ ├─ TypeScript Compiler                             │   │
│  │ ├─ PostCSS (CSS后处理)                             │   │
│  │ └─ ESLint + Prettier (代码质量)                    │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  后端技术栈                                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Web Framework (Web框架)                            │   │
│  │ ├─ FastAPI (高性能异步框架)                        │   │
│  │ ├─ Uvicorn (ASGI服务器)                            │   │
│  │ ├─ Pydantic (数据验证)                             │   │
│  │ └─ Python 3.9+ (运行时)                            │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ Database Stack (数据库栈)                          │   │
│  │ ├─ SQLAlchemy (ORM框架)                            │   │
│  │ ├─ SQLite (关系数据库)                             │   │
│  │ ├─ Alembic (数据库迁移)                            │   │
│  │ └─ aiosqlite (异步数据库驱动)                      │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ External Services (外部服务)                       │   │
│  │ ├─ Real-ESRGAN (AI图片放大)                        │   │
│  │ ├─ requests (HTTP客户端)                           │   │
│  │ ├─ aiofiles (异步文件操作)                         │   │
│  │ └─ PIL/Pillow (图片处理)                           │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  开发与部署工具                                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Development (开发工具)                             │   │
│  │ ├─ Git (版本控制)                                  │   │
│  │ ├─ VS Code (开发环境)                              │   │
│  │ ├─ Python venv (虚拟环境)                          │   │
│  │ └─ npm/yarn (包管理)                               │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ Desktop Tools (桌面工具)                           │   │
│  │ ├─ tkinter (GUI框架)                               │   │
│  │ ├─ Python Scripts (自动化脚本)                     │   │
│  │ └─ Batch Processing (批量处理)                     │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ Deployment (部署工具)                              │   │
│  │ ├─ Shell Scripts (启动脚本)                        │   │
│  │ ├─ systemd (服务管理)                              │   │
│  │ ├─ Nginx (反向代理)                                │   │
│  │ └─ Docker (容器化可选)                             │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 辅助工具架构

### AI图片处理架构
```
┌─────────────────────────────────────────────────────────────┐
│                    AI图片处理模块                           │
├─────────────────────────────────────────────────────────────┤
│  Desktop GUI Application                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ upscaler_gui.py                                     │   │
│  │ ├─ tkinter.Tk (主窗口)                             │   │
│  │ ├─ File Browser (文件浏览器)                       │   │
│  │ ├─ Progress Bar (进度条)                           │   │
│  │ ├─ Settings Panel (设置面板)                       │   │
│  │ └─ Results Preview (结果预览)                      │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ upscale_batch.py                                    │   │
│  │ ├─ CLI Interface (命令行接口)                      │   │
│  │ ├─ Batch Processing (批量处理)                     │   │
│  │ ├─ Queue Management (队列管理)                     │   │
│  │ └─ Error Recovery (错误恢复)                       │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ upscale.py (Core Engine)                            │   │
│  │ ├─ Real-ESRGAN Integration                          │   │
│  │ ├─ GPU Memory Management                            │   │
│  │ ├─ Image Format Support                             │   │
│  │ ├─ Quality Assessment                               │   │
│  │ └─ Multi-threading Support                          │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Processing Pipeline                                       │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Input Processing                                    │   │
│  │ ├─ Image Validation                                 │   │
│  │ ├─ Format Detection                                 │   │
│  │ ├─ Size Analysis                                    │   │
│  │ └─ Memory Requirements                              │   │
│  └─────────────────────────────────────────────────────┘   │
│            │                                               │
│            ▼                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ AI Processing                                       │   │
│  │ ├─ Model Loading                                    │   │
│  │ ├─ GPU Acceleration                                 │   │
│  │ ├─ Tile Processing                                  │   │
│  │ └─ Super Resolution                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│            │                                               │
│            ▼                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Output Processing                                   │   │
│  │ ├─ Quality Enhancement                              │   │
│  │ ├─ Format Conversion                                │   │
│  │ ├─ Metadata Preservation                            │   │
│  │ └─ File Organization                                │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 数据管理工具架构
```
┌─────────────────────────────────────────────────────────────┐
│                    数据管理工具                             │
├─────────────────────────────────────────────────────────────┤
│  Database Management Scripts                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ backup_sqlite.py                                    │   │
│  │ ├─ Database Connection                              │   │
│  │ ├─ Table Export                                     │   │
│  │ ├─ Compression Support                              │   │
│  │ └─ Metadata Recording                               │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ restore_sqlite.py                                   │   │
│  │ ├─ Backup Validation                                │   │
│  │ ├─ Data Restoration                                 │   │
│  │ ├─ Integrity Checking                               │   │
│  │ └─ Rollback Support                                 │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ seed_from_export.py                                 │   │
│  │ ├─ Data Import Processing                           │   │
│  │ ├─ Format Standardization                           │   │
│  │ ├─ Duplicate Detection                              │   │
│  │ └─ Progress Tracking                                │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ sqlite_stress_write.py                              │   │
│  │ ├─ Performance Testing                              │   │
│  │ ├─ Concurrent Operations                            │   │
│  │ ├─ Bottleneck Analysis                              │   │
│  │ └─ Optimization Recommendations                     │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  System Management Scripts                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ start-bg.sh                                         │   │
│  │ ├─ Environment Setup                                │   │
│  │ ├─ Service Dependencies                             │   │
│  │ ├─ Background Process                               │   │
│  │ └─ Health Monitoring                                │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ stop-bg.sh                                          │   │
│  │ ├─ Graceful Shutdown                                │   │
│  │ ├─ Resource Cleanup                                 │   │
│  │ ├─ Process Termination                              │   │
│  │ └─ Status Reporting                                 │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```