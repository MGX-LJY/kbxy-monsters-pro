---
file: server/app/services/collection_service.py
type: service
owner: backend
updated: 2025-08-23
stability: stable
deps: [SQLAlchemy ORM, server/app/models.py (Monster, Collection, CollectionItem)]
exposes: [get_collection_by_id, get_collection_by_name, get_or_create_collection, update_collection, delete_collection, list_collections, bulk_set_members, list_collection_members]

# collection_service.py · 快速卡片

## TL;DR（30 秒）
- 职责：收藏夹的**查询/创建/更新/删除**与**成员批量维护**（add/remove/set），以及**分页列出成员**。
- 事务：函数内部只 `flush()`，**不 `commit()`**；交由路由层的请求生命周期统一提交/回滚。
- 幂等与健壮性：`bulk_set_members` 对重复添加/移除做去重；捕获 `IntegrityError` 时进行一次**安全重试**。
- 计数：列表接口通过子查询实时统计 `items_count`，并写入返回对象（可被持久化，但不强制提交）。

## 职责与边界
- 做什么：操作 `Collection` / `CollectionItem` 以及与 `Monster` 的关联；提供分页/排序/搜索。
- 不做什么：不负责权限/多租户，不做输入校验（由路由/Schema 层保证），不维护审计日志。

## 公开函数（函数表）
| 名称 | 签名(简) | 作用 | 读/写 | 备注 |
|---|---|---|---|---|
| get_collection_by_id | (db, collection_id) -> Optional[Collection] | 按 ID 查 | 读 | - |
| get_collection_by_name | (db, name) -> Optional[Collection] | 按名查 | 读 | 名称唯一 |
| get_or_create_collection | (db, \*, name, color?) -> (Collection, created: bool) | 获取或按名新建 | 写 | 惰性创建 |
| update_collection | (db, \*, collection_id, name?, color?) -> Optional[Collection] | 改名/改色 | 写 | 可能触发 UNIQUE |
| delete_collection | (db, collection_id) -> bool | 删除收藏夹 | 写 | 关联 `delete-orphan` 级联清理 |
| list_collections | (db, \*, q?, sort?, order?, page, page_size) -> (List[Collection], total:int) | 列表/搜索/排序 | 读 | `items_count` 由子查询计算 |
| bulk_set_members | (db, \*, collection_id?, name?, ids, action, color_for_new?) -> Dict | 批量 add/remove/set | 写 | 自动创建/跳过不存在/返回缺失清单 |
| list_collection_members | (db, \*, collection_id, page, page_size, sort?, order?) -> (List[Monster], total:int) | 列出某收藏夹的怪物 | 读 | 预加载 tags/derived/skills |

## 数据流与事务
- 输入：Session（请求级）、筛选/排序参数、成员 ID 列表、操作类型。
- 输出：ORM 对象或结果 dict（`added/removed/skipped/missing_monsters/collection_id`）。
- 事务：所有写操作仅 `flush()`；**调用方应在 try/except 中 `commit()`，异常时 `rollback()`**。

## 核心实现要点
- 排序器 `_direction(order)`：默认 `asc`，`"desc"`（不区分大小写）取降序。
- ID 去重 `_uniq_int_ids(ids)`：接受 `Iterable[int|str]`，过滤非数字、去重并转 `int`。
- `list_collections`：
  - 使用 `CollectionItem` 的 `COUNT(*)` 子查询统计成员数，外连接到主查询；
  - **修正总数**：对仅含过滤条件的 `id` 子查询再做 `COUNT(*)`，避免 Join 导致的重复计数；
  - 支持排序字段：`updated_at/created_at/name/items_count/last_used_at`（次排序 `id ASC`）。
- `bulk_set_members`：
  - 支持 `collection_id` 或 `name`（缺 ID 时按名**惰性创建**，可带 `color_for_new`）；
  - `action="add"`：仅插入缺失的 `(collection_id, monster_id)`；
  - `action="remove"`：仅删除已存在的成员；
  - `action="set"`：差异化覆盖（新增缺失 + 删除多余）；
  - 过滤无效怪物 ID，返回 `missing_monsters`；
  - 更新 `last_used_at = utcnow()`；
  - `flush()` 捕获 `IntegrityError`→`rollback()`→进行一次**递归重试**（提高并发幂等性）。
- `list_collection_members`：
  - 支持排序键：`id/name/element/role/updated_at/created_at`；
  - 预加载：`tags/derived/monster_skills`（`selectinload`）减少 N+1。

## 错误与边界情况
- `update_collection` 改名可能触发 `UNIQUE(name)` → `IntegrityError`（上层统一捕获后转 409）。
- `bulk_set_members`：
  - 未提供 `collection_id` 且 `name` 为空 → `ValueError("must provide collection_id or name")`；
  - `action` 非 `"add/remove/set"` → `ValueError("action must be one of: add/remove/set")`；
  - `ids` 为空且 `action!="set"` → 直接返回 0 变更（`set` 的空表示“清空”）。
- 并发：重复插入同一成员可能临界触发唯一键冲突；函数已做一次重试，但**建议路由层保证单请求内的幂等键**。

## 使用示例（服务层直接调用）
```py
# 获取或创建收藏夹
col, created = get_or_create_collection(db, name="竞技队1", color="#FF8800")

# 批量添加成员
res = bulk_set_members(db, collection_id=col.id, ids=[1,2,2,3,"4"], action="add")
# -> {"added": 3, "removed": 0, "skipped": 1, "missing_monsters": [], "collection_id": col.id}

# 覆盖成员（set）
res = bulk_set_members(db, name="竞技队1", ids=[10,11], action="set")

# 列出收藏夹（按 items_count 降序）
items, total = list_collections(db, sort="items_count", order="desc", page=1, page_size=20)

# 查看收藏夹内成员
mons, total = list_collection_members(db, collection_id=col.id, sort="updated_at", order="desc")
```

## 变更指南（How to change safely）
- **多租户支持**：为 `Collection` 增加 `user_id`，并将唯一键改为 `(user_id, name)`；服务层查找/创建需带上 `user_id` 过滤。
- **一致性维护**：若希望持久化冗余 `items_count`，可在 `bulk_set_members` 里维护增量并更新 `Collection.items_count`；或改为数据库视图/触发器。
- **性能优化**：对 `CollectionItem(collection_id, monster_id)` 保持复合主键；为 `CollectionItem.monster_id` 建索引（已存在）便于反查。
- **幂等与重试**：当前仅一次递归重试；对高并发可引入“悲观锁”（如 `FOR UPDATE`，非 SQLite）或重试次数与退避策略。
- **输入校验**：如需更严格的 `ids` 校验，放在 Schema/路由层（非负/最大长度等）。

## 自测清单
- [ ] `get_or_create_collection`：已存在返回 `(col, False)`；不存在创建并返回 `(col, True)`。
- [ ] `list_collections`：带搜索 `q` 与排序 `items_count` 时，`total` 与页面项目数符合预期，且无重复计数。
- [ ] `bulk_set_members(action="add")`：对已存在成员不重复插入，`skipped` 正确。
- [ ] `bulk_set_members(action="remove")`：只删除存在成员，`removed` 正确，`skipped` 为不存在成员数量。
- [ ] `bulk_set_members(action="set")`：能够清空（当 `ids=[]`）并正确做差异化覆盖。
- [ ] `list_collection_members`：分页+排序稳定，且预加载消除明显 N+1。