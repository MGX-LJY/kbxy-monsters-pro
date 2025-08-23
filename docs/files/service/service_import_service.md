---
file: server/app/services/import_service.py
type: service
owner: backend
updated: 2025-08-23
stability: beta
deps: [SQLAlchemy Session/select, csv/io/re, ..models.{Monster,ImportJob}, .rules_engine.calc_scores, .skills_service.{upsert_skills,derive_tags_from_texts}, .monsters_service.upsert_tags]
exposes: [preview, commit, parse_csv]

# import_service.py · 快速卡片

## TL;DR（30 秒）
- 职责：把 CSV/TSV 批量导入为 Monster 记录；支持**表头纠错**、**技能列自动识别**、**幂等**（Idempotency-Key）、**单事务提交**、**标签合并**与**解释字段**构建。
- 入口：
  - `preview(file_bytes) -> {columns,total_rows,sample,hints}`：只解析不落库。
  - `commit(db, file_bytes, idempotency_key=None) -> {inserted,updated,skipped,errors}`：在**单事务**中 upsert 并返回统计。
- 常见坑
  1) 当前实现依赖列名 `name_final` 与 `Monster.name_final/base_*` 字段；而**最新模型使用 `name` 且无 base_* 字段**（需按“版本兼容建议”调整）。  
  2) `m.skills.append(s)` 依赖 association_proxy 的 **creator** 行为；若未配置，会导致**只建关联不落**（建议通过服务层创建 `MonsterSkill`）。  
  3) 任何一行抛错（如约束冲突）都会导致整个事务回滚；返回的 `errors` 不含逐行细节（仅总体 IntegrityError）。

## 数据输入与表头规范化
- `HEADER_MAP`：把多语/别名表头映射到标准键，如
  - 名称：`名称/最终名称/名字/name → name_final`
  - 元素：`元素/属性/element → element`
  - 六维：`体力/生命/hp/survive → hp`，`速度/tempo → speed`，`攻击/offense → attack`...（详见代码）
  - 文本：`总结/评价/说明/summary/effect → summary`
- 技能列自动识别（重难点，见 `_read_rows_with_duplicate_headers`）
  - 识别形态：`skill_#_name / skill_#_desc / skill_#_is_core`，兼容 `skill#`、`skill#_desc`、`skill-#-name`、“技能/关键技能”中文列。
  - 去除非技能列：如“技能数量/次数/等级/CD/冷却”等。
  - “技能说明”自动与最近一次出现的技能名对齐。
- 分隔符探测：优先 `csv.Sniffer()`，失败则按是否包含 `\t` 退化为 `\t` 或 `,`。

## 主要流程（preview / commit）
1) `parse_csv(file_bytes)`  
   - 归一化表头 → 产出 `semantic_cols`（标准列名集合）与**行字典数组**（已清洗）。
2) `preview(bytes)`  
   - 返回列名、总行数、前 10 行样本与提示（缺少 `name_final` 时给出 hint）。
3) `commit(db, bytes, idempotency_key=None)`  
   - 幂等：若提供 `idempotency_key` 且 `ImportJob.key` 已存在，直接返回历史结果。  
   - 打开 `with db.begin():` 单事务，逐行处理：  
     a. 读取 `name_final`（或降级 `name_repo/名称`）；为空/占位（"string"）→ `skipped++`。  
     b. 以 `name_final`（可选叠加 `element`）查询是否已有记录；决定新增/更新。  
     c. 解析六维（字符串→float），并构造**分数基**传入 `rules_engine.calc_scores()`；把 `raw_stats`（含六维与 sum）写入 `explain_json`。  
     d. 技能：`_extract_skills_from_row()` 仅取**核心技能**（`is_core` 为真；缺列默认保留），调用 `upsert_skills()` 入库后**绑定到怪物**（去重）。  
     e. 标签：合并 `calc_scores` 产出的数值标签、由技能文本/summary 提取的标签（`derive_tags_from_texts`），再通过 `upsert_tags()` 落库。  
     f. 角色：若 CSV 未给 `role`，用 `_derive_role()` 兜底（简单规则）。  
     g. 解释：补充 `skill_names` 与 `summary`。  
   - 计数 `inserted/updated/skipped`；事务成功后（或幂等键存在时）维护/写入 `ImportJob` 结果快照。

