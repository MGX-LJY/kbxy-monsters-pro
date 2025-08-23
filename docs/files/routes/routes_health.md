file: server/app/routes/health.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, platform]
exposes: [/health(GET)]

TL;DR（30秒）
- 健康检查端点：返回服务可用性信号 + 版本信息 + DB 基础统计（monsters/tags 计数）。  
- 只读查询，无写入副作用；若 DB 不可用将抛异常（500）。

职责与边界
- 做什么：快速验证 API 与数据库连通性，给出基础元信息（python/fastapi/sqlalchemy、engine_version、db_path）。  
- 不做什么：深度自检（迁移状态/索引/派生正确性）、多依赖探活、权限校验。

HTTP 端点
- GET /health —— 返回 {ok, versions, db_path, engine_version, counts}。幂等：是（读取）。

查询参数/请求体（节选）
- 无。

输入/输出（要点）
- 输出字段：
  - ok: bool —— 固定 True（仅代表路由本身执行到返回）。  
  - versions: {python, fastapi, sqlalchemy} —— 其中 fastapi/sqlalchemy 为**硬编码**字符串；python 来自 platform.python_version()。  
  - db_path: "kbxy-dev.db" —— **硬编码**，非真实连接字符串。  
  - engine_version: "rules-2025.08.01" —— 规则引擎版本号标识（硬编码）。  
  - counts: {monsters, tags} —— ORM count() 结果。

依赖与数据流
- 使用 SessionLocal 创建短生命周期会话 → ORM count() 两次 → 关闭会话 → 返回 JSON。  
- 无外部网络/文件 IO。

事务与幂等
- 单次请求内创建会话，只读查询；无事务写入。  
- 幂等：相同数据状态下重复调用返回一致；随 DB 内容变化而变化。

错误与可观测性
- DB 不可连/表缺失将触发异常 → 500（未捕获）；无降级/备用路径。  
- 未记录日志；依赖全局中间件（如有）输出 trace-id。

示例（最常用）
- curl http://127.0.0.1:8000/health
- 成功响应示例：{"ok":true,"versions":{"python":"3.x.y","fastapi":"0.112","sqlalchemy":"2.x"},"db_path":"kbxy-dev.db","engine_version":"rules-2025.08.01","counts":{"monsters":123,"tags":45}}

常见坑（Top 6）
1) fastapi/sqlalchemy 版本字符串为硬编码，可能与实际安装不一致，容易误导排查。  
2) db_path 为固定文本，并不反映真实 `DATABASE_URL/KBXY_DB_PATH`；在多环境中可能产生错觉。  
3) 未捕获 DB 异常；当数据库不可达或迁移未执行时会直接 500。  
4) count() 在数据量很大时可能较慢；健康检查不宜高频调用或用于监控拉取大样本。  
5) 未输出应用启动时间/构建哈希，无法定位部署版本。  
6) 未暴露依赖探活（如外部爬虫站点、缓存、消息队列等）。

变更指南（How to change safely）
- 将版本信息改为**动态获取**：fastapi.__version__ / sqlalchemy.__version__。  
- 将 db_path 改为从配置/engine.url 提取只读展示，或直接移除以避免误导。  
- 增加 try/except 捕获 DB 异常，返回 {"ok": false, "error": "..."} 与 503 状态码更合适。  
- 添加构建信息：git_sha、started_at、env（dev/prod）、app_version。  
- 对大库：把 count 改为 `SELECT 1 FROM ... LIMIT 1` 的“可用性探测”或增加超时保护。  
- 可选：加入依赖探活子检查（cache、外部服务），并提供 `/healthz`（轻量）与 `/readyz`（依赖就绪）区分。

术语与约定
- health/ready 区分：health 用于存活探测（liveness），ready 用于就绪探测（readiness）。  
- engine_version：内部规则/映射版本标签，用于排查与数据解释一致性。