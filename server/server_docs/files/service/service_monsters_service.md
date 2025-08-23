---
file: server/app/services/monsters_service.py
type: service
owner: backend
updated: 2025-08-23
stability: beta
deps: [SQLAlchemy Session/select/func/asc/desc/outerjoin/case/distinct/or_, server/app/models.{Monster,Tag,MonsterDerived,MonsterSkill,Skill}]
exposes: [_get_sort_target, list_monsters, upsert_tags, set_tags_and_rederive, auto_match_monsters]

# monsters_service.py · 快速卡片

## TL;DR（30 秒）
- 职责：提供**怪物列表查询**（筛选/排序/分页）、**标签 upsert**、**设置标签并重算派生**、**批量自动匹配标签**等通用服务。
- 亮点：  
  - 列表排序同时支持**派生五维**（需 JOIN）与**原始六维/六维总和**（无需 JOIN）。  
  - 标签筛选支持**单标签**与**多标签**（AND/OR 组合）。  
  - 可按**获取途径**（`type` 包含匹配）与**当前可获取**（`new_type` 布尔）过滤。  
  - “需修复”筛选：技能名非空的技能数为 0 或 >5。

## 排序字段解析 · `_get_sort_target(sort)`
- 输入：`sort` 字符串（不区分大小写），返回 `(sort_column_expr, need_join_monster_derived)`.
- 支持：
  - **派生**：`offense/survive/control/tempo/pp_pressure`（别名：`pp`）→ 需 `outerjoin(MonsterDerived)`。
  - **原始六维**：`hp/speed/attack/defense/magic/resist` → 直接在 `Monster` 表排序。
  - **六维总和**：`raw_sum/sum/stats_sum` → `coalesce(hp,...)+...` 表达式。
  - 其它：`name/element/role/created_at/updated_at`。
- 用法：列表查询根据该返回值决定是否补 `MonsterDerived` 的 OUTER JOIN，并在最终 `order_by` 增加 `Monster.id` 作为稳定性次序键。

## 多标签筛选（AND/OR）
- `_subq_ids_for_multi_tags(tags_all, tags_any)` 生成仅含 `Monster.id` 的子查询：  
  - AND：必须**同时包含** `tags_all` 的所有标签（基于 `HAVING COUNT(DISTINCT CASE ...) == len(tags_all)`）。  
  - OR ：至少包含 `tags_any` 任一标签（`HAVING COUNT(DISTINCT CASE ...) >= 1`）。  
  - 两者同时给出时，需**同时满足** AND 与 OR。  
  - 若 `tags_all/any` 有值，则忽略旧参数 `tag`（单标签）。

## “需修复”子查询
- `_subq_skill_count_nonempty()` 统计每个怪物**技能名非空**的技能数量（JOIN `MonsterSkill` → `Skill` 并排除空白名），用于 `need_fix=True` 时筛出 `cnt IS NULL OR cnt=0 OR cnt>5`。

## 列表查询 · `list_monsters(...) -> (items, total)`
- 过滤参数：
  - `q`: 名称模糊（`Monster.name ILIKE %q%`）。
  - `element`, `role`: 等值。
  - `acq_type` / `type_`: 获取途径，**包含匹配**，作用于 `Monster.type`。
  - `new_type`: 布尔，可用于“当前可获取”筛选。
  - `tag`: 单标签；若 `tags_all/any` 存在则忽略。
  - `tags_all`, `tags_any`: 多标签 AND/OR（见上）。
  - `need_fix`: True 时套用技能计数子查询条件。
- 排序/分页：
  - `sort`: 见 `_get_sort_target`；`order`: `asc|desc`（默认 `desc`）。  
  - 二级排序：总是追加 `asc(Monster.id)` 以稳定结果。  
  - `page` 从 1 起；`page_size`（1~200）。
- 计数与取数：
  - **先构建最小 SELECT `Monster.id` 的计数子查询**，必要时仅为排序引入 `MonsterDerived` 的 OUTER JOIN；再 `COUNT(*)`。  
  - 之后按同等过滤条件构建取数语句，若排序需要派生则补 OUTER JOIN；最终 `.order_by(...).offset(...).limit(...)`。
