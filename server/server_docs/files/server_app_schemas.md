---
file: server/app/schemas.py
type: schema
owner: backend
updated: 2025-08-23
stability: stable
deps: [pydantic v2]
exposes: [SkillIn, SkillOut, DerivedOut, AutoMatchIn, AutoMatchOut, MonsterIn, MonsterOut, MonsterList, ImportPreview, ImportResult, ProblemDetail, CollectionIn, CollectionUpdateIn, CollectionOut, CollectionList, CollectionBulkSetIn, CollectionCreateIn, BulkSetMembersIn, BulkSetMembersOut]

# schemas.py · 快速卡片

## TL;DR（30 秒）
- 职责：定义对外 API 的请求/响应模型（Pydantic v2），覆盖技能、怪物、派生五维、导入、错误体与收藏夹。
- 关键约定：大多数组件 `from_attributes=True`，可直接从 ORM 对象序列化；列表字段均有 `default_factory=list` 防止 `null`。
- 常见坑
  1) `MonsterOut.possess` 在响应中是 `Optional[bool]`，可能为 `null`；与 DB 默认 `False` 不完全一致（前端需兜底）。
  2) `SkillIn.power` 为 `Optional[int]`，纯状态技建议传 `null` 而非 `0`（`0` 也允许且保留含义）。
  3) `CollectionBulkSetIn` 的 `action` 仅支持 `"add"|"remove"|"set"`；传其他值会 422。

## 总体约定
- 时间：`datetime` 字段均返回 ISO8601（UTC）字符串。
- 可空：标记为 `Optional[...]` 的字段如果未知/无值将省略或为 `null`（取决于路由返回逻辑）。
- 列表：输入/输出中的列表字段默认返回 `[]` 而非 `null`。
- 规范化：技能的 `element/kind` 在服务层/爬虫层会做映射（“特/无→特殊”、“技能→法术”等），Schema 允许自由值但推荐传规范值。

## Schema 一览与要点

### Skills
- SkillIn
  - 字段：`name`(必填)、`element?`、`kind?`、`power?`、`description?`(默认空串)
  - 用于：创建/覆盖怪物技能集合（如 PUT /monsters/{id}/skills）
- SkillOut（from_attributes=True）
  - 字段：`id`、`name`、`element?`、`kind?`、`power?`、`description?`

### Derived 五维（只读）
- DerivedOut
  - 字段：`offense/survive/control/tempo/pp_pressure`（int）

### AutoMatch（占位，当前不直接使用）
- AutoMatchIn：`commit: bool=False`
- AutoMatchOut：`monster_id`、`role`、`tags: List[str]`、`derived: DerivedOut`、`committed: bool`

### Monsters
- MonsterIn
  - 基本：`name`(必填)、`element?`、`role?`
  - 原始六维：`hp/speed/attack/defense/magic/resist`（float，默认 0）
  - 获取/持有：`possess: bool=False`、`new_type?`、`type?`、`method?`
  - 标签与技能：`tags: List[str]=[]`、`skills: List[SkillIn]=[]`
- MonsterOut（from_attributes=True）
  - 同步包含：`id/name/element/role/六维/获取相关`
  - 附加：`tags: List[str]`、`explain_json: Dict[str,Any]`
  - 时间：`created_at?`、`updated_at?`
  - 派生：`derived?: DerivedOut`

- MonsterList
  - 分页容器：`items: List[MonsterOut]`、`total: int`、`has_more: bool`、`etag: str`

### 导入（importing）
- ImportPreview：`columns: List[str]`、`total_rows: int`、`sample: List[dict]`、`hints: List[str]=[]`
- ImportResult：`inserted/updated/skipped: int`、`errors: List[dict]=[]`

### 错误体（Problem Details）
- ProblemDetail（与 RFC7807 风格接近）
  - 字段：`type="about:blank"`、`title="Bad Request"`、`status=400`、`code="BAD_REQUEST"`、`detail`、`trace_id`

### 收藏夹（Collections）
- CollectionIn：`name`(1..64, 唯一)、`color?`(≤16)
- CollectionUpdateIn：`name?`、`color?`
- CollectionOut（from_attributes=True）
  - 字段：`id/name/color/items_count/last_used_at?/created_at/updated_at`
- CollectionList：`items: List[CollectionOut]`、`total`、`has_more`、`etag`
- CollectionBulkSetIn
  - 语义：对某收藏夹批量操作成员
  - 键：`collection_id?`（优先）或 `name?`（可触发按名创建的策略由服务层决定）
  - 内容：`ids: List[int]`（怪物 ID 列表）；`action: "add"|"remove"|"set"`（默认 `"add"`）

- 兼容别名
  - CollectionCreateIn ≡ CollectionIn（用于 POST /collections）
  - BulkSetMembersIn ≡ CollectionBulkSetIn 并新增 `color_for_new?`（当按 name 惰性创建收藏夹时使用）
  - BulkSetMembersOut：批量结果回执（`collection_id`、`added/removed/skipped`、`missing_monsters: List[int]`）

## 示例载荷

- 创建怪物（POST /monsters）
  {
    "name": "碧青水龙兽",
    "element": "水系",
    "hp": 98, "speed": 96, "attack": 87, "defense": 81, "magic": 113, "resist": 85,
    "possess": false, "new_type": true, "type": "活动获取宠物", "method": "完成××活动",
    "tags": ["buf_speed", "util_water"],
    "skills": [
      {"name":"明王咒","element":"特殊","kind":"特殊","power":0,"description":"..."},
      {"name":"青龙搅海","element":"水系","kind":"法术","power":135,"description":"..."}
    ]
  }

- 覆盖技能（PUT /monsters/{id}/skills）
  [
    {"name":"明王咒","element":"特殊","kind":"特殊","power":0,"description":"..."},
    {"name":"青龙搅海","element":"水系","kind":"法术","power":135,"description":"..."}
  ]

- 批量维护收藏夹成员（POST /collections/bulk_set）
  {
    "collection_id": 3,
    "ids": [10,11,12],
    "action": "add"
  }

- 按名称惰性创建并覆盖成员（POST /collections/bulk_set）
  {
    "name": "竞技队1",
    "ids": [1,2,3,4],
    "action": "set",
    "color_for_new": "#FF8800"
  }

## 变更指南（How to change safely）
- 新增响应字段：优先在 `Out` 模型追加 `Optional[...]`，保持向后兼容；前端按存在性渲染。
- 强化校验：如需对 `element/kind` 做枚举限制，可引入 `Literal`/`Enum`；变更需评估历史数据与爬虫映射。
- 统一布尔语义：若希望 `MonsterOut.possess` 一律返回 `bool`，可将类型改为 `bool` 并在序列化层做 `False` 兜底。
- 错误体标准化：保持 ProblemDetail 在全局异常处理中一致输出，并写入 `trace_id`。
- 批量接口的稳定性：`CollectionBulkSetIn` 的 `action` 若扩展新值（如 `"toggle"`），需同步前端与服务层。

## 自测清单
- [ ] MonsterIn 不提供可选字段时，默认值能正确生效（六维=0、lists=[]）。
- [ ] SkillOut/MonsterOut 能从 ORM 模型直接序列化（`from_attributes=True`）。
- [ ] 导入预览与导入结果的错误列表格式固定（前端可直接渲染）。
- [ ] ProblemDetail 在 4xx/5xx 场景结构稳定，并含 `trace_id`。
- [ ] CollectionBulkSetIn 对非法 `action` 返回 422，对空 `ids` 返回 422（由路由层校验）。