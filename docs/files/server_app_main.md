---
file: server/app/main.py
type: infra
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/config.py, server/app/db.py, server/app/middleware.py, server/app/routes/*]
exposes: [app]

# main.py · 快速卡片

## TL;DR（30 秒）
- 职责：装配 FastAPI 应用（CORS、中间件、建表、路由注册、全局异常处理）。
- 关键点：`Base.metadata.create_all(bind=engine)` 在进程启动时执行一次；新增了 `collections` 路由；`tags/roles` 为可选加载。
- 常见坑
  1) **建表时机**：`create_all` 需要模型类已被导入到 `Base`；若未导入，可能导致应有表未创建。
  2) **CORS 与凭据**：`allow_credentials=True` 时，`allow_origins` 不能使用 `"*"`；需显式列出来源。
  3) **全局异常**：统一转成 `{"detail": ...}`，默认不会输出堆栈到响应；应在日志中记录异常详情。

## 职责与边界
- 做什么：实例化 `FastAPI(app_name)`；加 CORS 与 TraceID 中间件；执行一次性建表；集中注册所有路由；定义全局异常处理器。
- 不做什么：不包含业务逻辑；不处理数据库迁移（仅“按需建表”）；不做认证鉴权。

## 公开接口
- `app: FastAPI` —— 应用对象，供 `uvicorn server.app.main:app` 启动。

## 依赖与数据流
- 上游：`settings.app_name / settings.cors_origins`；`engine/Base`（来自 `db.py`）；`TraceIDMiddleware`。
- 下游：各路由模块（`health, monsters, importing, backup, utils, skills, recalc, derive, crawl, warehouse, types, collections`）以及可选 `tags/roles`。
- 初始化顺序：创建 `app` → 加中间件（CORS、TraceID） → `create_all` → `include_router(...)` → 注册异常处理器。

## 中间件与平台设置
- CORS：`allow_origins=settings.cors_origins`；`allow_credentials=True`；`allow_methods=["*"]`；`allow_headers=["*"]`。
- Trace：`TraceIDMiddleware` 从请求头读取/注入 `x-trace-id`，贯穿日志与响应。

## HTTP 路由汇总（由各 router 提供具体端点）
| Router | 典型前缀/标签 | 说明 |
|---|---|---|
| health | /health | 健康检查 |
| monsters | /monsters | 列表/详情/CRUD/批删 |
| skills | /monsters/{id}/skills | 技能读写（规范化） |
| importing | 依各文件定义 | 导入与（含）爬虫相关测试/导入入口 |
| crawl | /api/v1/crawl/* | 4399 图鉴抓取 |
| backup | /backup, /export/* | 统计、导出 CSV、备份/恢复 |
| utils | 依各文件定义 | 工具类接口 |
| recalc | /recalc | 重算相关 |
| derive | /derived, /api/v1/derived/batch | 派生/建议 |
| warehouse | (prefix="")，标签：warehouse | 仓库 possess 清单与批量设置 |
| types | /types | 元数据/类型相关 |
| collections | (prefix="")，标签：collections | 收藏夹（新增） |
| tags（可选） | /tags | 标签聚合/维护 |
| roles（可选） | /roles | 角色/定位相关 |

> 备注：`tags/roles` 通过 `try/except` 可选导入，缺失时不会阻断启动。

## 全局异常处理
- `HTTPException` → 返回 `status_code=exc.status_code`，体为 `{"detail": exc.detail}`。
- 兜底 `Exception` → 统一返回 `500`，体为 `{"detail": "internal server error"}`。建议在处理器内或中间件里记录异常与 `x-trace-id`，便于排障。

## 示例（启动与探活）
- 启动（开发）：  
  `PYTHONPATH="$(pwd)" KBXY_DB_PATH="$(pwd)/kbxy-dev.db" uvicorn server.app.main:app --reload --host 0.0.0.0 --port 8000`
- 健康检查：  
  `curl http://127.0.0.1:8000/health`

## 变更指南（How to change safely）
- 新增路由：在 `server/app/routes/xxx.py` 中定义 `router`，于此文件 `app.include_router(xxx.router, prefix? , tags?)` 挂载；保持与前端路径一致。
- 建表策略：若引入 Alembic 迁移，建议移除 `create_all` 并改为启动事件或迁移脚本统一管理。
- 可观测性：在异常处理器内记录 `trace_id`、请求方法/路径、状态码与异常摘要；必要时区分客户端错误（4xx）与服务端错误（5xx）。
- CORS 管控：按环境（dev/prod）拆分 `cors_origins`；生产环境只允许受控域名。
- 可选路由：保持 `try/except` 的**最小粒度**，避免吞掉真实导入错误（建议仅捕获 `ImportError`）。

## 自测清单
- [ ] 未配置可选模块（tags/roles）时，应用仍能启动且其端点不可用。
- [ ] CORS 预检通过（指定前端来源域名时）。
- [ ] `x-trace-id` 在请求、日志与响应中可追踪。
- [ ] 首次启动能自动创建缺失的表（确认模型已被导入）。
- [ ] 全局异常处理返回预期 JSON 结构与状态码。