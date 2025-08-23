file: server/app/routes/tags.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, server/app/services/monsters_service.py, server/app/services/tags_service.py, server/app/services/derive_service.py]
exposes: [/tags(GET), /tags/cat_counts(GET), /tags/i18n(GET), /tags/schema(GET), /tags/catalog/reload(POST), /tags/monsters/{id}/suggest(POST), /tags/monsters/{id}/retag(POST), /tags/monsters/{id}/retag_ai(POST), /tags/ai/batch(POST), /tags/ai_batch/start(POST), /tags/ai_batch/{job_id}(GET), /tags/ai_batch/{job_id}/cancel(POST)]

TL;DR（30秒）
- 标签系统路由：提供标签列表/统计/i18n 与词表热更新；支持正则与 AI 两种打标签方式（单条与批量），并与派生/定位联动。Tag.name 存储的是“标签代码”（如 buf_*/deb_*/util_*）。

职责与边界
- 做什么：读取与统计标签；按词表与规则正则建议/落库；调用 AI 识别标签；在落库时统一触发 recompute_and_autolabel（派生+定位）。  
- 不做什么：鉴权/配额；细粒度审计；长时任务调度（仅提供简单进度制接口，真正后台逻辑在 tags_service）。

HTTP 端点
- GET /tags?with_counts=false|true —— 返回标签代码数组；with_counts=true 返回 [{name,count}]。  
- GET /tags/cat_counts —— 统计三大类（增强/削弱/特殊）覆盖数，并附每个 code 的明细计数。  
- GET /tags/i18n —— 返回 {code: 中文名} 映射（来自 tags_catalog.json）。  
- GET /tags/schema —— 依据前缀 buf_/deb_/util_ 输出 {groups, default}，groups 内为各类的 code 列表。  
- POST /tags/catalog/reload —— 热加载 tags_catalog.json（正则与 i18n 一并刷新）。  
- POST /tags/monsters/{id}/suggest —— 仅建议：{role_suggest, tags(code[]), i18n}，不落库。  
- POST /tags/monsters/{id}/retag —— 正则打标签并落库：m.tags = upsert_tags(...); 然后 recompute_and_autolabel。  
- POST /tags/monsters/{id}/retag_ai —— AI 识别标签并落库，同步触发 recompute_and_autolabel。  
- POST /tags/ai/batch —— 同步批量 AI 打标签（可指定 ids；缺省=全量），逐条提交，返回明细≤200。  
- POST /tags/ai_batch/start —— 启动后台批处理，返回 {job_id}。  
- GET /tags/ai_batch/{job_id} —— 查询进度。  
- POST /tags/ai_batch/{job_id}/cancel —— 取消任务。

查询参数/请求体（要点）
- /tags：with_counts?=bool（默认 false）。  
- /tags/catalog/reload：无 Body。  
- /tags/monsters/{id}/suggest|retag|retag_ai：无 Body，仅路径参数 id。  
- /tags/ai/batch：Body {"ids"?: number[]}（缺省或空数组表示全量）。  
- /tags/ai_batch/start：Body {"ids"?: number[]}。  
- /tags/ai_batch/{job_id} 与 /cancel：仅路径参数 job_id。

