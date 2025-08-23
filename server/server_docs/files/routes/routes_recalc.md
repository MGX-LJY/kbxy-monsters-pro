file: server/app/routes/recalc.py
type: route
owner: backend
updated: 2025-08-23
stability: legacy
deps: [server/app/db.py, server/app/models.py, server/app/services/rules_engine.py, server/app/services/monsters_service.py, server/app/services/skills_service.py]
exposes: [/recalc(POST)]

TL;DR（30秒）
- 基于 `rules_engine.calc_scores` 的“快速重算”端点：对给定 ids（或全量）计算评分，返回 `tags` 与 `explain`；可选持久化到 `explain_json` 并**合并更新标签**（规则标签 + 技能文本派生）。
- 与当前统一的 `derive_service` 路径并行存在，适合做轻量/自定义权重回算；需要注意模型字段与关系名差异（见常见坑）。

职责与边界
- 做什么：按权重调用规则引擎 → 生成评分解释与标签 → 可选写入 `explain_json`、合并标签。  
- 不做什么：写入 derived 五维、角色定位、与标签的“覆盖式”策略（此处为合并）。

HTTP 端点
- POST /recalc —— 对 ids 批量重算。幂等：对同一权重和同一数据集重复调用结果稳定；当 persist=true 时会写库。

请求体（RecalcIn）
- ids?: number[] —— 目标集合；缺省表示全表（从 DB 读取全部 Monster.id）。
- weights?: {string: number} —— 传给 `calc_scores` 的自定义权重。
- persist: boolean = false —— 是否把 `r.explain` 写回 `m.explain_json`。
- update_tags: boolean = true —— 当 persist=true 时是否合并更新标签（规则标签 + 技能文本派生）。

输出
- { affected: number, results: [{ id, tags, explain }] }  
  - affected：实际写库的条数（仅在 persist=true 时递增）。
  - results[].tags：规则引擎返回的标签集合（列表/可迭代）。  
  - results[].explain：规则引擎的解释对象（透传）。

依赖与数据流
- 规则引擎：`calc_scores({ base_offense, base_survive, base_control, base_tempo, base_pp }, weights)` → 返回对象 `r`（含 `tags`、`explain`）。  
- 标签写入：当 persist & update_tags：  
  1) numeric = set(r.tags)  
  2) skill_texts = 技能名 + 技能描述（从怪物技能集合提取）  
  3) skill_tags = `derive_tags_from_texts(skill_texts)`  
  4) merged = existing ∪ numeric ∪ skill_tags → `upsert_tags` → 赋给 `m.tags`  
- 解释写入：`m.explain_json = r.explain`（整体覆盖）。

事务与幂等
- 会话：逐条循环构造/写入；函数末尾在 persist=true 时统一 `db.commit()`。  
- 幂等：相同 weights & 数据状态下重复运行得到相同 explain 与 tags；合并标签策略对重复调用稳定。  
- 回滚：行内异常未显式捕获（此文件中），但整体没有 try/except；如需细粒度回滚，请加 SAVEPOINT 或行级 rollback。

错误与可观测性
- 404/400：无显式抛出；缺失实体会被跳过（continue）。  
- 规则引擎异常/DB 异常会直接冒泡为 500。  
- 无日志与指标（未埋点），建议对 `affected`、耗时与失败原因做打点。

示例（最常用）
- 全量重算（只看结果，不落库）：  
  `curl -X POST -H "Content-Type: application/json" -d '{"persist":false}' http://127.0.0.1:8000/recalc`
- 指定 ids 并持久化 + 合并标签：  
  `curl -X POST -H "Content-Type: application/json" -d '{"ids":[1,2,3],"persist":true,"update_tags":true}' http://127.0.0.1:8000/recalc`
- 自定义权重试验（不写库）：  
  `curl -X POST -H "Content-Type: application/json" -d '{"ids":[42],"weights":{"base_offense":1.2,"base_survive":0.8}}' http://127.0.0.1:8000/recalc`

常见坑（Top 10）
1) **模型字段不统一**：此路由读取 `m.base_offense/base_survive/.../base_pp`；若模型未包含这些列或为旧名，将抛异常。  
2) **技能关系名差异**：此路由用 `m.skills` 直接取技能对象；若项目统一为 `m.monster_skills → .skill`，则 `skill_texts` 收集不到，需适配。  
3) `persist=false` 时不会写库，也不会更新标签；仅返回结果。  
4) `update_tags` 仅在 `persist=true` 时生效。  
5) 标签策略为**合并**（existing ∪ numeric ∪ skill_tags），不会清理旧标签；可能越积越多。  
6) `derive_tags_from_texts` 取自“技能名+描述”的纯文本解析，容易受噪声与描述风格影响。  
7) 全量模式（ids 缺省）会扫全表，可能耗时较长；建议分批或限流。  
8) 没有幂等键与批次 id；重复提交无法去重统计。  
9) 没有 N+1 预加载，循环内访问 `m.skills/m.tags` 可能导致多次 SQL。  
10) explain 覆盖写入会替换掉原有 `explain_json` 的其他键（如 `raw_stats`），除非规则引擎返回中包含这些内容。

变更指南（How to change safely）
- 对齐统一推导路径：若全局已采用 `derive_service`，建议将本端点改为调用 `recompute_and_autolabel/compute_and_persist`，或明确定位为“规则实验端点”。  
- 关系与字段适配：将 `m.skills` 改为联结 `MonsterSkill.skill` 的方式，并为技能做 `selectinload` 预加载。  
- 写入策略：写回 `explain_json` 时改为“合并更新”而不是整体覆盖；或限定写入 `explain_json["rules_explain"]`。  
- 事务稳健：大批量时引入分批提交与 `begin_nested()`；行异常捕获并 `rollback()` 后继续。  
- 可观测性：记录 `affected/total`、耗时、失败原因 TopN；返回批次 id 便于追踪。  

术语与约定
- rules_explain：建议用于标记规则引擎的解释块键名，以免覆盖 `raw_stats` 等其他 explain 字段。  
- 合并标签：existing ∪ numeric ∪ skill_tags 的并集策略，不移除旧标签。