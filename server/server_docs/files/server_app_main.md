---
file: server/app/main.py
type: infra
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/config.py, server/app/db.py, server/app/middleware.py, server/app/routes/*]
exposes: [app]
---

# main.py · 快速卡片

## TL;DR（30 秒）
- **职责**：装配 FastAPI（CORS、TraceID 中间件、路由、全局异常）并在**启动钩子**里做**一次性 schema 初始化**与**启动日志**。  
- **受控建表**：仅在 `dev/test`，使用**文件锁**（`.schema.init.lock`）避免 `uvicorn --reload` 并发导致“索引已存在”等错误；外部库（`DATABASE_URL`）场景仅 `checkfirst=True` 一次。  
- **启动日志**：打印 `APP_ENV`/`APP_NAME`，以及来自 `db.startup_db_report_lines()` 的 DB 绝对路径、父目录、写权限、`busy_timeout(ms)`、`connect_timeout(s)` 等。  
- **路由**：核心路由固定加载；`tags/roles` **可选加载**（缺失不阻断）。

---

## 职责与边界
- **做什么**：创建 `FastAPI` 应用；配置 CORS；挂载追踪中间件；注册路由；在启动时打印运行环境/DB 信息并**安全初始化 schema**；设置统一异常响应。  
- **不做什么**：不在模块顶层建表；不做数据库迁移（后续由 Alembic 接管）；不承载业务逻辑。

---

## 公开接口
- `app: FastAPI` —— 供 `uvicorn server.app.main:app` 启动。  

---

## 启动流程（顺序）
1) 构建 `app = FastAPI(title=settings.app_name)`  
2) 加 CORS：`allow_origins=settings.cors_origins`、`allow_credentials=True`、`allow_methods/headers="*"`  
3) 加 `TraceIDMiddleware`  
4) 注册路由：`health / monsters / importing / backup / utils / skills / recalc / derive / crawl / warehouse / types / collections`；`tags / roles` **try-import**  
5) `@app.on_event("startup")`:  
   - 打印 `APP_ENV / APP_NAME`  
   - 遍历 `startup_db_report_lines()` 输出 DB 路径/超时等  
   - 调用 `_init_schema_once_with_lock()` 执行**一次性** `Base.metadata.create_all(checkfirst=True)`  
6) 全局异常处理：统一返回 `{"detail": ...}`（`HTTPException` 保留状态码，其他异常返回 500）

---

## 受控建表策略（避免 reload 竞态）
- **触发条件**：仅 `settings.app_env in ("dev","test")`。  
- **外部数据库**（`DATABASE_URL` 已设置）  
  - 直接 `create_all(checkfirst=True)` 一次；无文件锁（无法判定本地目录）。  
- **本地 SQLite**  
  - 在 DB 父目录创建锁文件 `<db_parent_dir>/.schema.init.lock`：  
    - **首次**启动进程拿到锁 → 执行 `create_all(checkfirst=True)` → 删除锁；  
    - 其他并发进程/热重载进程检测到锁存在 → **跳过**建表；  
- 设计目标：解决并发 `create_all` 导致的 “index … already exists”。

---

## CORS 与中间件
- **CORS**：因 `allow_credentials=True`，`allow_origins` **不可使用 `"*"`**，需要显式来源（已在 `settings.cors_origins` 配置）。  
- **Trace**：`TraceIDMiddleware` 注入/透传 `x-trace-id`，建议在日志中串联请求链路。

---

## 路由概览
| 模块 | 标签/前缀 | 说明 |
|---|---|---|
| `health` | `/health` | 健康检查 |
| `monsters` | `/monsters` | 怪物 CRUD |
| `skills` | `/monsters/{id}/skills` | 技能 |
| `importing` | 依实现 | 导入/爬虫入口 |
| `crawl` | `/api/v1/crawl/*` | 4399 图鉴抓取 |
| `backup` | `/backup`, `/export/*` | 导出/备份 |
| `utils` | 依实现 | 工具接口 |
| `recalc` | `/recalc` | 重算 |
| `derive` | `/derived`, `/api/v1/derived/batch` | 派生/建议 |
| `warehouse` | 标签 `warehouse` | 仓库清单/批量 |
| `types` | `/types` | 元数据 |
| `collections` | 标签 `collections` | 收藏夹 |
| `tags`（可选） | `/tags` | 标签管理 |
| `roles`（可选） | `/roles` | 角色管理 |

---

## 可观测性与错误处理
- **启动日志**：  
  - `[startup] APP_ENV=<env> APP_NAME=<name>`  
  - `[startup] DB absolute path / Parent dir / Writable / Busy timeout (ms) / Connect timeout (s)`（由 `db.py` 汇总）  
- **全局异常**：  
  - `HTTPException` → 透传状态码与 `detail`；  
  - 其他异常 → `500` + `{"detail":"internal server error"}`（堆栈仅写日志，不回传客户端）。  
- 建议：在异常处理处附带 `x-trace-id` 到日志，便于问题追踪。

---

## 自测清单
- [ ] `uvicorn --reload` 启动不再出现 “index already exists”等并发建表报错。  
- [ ] 本地 SQLite：首次启动打印 “schema create_all executed …”，后续热重载打印 “skip create_all.”。  
- [ ] `DATABASE_URL` 设置时：启动日志包含 “DB in use: DATABASE_URL (local file ignored)”。  
- [ ] CORS 预检通过（从 `http://localhost:5173` 等来源）。  
- [ ] 异常被全局处理并返回统一结构。

---

## 变更指南（How to change safely）
- **新增路由**：在 `server/app/routes/xxx.py` 定义 `router`，在此文件 `include_router`；可为其设置 `prefix` 与 `tags`。  
- **迁移到 Alembic**：迁移引入后，应移除 `_init_schema_once_with_lock()` 的建表逻辑，改为迁移脚本统一管理。  
- **生产多进程**：若以后使用 `uvicorn --workers N`，应将 schema 初始化交给迁移或单独的“init”步骤（避免多工作进程竞争锁文件）。  
- **CORS 策略**：按环境（`dev/test`）拆分来源；生产请最小化来源域名集合。