- 去重：`.unique().all()` 以避免 JOIN 导致的重复实体。
- 返回：`(List[Monster], total:int)`。

## 标签 upsert · `upsert_tags(db, names) -> List[Tag]`
- 作用：将字符串标签写入 `Tag` 表，返回对应 `Tag` 实体（保持传入顺序的去重）。  
- 要求：调用方应保证传入的是**规范化标签**（新三类前缀 `buf_/deb_/util_`）。  
- 注意：每个新标签 `flush()` 一次以拿到 ID；大批量场景可考虑批量插入优化。

## 设置标签并重算 · `set_tags_and_rederive(db, monster, names, commit=True)`
- 步骤：`upsert_tags` → `derive_service.recompute_and_autolabel`。  
- 副作用：会更新 `monster.tags`、写入/更新 `MonsterDerived`，并回写 `monster.role`。  
- 事务：默认 `commit=True`，可在上层批量处理时设为 `False` 后自行提交。

## 批量自动匹配 · `auto_match_monsters(db, ids=None) -> dict`
- 对指定 `ids`（为空则全库）执行：`tags_service.suggest_tags_for_monster` → `set_tags_and_rederive(commit=False)`。  
- 遇错对单个条目 `rollback()` 并记录；最后统一 `commit()`。  
- 返回统计：`total/success/failed` 与前 200 条 `details`。

## 使用示例
- 基本列表：
  ```
  items, total = list_monsters(db, q="龙", element="水系", sort="offense", order="desc", page=1, page_size=20)
  ```
- 多标签（AND+OR）：
  ```
  items, total = list_monsters(db, tags_all=["buf_crit_up","deb_def_down"], tags_any=["util_first","util_multi"])
  ```
- 获取途径 + 当前可获取：
  ```
  items, total = list_monsters(db, acq_type="活动", new_type=True, sort="tempo")
  ```
- 设置标签并重算：
  ```
  set_tags_and_rederive(db, monster, ["buf_shield","deb_spd_down"])
  ```
- 批量自动匹配：
  ```
  res = auto_match_monsters(db, ids=[1,2,3])
  ```

## 常见坑与建议
- `acq_type/type_` 是作用于 `Monster.type` 的**包含匹配**（ILIKE），请保证该字段已由爬虫/导入规范化；否则筛选会较松散。  
- 标签筛选在 SQL 层通过 `HAVING COUNT(DISTINCT CASE ...)` 实现，**频繁使用时应关注索引**：  
  - 关联表 `monster_tag`（由 ORM 的关系表创建）建议有 `(monster_id)`, `(tag_id)`, 以及联合索引 `(tag_id, monster_id)`。  
- 派生排序需要 OUTER JOIN `MonsterDerived`，大量分页时要注意执行计划和覆盖索引；如需极致性能可考虑将派生五维冗余到 `Monster`。  
- `need_fix=True` 的判断依赖 `Skill.name` 非空，若存在“描述在 `MonsterSkill` 上而 `Skill.name` 为空”的历史数据，会被当作需修复。  
- `q` 仅匹配 `Monster.name`；如果需要“按技能名搜索怪物”，应在路由/服务层新增 JOIN `Skill` 的路径并加去重。  
- `upsert_tags` 假定 `Tag.name` 唯一；若迁移到其他 DB（如 PG），请同步唯一索引并处理并发冲突。

## 自测清单
- [ ] 派生排序（例：`sort=pp_pressure`）能正确返回，且总数计算不受 JOIN 影响。  
- [ ] 多标签 AND/OR 组合在边界（空、重复、大小写）下结果正确。  
- [ ] “需修复”能筛出技能名数为 0 或 >5 的怪物。  
- [ ] `set_tags_and_rederive` 能同步更新 `monster.role` 与 `MonsterDerived`。  
- [ ] `auto_match_monsters` 对不存在的 ID 返回 `ok=False, error="monster not found"`，整体流程不被单条失败阻断。