file: server/app/routes/derived.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, server/app/services/derive_service.py]
exposes: [/monsters/{id}/derived(GET), /derive/{id}(GET, 兼容), /monsters/{id}/derived/recompute(POST), /derive/recalc/{id}(POST, 兼容), /derived/batch(POST), /api/v1/derived/batch(POST, 兼容), /derive/recalc_all(POST)]

TL;DR（30秒）
- 提供“派生五维 + 定位(role) + 自动标签”的读取与重算接口；默认在读取时也会**重算并落库**以保持一致。  
- 支持单个、批量与全量重算；批量接口逐条提交，失败不影响已成功项；返回明细（最多 200 条）。

职责与边界
- 做什么：按需重算 offense/survive/control/tempo/pp_pressure；回写/建议 role；自动合并标签；返回统一派生视图。  
- 不做什么：权限/速率限制；长任务编排；并发/队列；前端缓存协调（仅返回弱一致视图）。

HTTP 端点
- GET /monsters/{monster_id}/derived —— 读取并**同步重算 + 落库**后返回统一派生视图。幂等：重复调用结果稳定，但有写入副作用。  
- GET /derive/{monster_id} —— 兼容旧路径，同上。  
- POST /monsters/{monster_id}/derived/recompute —— 强制重算并落库后返回视图。  
- POST /derive/recalc/{monster_id} —— 兼容旧路径，同上。  
- POST /derived/batch —— 批量重算；Body 可选 ids，缺省/空表示“全部”。逐条提交，返回统计与明细。  
- POST /api/v1/derived/batch —— 兼容别名，同 /derived/batch。  
- POST /derive/recalc_all —— 全量重算（不返回明细），返回 {recalculated: n}。

查询参数/请求体（节选）
- /derived/batch Body：{"ids"?: number[]} —— 目标 ID 列表；缺省/[] => 全部。  
- 其他端点无查询参数或简单路径参数。

输入/输出（要点）
- 统一派生视图：{ offense, survive, control, tempo, pp_pressure, role_suggested, tags[] }  
  - role_suggested：优先返回已落库的 monster.role；无则回退 derived.role_suggested。  
  - tags：当前已落库的标签名列表（自动贴标后的最新状态）。  
- /derived/batch 返回：{ ok, total, success, failed, details[]≤200 }，details 单项形如 {id, ok, error?}。  
- /derive/recalc_all 返回：{recalculated: number}。

依赖与数据流
- compute_derived_out(m)：计算五维并生成对外 DTO。  
- recompute_and_autolabel(db, m)：重算五维 → 应用定位/角色 → 自动贴标签（合并策略）→ 写库。  
- recompute_all(db)：对全量 Monster 批量执行重算（服务层实现）。  
- DB 会话：路由层 get_db 提供；批量接口内对每个 id 执行一次重算并 commit/rollback。

事务与幂等
- 单个端点：一次请求一次事务，成功后 commit。  
- 批量端点：逐条串行执行与提交；单条失败 rollback 当前条，不影响已成功条。  
- 幂等性：在派生算法与贴标规则不变情况下，多次重算结果稳定；GET 端点有写入副作用但**结果幂等**。  
- 明细截断：/derived/batch 的 details 最多返回 200 条，超出仅统计计数。

错误与可观测性
- 404：monster 不存在（单个读取/重算）。  
- 422：Body 校验失败（ids 非法等）。  
- 批量重算明细含错误文本；遇异常对该条 rollback 并继续下一条。  
- 日志/Trace：依赖全局中间件（x-trace-id）；路由内未加显式日志。

示例（最常用）
- 读取并重算单个：curl "http://127.0.0.1:8000/monsters/123/derived"  
- 强制重算单个：curl -X POST "http://127.0.0.1:8000/monsters/123/derived/recompute"  
- 批量重算（指定 3 个）：curl -X POST -H "Content-Type: application/json" -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/derived/batch  
- 批量重算（全部）：curl -X POST -H "Content-Type: application/json" -d '{"ids":[]}' http://127.0.0.1:8000/derived/batch  
- 全量重算（无明细）：curl -X POST http://127.0.0.1:8000/derive/recalc_all

常见坑（Top 8）
1) GET /monsters/{id}/derived 有**写入副作用**（重算并落库），不适合在高频轮询中使用。  
2) 批量重算默认“全部”（ids 缺省/空数组），易误触发全库重算；请显式传 ids。  
3) 批量明细返回最多 200 条；前端不要据明细长度判断总量。  
4) 逐条提交模型下，批次一致性无法保证；如需“全成全败”需改为单事务或队列任务。  
5) 贴标为合并策略（不会盲目清空已有标签）；若需“先清空再覆盖”，需扩展服务层选项。  
6) role_suggested 可能与落库角色一致，也可能是建议值（当未落库或算法更新时）。  
7) 大库全量重算耗时较长，可能引发锁竞争或 I/O 压力；建议分批执行或增加限流。  
8) recompute_all 仅返回数量，不返回失败明细；问题排查需改用 /derived/batch。

变更指南（How to change safely）
- 拆分“读取 vs 重算”语义：若要让 GET 纯读取，可新增 /monsters/{id}/derived/view 并在现有 GET 中保留重算以兼容。  
- 扩展贴标策略：在 derive_service 中增加参数（e.g., replace_tags: bool, dry_run: bool），路由层透传。  
- 批量性能：加入分页/批次大小参数，或迁移到队列/后台任务；为 derived 相关字段建立必要索引。  
- 可观测性：为重算路径增加耗时、失败原因 TopN 的日志与指标埋点。  

术语与约定
- 五维：offense（输出）、survive（生存）、control（控制）、tempo（节奏）、pp_pressure（PP 压力）。  
- role_suggested：由派生算法建议或由贴标/定位规则写入的角色；当前实现优先返回落库值。  
- 自动贴标：根据规则给 Monster 合并标签，不清空已有非目标类标签（除非策略变更）。