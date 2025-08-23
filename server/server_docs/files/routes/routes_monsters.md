file: server/app/routes/monsters.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, server/app/schemas.py, server/app/services/monsters_service.py, server/app/services/skills_service.py, server/app/services/derive_service.py]
exposes: [/monsters(GET|POST), /monsters/{id}(GET|PUT|DELETE), /monsters/{id}/skills(GET|PUT), /monsters/{id}/raw_stats(PUT), /monsters/{id}/derived(GET), /monsters/auto_match(POST)]

TL;DR（30秒）
- “怪物”主路由：列表检索/详情/创建/更新/删除，技能读写，原始六维写入，派生与自动贴标。
- 列表支持多种标签筛选（单标签、AND/OR、多分组）、获取途径、是否可获取、按收藏夹分组、修复筛查等。
- 所有读取路径会在必要时自动补齐 role/tags/derived 并与 compute_derived_out 对齐（可能触发写入）。

职责与边界
- 做什么：提供 Monster CRUD 与围绕 Monster 的常用操作（技能集合维护、raw_stats 保存、派生建议、自动匹配贴标）。
- 不做什么：权限/多租户隔离；长任务/批次一致性；导入导出（由 importing/backup 提供）。

HTTP 端点
- GET /monsters —— 列表（分页/排序/筛选），必要时自动补齐 role/tags/derived 并对齐派生，返回 MonsterList。幂等：读取但可能写入（对齐派生）。
- GET /monsters/{id} —— 详情，自动补齐并对齐派生后返回 MonsterOut。幂等：读取但可能写入。
- GET /monsters/{id}/skills —— 仅返回当前关联技能清单（关联描述优先，其次全局描述）。幂等：是（读取）。
- PUT /monsters/{id}/skills —— 覆盖设置技能集合（全局 upsert + 维护 MonsterSkill，支持 selected/关联级描述），自动贴标并重算派生。幂等：对相同载荷幂等。
- PUT /monsters/{id}/raw_stats —— 写入原始六维与 explain_json.raw_stats，并重算派生。幂等：对相同载荷幂等。
- GET /monsters/{id}/derived —— 计算并返回 role_suggested、tags、derived（通过 recompute_and_autolabel 落库）。幂等：读取但有写入副作用。
- POST /monsters/auto_match —— 批量对指定 ids 执行自动贴标+定位+派生。幂等：对同一集合重复调用结果稳定。
- POST /monsters —— 创建 Monster，可同时写标签与技能（关联级 selected/描述），随后自动贴标并重算派生。幂等：否（名称唯一冲突将抛错）。
- PUT /monsters/{id} —— 更新 Monster（显式包含 skills 时才同步技能集合），随后自动贴标并重算派生。幂等：对相同载荷幂等。
- DELETE /monsters/{id} —— 删除 Monster（显式清理关联后删除）。幂等：对已删对象返回 404。

查询参数/请求体（节选）
- 列表筛选：q, element, role, tag（旧）, tags_all[], tags_any[], tag_mode=and|or, buf_tags_all|any[], deb_tags_all|any[], util_tags_all|any[], tags[]（与 tag_mode 配合）。
- 获取途径：acq_type 或 type（包含匹配），new_type=true|false。
- 收藏过滤：collection_id（按收藏夹成员过滤）。
- 质量筛查：need_fix=true（技能名非空的技能数量为 0 或 >5）。
- 分页/排序：sort（默认 updated_at），order=asc|desc，page>=1，page_size<=200。
- 技能写接口载荷项：name, element?, kind?, power?, description?, selected?。

输入/输出（要点）
- MonsterOut：基础字段 + tags（名称数组）+ explain_json（含 raw_stats/skill_names 可选）+ 派生五维。
- 列表返回：{items, total, has_more, etag}，etag 形如 W/"monsters:{total}"。
- 技能唯一/去重：通过 services.skills_service.upsert_skills，全局去重（入参为(name,element,kind,power,description)，具体唯一策略以 service 为准）；MonsterSkill 维护 selected 与关联级描述。

依赖与数据流
- 首选调用 services.monsters_service.list_monsters；若签名不兼容则回退本地实现（含标签/收藏/获取途径/new_type/need_fix 过滤）。
- 预加载：selectinload(monster_skills.skill, tags, derived) 以避免 N+1。
- 对齐派生路径：compute_derived_out → 如不一致则 compute_and_persist；缺 role/tags/derived 时 recompute_and_autolabel。

事务与幂等
- 列表/详情可能在读取时触发写入（补齐 role/tags/derived 或对齐派生），本路由在列表中统一延迟一次 commit，详情在需要时 commit。
- 写操作（技能、raw_stats、创建、更新、删除）在函数末尾 commit；技能与标签修改后统一通过 recompute_and_autolabel 保障一致。
- 幂等性：技能 PUT、raw_stats PUT、更新 PUT 对相同载荷幂等；创建非幂等；读取端点结果幂等但有写副作用。

