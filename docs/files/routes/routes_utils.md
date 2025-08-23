file: server/app/routes/utils.py
type: route
owner: backend
updated: 2025-08-23
stability: maintenance
deps: [server/app/db.py, server/app/models.py, server/app/services/derive_service.py]
exposes: [/utils/backfill_raw_to_columns(POST)]

TL;DR（30秒）
- 把 explain_json.raw_stats 中的六维原始值，回填到 Monster 列上（仅当列为 None 或数值为 0.0 时），随后重算派生并持久化。用于老数据迁移/纠偏。

职责与边界
- 做什么：全表扫描 → 从 raw_stats 读取 hp/speed/attack/defense/magic/resist → 条件式回填 → compute_and_persist。  
- 不做什么：标签/角色定位更新、增量定位、并发控制、分页/分批。

HTTP 端点
- POST /utils/backfill_raw_to_columns —— 触发一次性回填任务；返回 {"updated_rows": number}。幂等：回填后重复调用一般变为 0。

请求/响应（要点）
- 无请求体与查询参数。  
- 响应：updated_rows 为实际执行了回填并触发重算的记录数。

依赖与数据流
- 读取：select(Monster) 全表拉取到内存。  
- 对每条：从 m.explain_json.raw_stats 取各六维；若目标列 need(v)（None 或可转为 float 且值为 0.0，或无法转 float）且 raw 中对应键存在 → 以 float(raw[k]) 覆盖列值；标记 changed。  
- 若 changed：调用 compute_and_persist(db, m) 重算派生五维。  
- 循环结束统一 db.commit()。

事务与幂等
- 单事务提交；失败将抛出 500（无局部回滚）。  
- 幂等：回填后再次执行通常不再触发更新（除非列仍为 None/0.0 或 raw_stats 新增）。

错误与可观测性
- 无错误捕获与日志；任何异常直接冒泡。  
- 无进度/耗时指标；对大表缺乏可观测性。

示例（最常用）
- 执行回填：curl -X POST "http://127.0.0.1:8000/utils/backfill_raw_to_columns"  
  预期返回：{"updated_rows": 123}

常见坑（Top 8）
1) 把 0.0 视为“缺失”并回填：若业务允许真实 0 值，会被覆盖。  
2) 全表载入到内存：大数据量可能占用大量内存并拖慢请求；建议离线或分批。  
3) 仅当 raw_stats 有值才回填；raw 不完整的字段不会更新。  
4) 未更新标签/角色：只重算派生五维；若派生依赖标签/角色，请另行触发相应流程。  
5) compute_and_persist 每条都执行：在大表上耗时较长，且无批处理。  
6) 无鉴权与保护：任何人可触发全库回填。  
7) 读写竞争：与其它写路径并发时缺少乐观锁，可能出现覆盖。  
8) 无 dry-run：无法预览将要更新的数量与样例。

变更指南（How to change safely）
- 增加 dry_run=true：仅统计将更新的条数与样例 id。  
- 分批与限流：按 id 范围或分页处理，每批 commit，降低锁与内存压力。  
- 引入保护：管理权限校验，或要求确认参数如 confirm=true。  
- 更精细的 need 判定：支持“仅在 None 时回填”的模式 avoid_zero_override=true。  
- 可观测性：记录耗时、更新计数、失败原因 TopN。  
- 并发安全：加入版本号/更新时间检查，避免覆盖近期更改。