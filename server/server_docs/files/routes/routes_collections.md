file: server/app/routes/collections.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, server/app/schemas.py, server/app/services/collection_service.py, server/app/services/derive_service.py]
exposes: [/collections(GET|POST), /collections/{id}(GET|PATCH|DELETE), /collections/bulk_set(POST), /collections/{id}/add(POST), /collections/{id}/remove(POST), /collections/{id}/set(POST), /collections/{id}/members(GET)]

TL;DR（30秒）
- 提供“收藏夹（Collection）”的增删改查、批量成员维护与成员分页查询；含旧接口兼容（add/remove/set）。  
- 名称唯一；创建冲突返回 409。批量接口支持 add/remove/set 与按 name 自动创建。  
- 成员列表附带派生字段（derived），已做 selectinload 预加载以避免 N+1。

职责与边界
- 做什么：收藏夹列表/创建/更新/删除；批量维护成员；查询收藏夹成员（分页、排序、含 derived）；兼容旧端点。
- 不做什么：权限与多租户隔离；复杂搜索（仅 q 简搜）；导入导出（在 backup 路由）；派生值计算的落库（仅读取时计算）。

HTTP 端点
- GET /collections —— 列表与分页，支持 q/排序/计数；返回 {items,total,has_more,etag}。幂等：是。
- POST /collections —— 创建（名称唯一）；返回 CollectionOut；冲突 409。幂等：否（对同名请求会报冲突）。
- PATCH /collections/{id} —— 更新 name/color；返回最新 items_count。幂等：取决于变更内容，重复相同载荷幂等。
- DELETE /collections/{id} —— 删除收藏夹；返回 {ok,id}。幂等：对已删除对象视作 404。
- POST /collections/bulk_set —— 批量成员维护（add/remove/set），支持按 name 自动创建（color_for_new 可选）。幂等：  
  - action=set 为强幂等；add/remove 对重复/不存在会统计 skipped/missing。
- 兼容旧接口：  
  - POST /collections/{id}/add|remove|set —— 仅按 id 操作成员。
- GET /collections/{id} —— 返回收藏夹元信息（含 items_count）。幂等：是。
- GET /collections/{id}/members —— 成员列表（分页/排序），输出 MonsterOut（含 derived）。幂等：是（读取）。

查询参数/请求体（节选）
- GET /collections：q, sort(=updated_at|created_at|name|items_count|last_used_at), order(=asc|desc, 默认 desc), page(>=1), page_size(1..200)。
- POST /collections：{"name": string, "color"?: string}。
- PATCH /collections/{id}：{"name"?: string, "color"?: string}。
- POST /collections/bulk_set：{"collection_id"?: int, "name"?: string, "ids": int[], "action": "add"|"remove"|"set", "color_for_new"?: string}。  
  - 规则：优先使用 collection_id；缺失则按 name get-or-create；ids 去重。
- 旧接口 Body：{"ids": int[]}。
- GET /collections/{id}/members：sort(=id|name|element|role|updated_at|created_at), order(=asc|desc, 默认 asc), page, page_size。

输入/输出（要点）
- CollectionOut：id,name,color,created_at,updated_at,last_used_at,items_count。  
- 列表响应统一：{items: CollectionOut[]|MonsterOut[], total: int, has_more: bool, etag: string}。  
- MonsterOut（成员列表）：基础字段 + tags/explain_json + derived（由 compute_derived_out 计算）。

依赖与数据流
- 上游：HTTP 路由 → service（collection_service）执行业务 → db 提交。  
- 主要调用的 service：list_collections, get_or_create_collection, update_collection, delete_collection, bulk_set_members, list_collection_members, get_collection_by_id。  
- 成员列表派生：compute_derived_out(m) 于返回前计算；为避免 N+1，提前 selectinload(tags, derived, monster_skills.skill)。

事务与幂等
- 提交策略：每个写接口在 service 执行后统一 db.commit()；service 内部需确保原子性。  
- 幂等性：  
  - 创建：非幂等，同名返回 409。  
  - 更新：同一载荷重复调用无额外副作用。  
  - 删除：成功后再次调用返回 404。  
  - bulk_set：  
    - set：目标集合与传入 ids 完全一致（强幂等）。  
    - add/remove：重复 ids 或不存在的 ids 不报错，计入 skipped/missing_monsters，结果稳定。

错误与可观测性
- 400：创建时 name 为空；bulk_set 参数非法（service 抛 ValueError）。  
- 404：目标收藏夹不存在（get/update/delete/members）。  
- 409：创建重名。  
- 422：Pydantic 校验失败（类型/范围）。  
- Trace：继承全局中间件（x-trace-id）；本文件未显式记录日志。

示例（最常用）
- 列表收藏夹：curl "http://127.0.0.1:8000/collections?q=精英&sort=items_count&order=desc&page=1&page_size=20"
- 创建收藏夹：curl -X POST -H "Content-Type: application/json" -d '{"name":"活动队伍","color":"#FFCC00"}' http://127.0.0.1:8000/collections
- 更新颜色：curl -X PATCH -H "Content-Type: application/json" -d '{"color":"#00AAFF"}' http://127.0.0.1:8000/collections/3
- 批量加入（按 id）：curl -X POST -H "Content-Type: application/json" -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/collections/3/add
- 批量覆盖（按 name 自动建）：curl -X POST -H "Content-Type: application/json" -d '{"name":"活动队伍","ids":[5,6,7],"action":"set","color_for_new":"#AAFF00"}' http://127.0.0.1:8000/collections/bulk_set
- 查询成员：curl "http://127.0.0.1:8000/collections/3/members?sort=name&order=asc&page=1&page_size=50"

常见坑（Top 8）
1) 创建时 name 必填且唯一；前端需处理 409，避免重复提交导致的用户困惑。  
2) bulk_set 同时传 collection_id 与 name 时以 collection_id 为准；仅传 name 时可能创建新收藏夹，注意 color_for_new。  
3) add/remove 对重复/不存在的 ids 不报错而计入 skipped/missing_monsters；不要误以为未生效。  
4) members 默认排序 id asc；如需按更新时间，请显式 sort=updated_at&order=desc。  
5) 成员列表 page_size 最大 200；过大可能使派生计算与预加载开销上升。  
6) items_count 通过 count(*) 现查询，非缓存；高频刷新可能造成额外查询压力。  
7) 旧端点不支持按 name 自动创建与 color_for_new；仅操作已有的 collection_id。  
8) 派生 derived 为读取时计算，不代表已持久化；导出请走 /export 或 backup 路由。

变更指南（How to change safely）
- 新增排序字段：在 service 层与查询层同步支持，并更新文档与校验。  
- 扩展成员输出：在 MonsterOut/compute_derived_out 扩展，同时保证 selectinload 预加载完整以避免 N+1。  
- 行为调整（如冲突策略/自动创建）：保持旧端口兼容或提供明确迁移说明；为 bulk_set 增加 dry-run 选项可降低风险。  
- 性能优化：为 CollectionItem.collection_id 建索引；成员列表采用更轻量的 DTO；必要时引入缓存 items_count。

术语与约定
- action 语义：add=追加（去重），remove=移除（忽略不存在），set=覆盖到精确集合。  
- items_count：实时 count，不缓存。  
- ETag：弱校验值（W/），可用于前端轻量缓存与变更检测。