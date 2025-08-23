---
file: server/app/models.py
type: model
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py (Base, PRAGMA foreign_keys=ON)]
exposes: [Monster, MonsterDerived, Tag, Skill, MonsterSkill, Collection, CollectionItem, ImportJob, Task, ensure_collections_tables, monster_tag]

# models.py · 快速卡片

## TL;DR（30 秒）
- 职责：定义全部 ORM 模型与关联（多对多、1:1、关联对象表），并提供收藏夹相关的惰性建表工具。
- 关键关系：
  - Monster↔Tag：多对多（关联表 monster_tag，级联删除）
  - Monster↔Skill：通过关联对象 MonsterSkill（一条关系可带 `selected/level/description`）
  - Monster↔MonsterDerived：1:1 派生五维
  - Collection↔Monster：通过关联对象 CollectionItem（复合主键）
- 常见坑
  1) `monsters.name` 唯一；创建重名会触发 UNIQUE 约束（建议路由层转 409）。
  2) `skills` 唯一约束是组合键：`(name, element, kind, power)`；任何维度不同都视为不同技能。
  3) 删除 Monster/Skill/Collection 时需确认级联与外键开关（SQLite 需 `foreign_keys=ON`，已在 db.py 配置）。

## 表与字段（要点）

### Monster（妖怪主表）
- 主键：`id`
- 唯一：`name`
- 基础：`element?`（"水系"/"火系"/"特殊"...）、`role?`
- 获取/持有：`possess`(bool)、`new_type?`(bool)、`type?`、`method?`
- 六维：`hp/speed/attack/defense/magic/resist`（Float，默认 0.0）
- 附加：`explain_json`(JSON) —— 包含 `raw_stats`、自动标签等
- 时间：`created_at`、`updated_at(onupdate)`
- 关系：
  - `tags`（m2m，经由 monster_tag）
  - `monster_skills`（1:n 到 MonsterSkill，`lazy="selectin"`，含级联删除）
  - `skills`（association_proxy 到 `monster_skills.skill`）
  - `derived`（1:1 到 MonsterDerived）
  - `collection_links`（1:n 到 CollectionItem）
  - `collections`（association_proxy 到 `collection_links.collection`）

### MonsterDerived（派生五维，1:1）
- 主键=外键：`monster_id`
- 五维：`offense/survive/control/tempo/pp_pressure`（int）
- 追踪：`formula/inputs/weights/signals`（JSON/Str）
- 更新时间：`updated_at(onupdate)`
- 关系：`monster`（回指）

### Tag（标签）
- 主键：`id`
- 唯一：`name`
- 关系：`monsters`（经由 monster_tag）

### Skill（技能）
- 主键：`id`
- 组合唯一：`(name, element, kind, power)` → `uq_skill_name_elem_kind_power`
- 主要字段：`name`、`element?`、`kind?`（物理/法术/特殊）、`power?`、`description`
- 关系：
  - `monster_skills`（1:n 到 MonsterSkill）
  - `monsters`（association_proxy 到 `monster_skills.monster`）

### MonsterSkill（关联对象：怪物-技能）
- 主键：`id`
- 外键：`monster_id` → monsters.id（CASCADE），`skill_id` → skills.id（CASCADE）
- 组合唯一：`(monster_id, skill_id)` → `uq_monster_skill_pair`
- 关系级字段：`selected`(bool)、`level?`(int)、`description?`(Text)
- 时间：`created_at/updated_at`

### Collection（收藏夹）
- 主键：`id`
- 唯一：`name`（单用户场景）
- UI：`color?`
- 冗余：`items_count`（需由服务层维护）、`last_used_at?`
- 时间：`created_at/updated_at`
- 关系：`items`（1:n 到 CollectionItem）、`monsters`（association_proxy）

### CollectionItem（关联对象：收藏夹-怪物）
- 复合主键：`(collection_id, monster_id)`
- 外键：分别指向 `collections.id`、`monsters.id`（CASCADE）
- 时间：`created_at`
- 关系：`collection`、`monster`
- 索引：`ix_collection_items_monster_id`（加速按怪物反查）

### ImportJob（导入作业）
- 主键：`id`
- 唯一：`key`（幂等用）
- 状态：`status`（done/processing/failed）
- 结果：`result_json`（JSON）
- 时间：`created_at`

### Task（异步任务）
- 主键：`id`（uuid）
- 类型/状态：`type`、`status`（pending/running/done/failed）
- 进度：`progress/total`
- 结果：`result_json`
- 时间：`created_at`

### 关联表 monster_tag（Monster↔Tag）
- 复合主键：`(monster_id, tag_id)`，双向 CASCADE

