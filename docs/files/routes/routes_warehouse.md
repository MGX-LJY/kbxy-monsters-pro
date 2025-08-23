file: server/app/routes/warehouse.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, server/app/schemas.py, server/app/services/warehouse_service.py, server/app/services/derive_service.py]
exposes: [/warehouse(GET), /warehouse/add(POST), /warehouse/remove(POST), /warehouse/bulk_set(POST), /warehouse/stats(GET)]

TL;DR（30秒）
- “仓库/拥有”功能：按是否拥有（possess）与多条件筛选列出怪物；支持按收藏分组过滤与多标签 AND；支持批量设置拥有态；返回派生五维快照（计算自 `compute_derived_out`）。
- 优先走 `warehouse_service`；若服务层落后则本路由内有完整回退实现（含 `collection_id`/`raw_sum` 排序等）。

职责与边界
- 做什么：拥有清单查询（过滤/排序/分页）、拥有状态增删（单个/批量）、总体统计；列表返回派生五维（只计算、不必然落库）。  
- 不做什么：派生/标签的持久化更新、鉴权和审计、复杂 OR 标签过滤（仅 AND 与单标签）、导出。

HTTP 端点
- GET /warehouse —— 列表与筛选。返回 `MonsterList`：{items,total,has_more,etag}。  
- POST /warehouse/add —— Body {id}，把该怪标记为已拥有。  
- POST /warehouse/remove —— Body {id}，把该怪标记为未拥有。  
- POST /warehouse/bulk_set —— Body {ids: number[], possess: boolean}，批量设置拥有态。  
- GET /warehouse/stats —— 返回仓库统计（服务层定义，通常含 {total, owned_total, not_owned_total, in_warehouse}）。

查询参数/请求体（要点）
- /warehouse  
  - possess: true|false|null（默认 true）。false 视为“未拥有或未知”。  
  - q, element, role  
  - tag（单标签）  
  - tags_all[]=code…（多标签 AND）  
  - acq_type / type（获取途径，包含匹配）  
  - collection_id: number（收藏分组过滤）  
  - sort: updated_at | raw_sum | hp|speed|attack|defense|magic|resist|name|created_at|updated_at  
  - order: asc|desc（默认 desc）  
  - page(≥1), page_size(1~200)  
- /warehouse/add|remove —— Body: {"id": number}  
- /warehouse/bulk_set —— Body: {"ids": number[], "possess": boolean}

输入/输出（要点）
- 列表项 `MonsterOut` 包含六维、拥有态、获取途径、标签、explain_json 以及 `derived`（由 `compute_derived_out(m)` 现算）。  
- ETag 形如 `W/"warehouse:{total}:{possess}:{collection_id}"`（仅纳入少量参数）。

依赖与数据流
- 首选调用 `warehouse_service.list_warehouse/warehouse_stats/...`；若签名不兼容（抛 `TypeError`），使用路由内回退查询：  
  - `possess` → 过滤 `Monster.possess is True/False or None`  
  - `collection_id` → JOIN `CollectionItem` 去重  
  - 标签 → `tags_all` 连续 `.any(Tag.name==code)`；单 `tag` 等价 AND=1  
  - 获取途径 → `Monster.type ILIKE %...%`  
  - 排序 → 指定列或 `raw_sum`；分页 → offset/limit  
- 为避免 N+1，对列表结果用 `selectinload` 预加载 `tags/derived/monster_skills.skill`；派生值用 `compute_derived_out` 现算填充。

事务与幂等
- GET /warehouse 与 /warehouse/stats：只读。  
- /warehouse/add|remove|bulk_set：单次提交；幂等取决于服务层实现（重复设置同一状态应不改变计数）。  

错误与可观测性
- /warehouse/add|remove：目标不存在 → 404。  
- 其它异常直接 500；无日志与指标。  
- ETag 未包含所有筛选参数（仅含 total/possess/collection_id），作为缓存键可能过宽。

示例（最常用）
- 已拥有，按更新时间倒序：  
  curl "http://127.0.0.1:8000/warehouse?possess=true&sort=updated_at&order=desc&page=1&page_size=20"
- 未拥有，按原始总和升序并筛标签：  
  curl "http://127.0.0.1:8000/warehouse?possess=false&tags_all=buf_speed&tags_all=util_shield&sort=raw_sum&order=asc"
- 筛某收藏分组：  
  curl "http://127.0.0.1:8000/warehouse?collection_id=3"
- 批量设为已拥有：  
  curl -X POST -H "Content-Type: application/json" -d '{"ids":[10,11,12],"possess":true}' http://127.0.0.1:8000/warehouse/bulk_set
- 单个加入/移出：  
  curl -X POST -H "Content-Type: application/json" -d '{"id":42}' http://127.0.0.1:8000/warehouse/add  
  curl -X POST -H "Content-Type: application/json" -d '{"id":42}' http://127.0.0.1:8000/warehouse/remove

常见坑（Top 12）
1) **raw_sum 排序实现**：回退实现里用 `(Monster.hp or 0)` 等 Python `or` 组合，在 SQLAlchemy 中会报“Boolean value of this clause is not defined”；应改为 `func.coalesce(Monster.hp, 0)` 逐项相加。  
2) ETag 过于粗粒度，忽略了 q/element/role/tag/tags_all/type 等筛选；做缓存需谨慎。  
3) `possess=false` 将 `None` 也计入“未拥有”，如需严格 false 请另加参数。  
4) 标签仅支持 AND（`tags_all`）与单标签；无 OR（`tags_any`）。  
5) 现算派生未落库；若前端依赖数据库中的 derived，会看到与接口输出不一致。  
6) 与 monsters 列表语义差异：monsters.py 在缺失时会自动 recompute & persist，这里不会。  
7) `type` 参数名与 Python 内置同名；虽不影响运行，但建议统一为 `acq_type`。  
8) 大分页/多 JOIN 时计数与排序性能依赖索引（`monsters(possess)`, `monsters(type)`, `tags.name` 关联等）。  
9) `collection_id` 过滤使用 `DISTINCT(Monster.id)`，仍可能受 ORM 生成 SQL 差异导致性能问题。  
10) 未做输入长度限制（q）与字段归一化（trim/全角空格），可能影响命中率与执行计划。  
11) 写接口无鉴权与审计；容易被误操作。  
12) 批量设置未返回逐条失败明细；ids 中缺失或无效项由服务层处理，调用方需自行校验。

变更指南（How to change safely）
- 修复 raw_sum：`raw_sum = sum(func.coalesce(getattr(Monster,f),0) for f in ["hp","speed","attack","defense","magic","resist"])`。  
- 对齐派生策略：列表输出后若检测 derived 旧值可选择 `compute_and_persist` 批量落库（注意性能）。  
- 扩展筛选：支持 `tags_any`、`new_type` 等与 monsters 列表保持一致；统一参数名 `acq_type`。  
- 缓存与观测：完善 ETag/Cache-Control、埋点总量/筛选命中/耗时；对常用查询加索引或物化视图。  
- 安全：为写接口加鉴权/审计；为全量批量操作加入确认/限流。  

术语与约定
- possess：拥有态（true=已拥有，false/none=未拥有）。  
- raw_sum：六维列的和，用于粗排序。  
- collection_id：收藏分组过滤，用中间表 `CollectionItem` 连接。