## 关键函数速查
- `_read_rows_with_duplicate_headers(text, delim) -> (headers_norm, data_rows)`  
  规范技能列与重复表头，排除“数量/等级/CD”等。
- `_extract_skills_from_row(row) -> List[(name, desc)]`  
  只保留核心技能，缺描述时**向右 3 列**搜索“像描述”的文本；按名称去重。
- `_is_meaningful_desc(text)`  
  粗判是否为有效描述（长度、包含中文标点或关键效果词）。
- `_split_tags(text)`  
  以 `|,;/\s` 拆分，去空。

## 幂等与事务语义
- 幂等：重复调用 `commit(..., idempotency_key="...")` 返回同一 `ImportJob.result_json`。  
- 事务：使用 `with db.begin():`；任意异常导致**整批回滚**。  
- 错误：捕获 `IntegrityError`，返回 `errors=[{"error":"db_integrity_error", "detail": "..."}]`；逐行错误目前未细分。

## 与当前模型的差异（重要）
- 模型侧（最新）：`Monster.name` 为唯一键，且无 `base_offense/base_survive/...` 字段。  
- 本服务（当前文件）：使用 `name_final` 与 `base_*`。  
- 影响：  
  - 查询/创建使用了 `Monster.name_final`（会报字段不存在）；  
  - 赋值 `m.base_*` 同样不存在；  
  - 直接 `m.skills.append(s)` 在未配置 association_proxy creator 的情况下可能不生效。
- 迁移/修复建议（v2 对齐）：
  1) 把 `REQUIRED = ["name_final"]` 改为 `["name"]`；`HEADER_MAP` 中所有 `→ name_final` 的映射改为 `→ name`。  
  2) `commit()` 查询改为 `select(Monster).where(Monster.name == name, Monster.element == element?)`；创建用 `Monster(name=name)`。  
  3) 去除 `base_*` 相关字段：`calc_scores()` 的输入直接基于六维或迁移到 `derive_service.compute_derived[_out]`。  
  4) 绑定技能：通过服务层**创建 MonsterSkill**（或给 association_proxy 配置 `creator`），示例：  
     ```py
     from ..models import MonsterSkill
     if s.id not in existed_ids:
         db.add(MonsterSkill(monster_id=m.id, skill_id=s.id, selected=False))
     ```  
  5) `explain_json` 继续写入 `raw_stats` 与 `summary/skill_names`；其余字段保持兼容。

## 使用示例（与接口映射）
- 预览
  - `preview(open("monsters.csv","rb").read()) -> {"columns":[...],"total_rows":N,"sample":[...],"hints":[]}`
- 提交（带幂等）
  - `commit(db, open("monsters.csv","rb").read(), idempotency_key="sha256(file)") -> {"inserted":..,"updated":..,"skipped":..,"errors":[]}`

## 自测清单
- [ ] 复杂表头（包含 `skill1/name/desc/is_core`、中文“技能/关键技能”）能正确配对到同一技能编号。  
- [ ] `is_core` 缺省时核心技能默认保留；`_is_meaningful_desc` 能过滤“无/0/null”等伪描述。  
- [ ] `preview` 对缺少名称列给出 hint；`parse_csv` 能正确探测分隔符并输出 10 条样本。  
- [ ] 幂等键重复提交直接返回旧结果；更换文件但复用旧键仍返回旧结果（符合幂等语义）。  
- [ ] 单行违反唯一约束能触发整体回滚并返回 `db_integrity_error`。  
- [ ]（完成迁移后）使用 `name` +（可选）`element` 作为 upsert 键，全量导入通过。

## 后续优化
- 行级错误收集与“跳过错误继续导入”的降级模式（批次容忍）。  
- 进度与审计：写 `ImportJob.status=processing/failed`，导入中可轮询。  
- 与 `derive_service` 打通：导入后**自动计算派生五系与定位**。  
- 校验更强：对 `element/role/tags` 做枚举/正则校验并产出详细错误定位行号。  
- 大文件处理：流式解析与分批事务提交，避免长事务与内存占用。