## 索引与唯一约束（节选）
- Monster：`UNIQUE(name)`；`INDEX(element)`、`INDEX(role)`、`INDEX(type)`
- Skill：`UNIQUE(name, element, kind, power)`；`INDEX(name)`、`INDEX(name like)`（`ix_skill_name_like`）
- MonsterSkill：`UNIQUE(monster_id, skill_id)`；`INDEX(monster_id)`、`INDEX(skill_id)`
- Tag：`UNIQUE(name)`；`INDEX(name)`
- Collection：`UNIQUE(name)`；`INDEX(name)`
- CollectionItem：`PRIMARY KEY(collection_id, monster_id)`；`INDEX(monster_id)`

## 事务与级联
- 物理删除 Monster/Skill/Collection 时，相关关联对象（MonsterSkill、CollectionItem、monster_tag）将因外键 `ondelete="CASCADE"` 与关系 `cascade="all, delete-orphan"` 一并删除。
- 注意：SQLite 需开启 `PRAGMA foreign_keys=ON`（在 db.py 的连接事件中已启用）。

## association_proxy 使用要点
- `Monster.skills`：读写透传到 MonsterSkill 的 `skill`；新增技能时请走服务层以应用“规范化/去重”逻辑。
- `Skill.monsters`、`Monster.collections`、`Collection.monsters` 同理，用于便捷读取；写入仍建议通过服务层以维护冗余计数、唯一性与业务校验。

## 错误与常见报错
- 重名创建 Monster → `sqlite3.IntegrityError: UNIQUE constraint failed: monsters.name`
- 重复绑定同一技能到同一怪 → `UNIQUE constraint failed: monster_skills.monster_id, monster_skills.skill_id`
- 新建 Skill 组合键冲突 → `UNIQUE constraint failed: uq_skill_name_elem_kind_power`
- 外键删除约束 → `sqlite3.IntegrityError: FOREIGN KEY constraint failed`

## 性能与加载策略
- 关系默认 `lazy="selectin"`（Monster.monster_skills 等），减少 N+1 查询；如需联表过滤可在查询中使用 `selectinload/joinedload` 精调。
- 热路径查询建议对 `monsters(name, element, role, type)` 与 `skills(name)` 合理利用索引。
- 大批量写入建议分批事务，避免长事务阻塞。

## 示例（最常用 3 例）
- 查询带标签与精选技能的怪：
  - ORM：按名称模糊 + 预加载 `monster_skills.skill` + 过滤 `MonsterSkill.selected==True`
- 将某怪加入收藏夹：
  - 流程：确保 `Collection` 存在 → 插入 `CollectionItem(collection_id, monster_id)` → 可在服务层维护 `items_count` 与 `last_used_at`
- 读取某技能在哪些怪身上出现：
  - 通过 `skill.monsters`（association_proxy）直接拿到 Monster 列表

## 变更指南（How to change safely）
- 增字段：为对应 ORM 模型添加列并给出默认值；SQLite 生产环境建议通过迁移（Alembic）管理，避免仅靠 `create_all`。
- 调整唯一键/索引：需评估现有数据是否冲突，并在迁移脚本中完成数据清洗与索引重建。
- 修改关系：
  - 由 m2m 改为关联对象（或反之）会影响 API 与服务层逻辑（技能就是使用关联对象存储关系级属性的示例）。
- 收藏夹多租户化：
  - 将 Collection 唯一键从 `name` 改为 `(user_id, name)`；CollectionItem 外键链路随之调整。
- 计数字段一致性：
  - `items_count` 为冗余字段；新增/删除 `CollectionItem` 时由服务层事务内同步维护（或改为触发器/视图）。

## 自测清单
- [ ] 创建 Monster/Tag 并通过 `monster.tags.append(tag)` 绑定，删除 Monster 后 `monster_tag` 行应消失。
- [ ] 同一 Monster 重复绑定相同 Skill 会失败（命中 `uq_monster_skill_pair`）。
- [ ] Skill 唯一组合键生效：仅 `power` 不同即视为不同技能。
- [ ] `Monster.derived` 创建/更新可写入并在更新时刷新 `updated_at`。
- [ ] 收藏夹：创建 `Collection` 与 `CollectionItem` 后，通过 `collection.monsters` 和 `monster.collections` 可互查；重复插入同一 `(collection_id, monster_id)` 被主键拦截。

## 工具与辅助
- 惰性建表：`ensure_collections_tables(bind)` 仅为 `Collection` / `CollectionItem` 两表执行 `create_all`（幂等），便于按需开启收藏能力。