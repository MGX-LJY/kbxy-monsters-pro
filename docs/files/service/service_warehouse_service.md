file: server/app/services/warehouse_service.py
type: service
owner: backend
updated: 2025-08-23
stability: stable
deps: [sqlalchemy.orm.Session, sqlalchemy.select/func/asc/desc/or_, selectinload, models.{Monster, MonsterSkill, Skill, Tag, MonsterDerived}, derive_service.{compute_derived_out, compute_and_persist}]
exposes: [add_to_warehouse, remove_from_warehouse, bulk_set_warehouse, warehouse_stats, list_warehouse]

TL;DR（30秒）
- “仓库/拥有”能力：用 Monster.possess 记录是否已拥有。
- 提供单个增删、批量设置、统计概览、列表查询（多条件过滤 + 多维排序 + 分页）。
- 列表返回时会自动校准派生五维（如变化则落库），确保后续视图一致。

功能职责
1) 拥有状态维护  
   - add_to_warehouse(db, monster_id) → True/False：将 possess 置 True（不存在返回 False）。  
   - remove_from_warehouse(db, monster_id) → True/False：将 possess 置 False。  
   - bulk_set_warehouse(db, ids, possess) → int：批量设置，返回实际变更数量。  
2) 概览统计  
   - warehouse_stats(db) → {total, owned_total, not_owned_total, in_warehouse}。  
3) 列表查询（核心）  
   - list_warehouse(...) → (items: List[Monster], total: int)  
     过滤：拥有状态/关键词/元素/定位/标签/获取渠道；  
     排序：派生五维、原始六维、六维总和或基础元字段；  
     分页 + 关系预加载；返回后自动校验并持久化派生值。

list_warehouse 参数与行为
- possess: Optional[bool] = True  
  True=仅已拥有；False=仅未拥有（False 或 NULL）；None=不过滤。  
- q: str | None  按 name ILIKE 模糊。  
- element / role: 精确等值。  
- tag: 单标签过滤（等于 Tag.name）。  
- tags_all: Iterable[str] 多标签 AND；对每个标签添加 .tags.any(Tag.name == t)。  
- type / acq_type: 获取渠道（Monster.type）包含匹配 ILIKE，两个参数等价，择其一或都给。  
- sort / order:  
  • 派生五维：offense/survive/control/tempo/pp 或 pp_pressure（需要 OUTER JOIN MonsterDerived）  
  • 原生六维：hp/speed/attack/defense/magic/resist（无需 JOIN）  
  • 六维总和：raw_sum（hp+speed+attack+defense+magic+resist）  
  • 基础列：updated_at/created_at/name/element/role（默认 updated_at desc）  
- page / page_size: 页码与每页条数（page_size 上限 200）。  
- 计数：对已构造的 SELECT 生成子查询再 count()，避免 JOIN 重复导致的误计。  
- 预加载：tags、derived、monster_skills.skill 采用 selectinload。  
- 派生校准：对返回 items 逐个 compute_derived_out；若与 m.derived 不一致则 compute_and_persist 并 flush（不影响本次排序结果，因排序已由 SQL 完成）。

返回结构
- items: List[Monster]（已带 tags/derived/monster_skills.skill 预加载；可能被本次校准更新 derived* 值）  
- total: int（过滤后的总数）

幂等与副作用
- add/remove：仅在状态发生变化时写库（flush）。  
- bulk_set_warehouse：去重 ids，逐个比对差异，批量 flush 一次。  
- list_warehouse：可能写库（当发现派生值需要更新时）。如果不希望在读路径落库，可去掉该段或改为开关控制。

性能与索引建议
- 频繁过滤/排序字段建议建立索引：Monster.possess、Monster.type（LIKE 查询可搭配前缀规范化）、已存在的 name/element/role 索引可复用。  
- 派生排序使用 OUTER JOIN MonsterDerived；如列表页占比高，可在写入流程保证 derived 同步，减少二次校准触发。  
- tags_all 采用多次 .any()，标签多时可考虑改用中间表分组聚合方案（见 monsters_service._subq_ids_for_multi_tags 的思路）。

典型调用
- 加入/移出：add_to_warehouse(db, 123) / remove_from_warehouse(db, 123)  
- 批量设置：bulk_set_warehouse(db, [1,2,3], possess=True)  
- 统计：warehouse_stats(db)  
- 列表：  
  items, total = list_warehouse(  
    db, possess=True, q="龙", element="火系", tags_all=["buf_immunity","deb_stun"],  
    acq_type="活动", sort="offense", order="desc", page=1, page_size=20  
  )

边界与注意
- ids 为空的 bulk_set_warehouse 返回 0；不存在的 monster 会被跳过。  
- type/acq_type 以包含匹配 ILIKE 进行过滤；空白字符串不生效。  
- tag 与 tags_all 同时给时都会生效（tag 作为额外 AND 条件）。  
- list_warehouse 的派生校准需要 derive_service，若移除请同步更新排序/展示依赖。