输入/输出（要点）
- list_tags：当 with_counts=true，排序为 count 降序、同 count 按 code 升序（实现里是 count desc, name asc）。  
- cat_counts：{"summary": {"增强类":n1,"削弱类":n2,"特殊类":n3}, "detail":[{code,category,count}]（按 count desc 排）。  
- suggest：返回当前 role（已落库）与 role_suggest（推断），以及正则建议的标签 codes 与 i18n 映射。  
- retag/retag_ai：返回 {ok, monster_id, role, tags(code[]), i18n}，均在内部完成 upsert_tags 与 recompute_and_autolabel 后 commit。  
- ai/batch：返回 {ok,total,success,failed,details≤200,i18n}，每条 detail 含 {id, ok, role?, tags?|error?}。

依赖与数据流
- 词表与正则：tags_service.load_catalog / get_i18n_map / suggest_tags_for_monster / ai_suggest_tags_for_monster / 批处理接口。  
- 打标签落库：upsert_tags → Monster.tags；随后 derive_service.recompute_and_autolabel 写入 role 与 derived。  
- 推断角色（仅建议）：derive_service.infer_role_for_monster。  
- DB：SessionLocal；读取 Monster 时用 select(Monster).where(Monster.id==...）。

事务与幂等
- retag/retag_ai：单请求单事务；重复对同一实体调用结果稳定（取决于正则/AI输出是否稳定）。  
- ai/batch：对每个 id 独立 try/commit/rollback；成功与失败互不影响；重复调用可能重复计算（无幂等键）。  
- catalog/reload：一次性调用，原子性与并发安全由 tags_service 负责。

错误与可观测性
- 404：monster/job 不存在（suggest/retag/retag_ai/ai_batch 查询）。  
- 500：AI 失败（retag_ai 捕获 RuntimeError → 500）；reload 失败时抛 500。  
- 统计接口未对“无关联标签的计数”为 0 做特别处理（见常见坑 #1）。  
- 无鉴权与限流；AI 类接口可能被滥用。  
- ai/batch 返回明细最多 200 条；大批次需通过进度制接口查看整体状态。

示例（最常用）
- 获取标签代码（含计数）：curl "http://127.0.0.1:8000/tags?with_counts=true"  
- 类别统计：curl "http://127.0.0.1:8000/tags/cat_counts"  
- 取 i18n 映射：curl "http://127.0.0.1:8000/tags/i18n"  
- 输出目录：curl "http://127.0.0.1:8000/tags/schema"  
- 热更新词表：curl -X POST "http://127.0.0.1:8000/tags/catalog/reload"  
- 正则建议：curl -X POST "http://127.0.0.1:8000/tags/monsters/42/suggest"  
- 正则落库：curl -X POST "http://127.0.0.1:8000/tags/monsters/42/retag"  
- AI 落库：curl -X POST "http://127.0.0.1:8000/tags/monsters/42/retag_ai"  
- AI 批量（同步）：curl -X POST -H "Content-Type: application/json" -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/tags/ai/batch  
- AI 批量（后台）：  
  - 启动：curl -X POST -H "Content-Type: application/json" -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/tags/ai_batch/start  
  - 进度：curl "http://127.0.0.1:8000/tags/ai_batch/<job_id>"  
  - 取消：curl -X POST "http://127.0.0.1:8000/tags/ai_batch/<job_id>/cancel"

常见坑（Top 12）
1) with_counts/cat_counts 的计数实现基于 LEFT JOIN + count(*)，对“无关联”的标签可能统计为 1 而非 0；应改为 count(Monster.id)。  
2) Tag.name 是代码（code），需前端用 /tags/i18n 转中文；直接展示会出现英文/下划线。  
3) /suggest 仅建议，不落库；前端若据此展示“已打标签”会引发误解。  
4) /retag_ai 依赖外部/模型资源；没有限流与熔断，容易被滥用或触发配额问题。  
5) /ai/batch 在 ids 为空时会对全表执行，易误触发全库批量；请在前端显式选择目标。  
6) 批量接口逐条 commit/rollback，吞吐与一致性受限；长批次建议用后台流程。  
7) catalog/reload 为全局可见操作，且无鉴权；误操作会影响正在运行的标注行为。  
8) 正则/AI 输出可能包含词表外 code；upsert_tags 会创建新 Tag 记录，导致词表与数据漂移。  
9) infer_role_for_monster 仅用于建议；角色真正写入依赖 recompute_and_autolabel。  
10) i18n 映射缓存策略不明；重载后前端应主动刷新缓存。  
11) 没有审计记录（谁在何时执行了 retag/retag_ai/批量），难以回溯。  
12) 读取 Monster 未做预加载；在批量中可能产生 N+1。

变更指南（How to change safely）
- 修正计数：把 count(*) 改为 count(Monster.id) 或 count(TagMonster.monster_id)。  
- 增加 dry_run：为 /retag /retag_ai 增加 dry_run=true 返回建议而不落库。  
- 增加鉴权与配额：为 /admin 或 /tags 下的写接口加入权限校验与速率限制。  
- 词表一致性：限制 upsert_tags 仅允许词表内 code，或在落库前做白名单过滤。  
- 批处理：/ai/batch 支持 limit/offset、并行度、批次 id 与重试机制；建议统一走后台任务。  
- 可观测性：对正则/AI 成功率、Top 错误原因、耗时、覆盖率等做埋点；后台任务暴露 ETA 与速率。  

术语与约定
- 标签代码（code）：以 buf_/deb_/util_ 为前缀的机器可读标识，Tag.name 持久化此值。  
- i18n：从 tags_catalog.json 派生的 code→中文名映射，用于 UI 显示。  
- 正则打标签：基于词表与正则从怪物字段/技能文本抽取标签。  
- AI 打标签：调用模型/外部服务返回标签候选，内部可能附带审计与自由候选写盘。