错误与可观测性
- 404：目标 Monster 不存在（详情/技能读写/删除等）。
- 400/422：参数校验失败（由 FastAPI/Pydantic 提供）。
- 名称唯一冲突：创建/更新未捕获 IntegrityError 将冒泡为 500（建议转 409，见“常见坑”）。
- 列表对齐派生可能引入写入失败从而 500；当前未细化捕获。
- 依赖全局 trace（x-trace-id）；本路由未加专门日志。

示例（最常用）
- 列表（多标签 AND + 收藏分组）：curl "http://127.0.0.1:8000/monsters?tags_all=buf_x&tags_all=deb_y&collection_id=3&sort=updated_at&order=desc&page=1&page_size=20"
- 列表（OR + 获取途径模糊）：curl "http://127.0.0.1:8000/monsters?tags_any=util_speed&tags_any=util_hit&acq_type=活动"
- 详情：curl "http://127.0.0.1:8000/monsters/42"
- 读取技能：curl "http://127.0.0.1:8000/monsters/42/skills"
- 覆盖技能：curl -X PUT -H "Content-Type: application/json" -d '[{"name":"青龙搅海","element":"水系","kind":"法术","power":135,"description":"...","selected":true}]' http://127.0.0.1:8000/monsters/42/skills
- 写原始六维：curl -X PUT -H "Content-Type: application/json" -d '{"hp":98,"speed":96,"attack":87,"defense":81,"magic":113,"resist":85}' http://127.0.0.1:8000/monsters/42/raw_stats
- 创建：curl -X POST -H "Content-Type: application/json" -d '{"name":"碧青水龙兽","element":"水系","hp":98,"speed":96,"attack":87,"defense":81,"magic":113,"resist":85,"tags":["buf_x"],"skills":[{"name":"明王咒","kind":"特殊"}]}' http://127.0.0.1:8000/monsters
- 更新（不改技能）：curl -X PUT -H "Content-Type: application/json" -d '{"name":"碧青水龙兽X","tags":["buf_x","util_speed"]}' http://127.0.0.1:8000/monsters/42
- 删除：curl -X DELETE http://127.0.0.1:8000/monsters/42
- 批量自动匹配：curl -X POST -H "Content-Type: application/json" -d '{"ids":[1,2,3]}' http://127.0.0.1:8000/monsters/auto_match

常见坑（Top 12）
1) 列表/详情在“读取时修正”派生，可能导致高频查询产生写负载与锁竞争；建议前端缓存或增加只读视图。  
2) 名称唯一冲突在 create/update 未转换为 409；数据库将抛 IntegrityError → 500。  
3) need_fix 统计依赖 Skill.name 非空；来源数据质量差时可能误判。  
4) 列表回退本地实现时，对派生字段的排序与服务层实现可能不完全一致。  
5) 获取途径过滤使用 ilike "%{acq}%"; 文本不规范会漏匹配或过匹配。  
6) tags 参数混用（tag/tags_all/tags_any/tags/tag_mode）可能造成意外逻辑；前端应固定一种风格。  
7) /{id}/skills PUT 为“覆盖”语义；未在载荷中的旧技能会被移除。  
8) 关联级描述仅在提供时覆盖；未提供时保留旧描述，可能导致描述与 UI 不一致。  
9) raw_stats 写入将重算派生；若派生算法改变会导致历史对齐变化。  
10) collection_id 过滤通过 JOIN + DISTINCT；在大库下可能带来额外开销。  
11) 读取端点可能 commit；异常处理不当会让读请求失败并中断事务。  
12) explain_json.skill_names 由当前关联推导；与导入/备份的技能名来源可能不一致。

变更指南（How to change safely）
- 提供只读视图：新增 /monsters/view 与 /monsters/{id}/view，禁止写副作用，用于监控/缓存。  
- 将名称唯一冲突转 409：在 create/update 捕获 IntegrityError 并返回 409。  
- 统一技能唯一策略：与 skills_service/backup 路由对齐（4 元组或 5 元组），并编写迁移去重。  
- 强化列表性能：将对齐派生移至异步任务或定时批；列表仅读取 cached derived。  
- 明确标签接口：弃用 tag，统一使用 tags_all/tags_any 或分组参数。  
- 为 need_fix 增加更多条件（如过滤“推荐配招”等噪声技能）并在服务层实现可复用逻辑。  
- 增加可观测性：对自动补齐/对齐派生的触发次数与耗时打点；对错误集中来源做日志聚合。

术语与约定
- raw_stats：六维原始值与 sum，存于 explain_json.raw_stats。  
- 自动贴标：根据规则对 Monster 合并标签并建议/写入 role。  
- 派生五维：offense/survive/control/tempo/pp_pressure；compute_and_persist 将持久化到 MonsterDerived。