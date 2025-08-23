file: server/app/routes/tasks.py
type: route
owner: backend
updated: 2025-08-23
stability: experimental
deps: [server/app/db.py, server/app/models.py, server/app/services/rules_engine.py, server/app/services/monsters_service.py, server/app/services/skills_service.py, threading, uuid]
exposes: [/tasks/recalc(POST), /tasks/{task_id}(GET)]

TL;DR（30秒）
- 启动一个“后台重算任务”，逐个怪物调用 `rules_engine.calc_scores`，把 `explain_json` 写回，并**合并**数值标签与“从技能文本抽取的标签”后落库；任务进度存到 `Task` 表，提供查询接口。  
- 采用 Python 线程 + 独立 DB 会话；无取消/限速/鉴权。

职责与边界
- 做什么：创建异步任务记录 → 后台线程全表遍历 → 写回 explain 与标签 → 按批更新任务进度 → 提供轮询查询。  
- 不做什么：派生五维/角色定位（未走 `derive_service`）、任务取消/重试、幂等去重、权限与审计。

HTTP 端点
- POST /tasks/recalc —— 启动重算任务。入参 `weights`（可选，自定义权重）。返回 `{task_id, status:"pending"}`。  
- GET /tasks/{task_id} —— 查询任务状态。返回 `{id, type, status, progress, total, result}`。

请求/响应（要点）
- /tasks/recalc 入参：`weights?: Dict[str,float]`（当前作为**查询参数**解析；更合理的是 JSON Body）。  
- 任务状态：`pending|running|done|failed`；`progress/total` 为已处理/总数；`result` 仅在失败时包含 `{error}`。

依赖与数据流
- 线程体 `_run_recalc(task_id, weights)`：  
  1) 置 `Task.status=running`；  
  2) 取全量 `Monster.id`；  
  3) 对每只：`calc_scores({base_*}, weights)` → `m.explain_json=r.explain`；  
  4) 标签合并：`existing ∪ r.tags ∪ derive_tags_from_texts(技能名+描述)` → `upsert_tags`；  
  5) 每处理 50 条更新一次 `Task.progress/total` 并 `commit`；最后置 `done`。  
- 异常：捕获后置 `failed` 并写 `result_json.error`。

事务与幂等
- 单线程、循环内多次 commit（每 50 条 + 结尾）。  
- 重复启动会并行跑多个线程，互不感知；无幂等键（可能重复计算与写入）。  
- 标签策略为**合并**（不清理旧标签），重复执行结果稳定但会保留历史标签。

错误与可观测性
- 失败处理：线程级 try/except；失败时任务标记为 failed。  
- 细粒度错误（单条失败）不会单独记录/跳过；任何异常会结束任务。  
- 无日志/指标；进度按条数更新，缺少 ETA、速率等。

示例（最常用）
- 启动（权重放查询参数，当前实现方式）：  
  `curl -X POST "http://127.0.0.1:8000/tasks/recalc?weights=%7B%22base_offense%22%3A1.2%2C%22base_survive%22%3A0.8%7D"`  
- 轮询：  
  `curl "http://127.0.0.1:8000/tasks/<task_id>"`

常见坑（Top 12）
1) **入参位置不合理**：`weights` 未声明为 Body，FastAPI 会把 dict 当查询参数解析，使用不便（需手工 JSON-encode）。  
2) **字段/关系名不一致风险**：使用 `m.base_offense/.../base_pp` 与 `m.skills`；若模型实际采用 `MonsterSkill` 关系且无 `m.skills` 则会失败。  
3) **缺少取消**：长任务无法中断；取消接口与任务协作标志未实现。  
4) **无鉴权/限流**：任意人可发起全库重算；并发多任务会造成写放大。  
5) **未走统一派生路径**：不调用 `recompute_and_autolabel`/`compute_and_persist`，不会更新派生五维与角色定位。  
6) **全库读写 + 频繁 commit**：每 50 条提交；在大库下 IO 抖动明显，建议分批/批量优化。  
7) **错误容错不足**：单条异常会中断整个任务；没有单条 try/rollback 继续。  
8) **竞态**：后台线程与前台写同时操作同一实体，缺乏乐观锁/版本号。  
9) **无幂等键**：同一人反复点击会产生多个任务；无法去重或合并。  
10) **结果缺乏明细**：`result_json` 只在失败时存 error；没有统计报告（变更数量、Top 标签）。  
11) **N+1 查询**：循环中 `db.get(Monster, mid)` + 访问关系可能触发多次 SQL；建议预加载或批量处理。  
12) **资源释放**：线程结束仅关闭 DB，会话泄漏风险较低但需确保异常路径也关闭（当前 finally 已处理）。

变更指南（How to change safely）
- API 设计：将 `weights` 改为 `Body(..., embed=True)`；返回 `job_id` 与创建时间。  
- 任务控制：支持取消/暂停（任务轮询检查 `Task.status in {"cancelling"}`）；加入并发上限与幂等键（如按 weights+数据快照）。  
- 路径对齐：调用 `derive_service` 做派生与角色定位，或明确标注为“仅写 explain + 合并标签”的实验任务。  
- 容错与性能：单条 try/rollback 继续；按批量（如 500 条）flush/commit；对技能与标签预加载或做批处理。  
- 观测：记录耗时、速率、变更数、失败样本；在 `result_json` 写入汇总报告。  
- 安全：加鉴权/配额；对全库任务增加确认或白名单；持久化任务创建者与权重参数。  

术语与约定
- 合并标签：`existing ∪ numeric ∪ skill_tags`；不会移除旧标签。  
- 任务进度：以处理条数为单位更新，不代表最终写入成功数。