file: server/app/routes/skills_admin.py
type: route
owner: backend
updated: 2025-08-23
stability: admin
deps: [server/app/db.py, server/app/models.py, sqlalchemy.func, re]
exposes: [/admin/skills/stats(GET), /admin/skills/clear_descriptions(POST), /admin/skills/scrub_names(POST)]

TL;DR（30秒）
- 技能清理与统计的管理端路由：统计技能与“疑似错误描述”，一键清空描述（全部/疑似），以及删除无效技能名的 Skill 记录。  
- 操作具破坏性，默认无鉴权、无干跑；清理前务必备份（/backup/export_json）。

职责与边界
- 做什么：统计技能描述质量；按启发式规则批量清空描述；删除仅由数字/横线/空白组成或空字符串的技能名。  
- 不做什么：鉴权/审计、细粒度预览、并发安全、与“技能唯一策略”对齐（可能影响其它模块的唯一性/去重）。

HTTP 端点
- GET /admin/skills/stats —— 返回 {total_skills, with_description, suspicious_description}。  
- POST /admin/skills/clear_descriptions?mode=suspicious|all（默认 suspicious）  
  - suspicious：仅清理疑似由“summary/评价语”误写入的描述；返回 {mode, changed, summary_candidates}。  
  - all：清空所有非空描述；返回 {mode, changed}。  
- POST /admin/skills/scrub_names —— 删除名称无效（空/只含数字与横线/空白）的技能；先解除关联再删，返回 {removed, total}。

判断规则（核心启发式）
- 无效名称：空串或完全匹配 `^[\d\-\—\s]+$`。  
- 可疑描述：  
  1) 在 TRIVIAL 集（"", "0", "1", "-", "—", "无", "暂无", "null", "none", "n/a", "N/A"），或  
  2) 与任意 Monster.explain_json.summary 完全相同，或  
  3) 含评价性词汇（如“主攻/辅助/比较均衡/克星/种族值/生存能力/可以/不错/非常/做一个”…）且**不**含技能机制关键词（命中/回合/几率/造成/伤害/提高/降低/免疫/状态/先手/消除/PP/倍/持续）。

依赖与数据流
- stats/clear：遍历全表 Monster 收集 summary 集合 → 遍历全表 Skill 评估/清理 description。  
- scrub：遍历全表 Skill，命中规则则 `s.monsters.clear()` 解除关联并 `db.delete(s)`。

事务与幂等
- 每个端点单事务提交（一次 commit）；重复调用在相同数据上结果稳定（被清空/删除后不再计数/删除）。  
- 无分批/保存点；超大表时建议手动分批执行或扩展为批处理。

错误与可观测性
- 无显式错误处理/鉴权；DB 异常将 500。  
- 无日志与指标；建议对 `{changed/removed}`、用时做埋点。  
- 注意：清空/删除操作不可逆；与其它模块并发写入可能产生竞态。

示例（最常用）
- 查看统计：curl "http://127.0.0.1:8000/admin/skills/stats"  
- 仅清理可疑描述：curl -X POST "http://127.0.0.1:8000/admin/skills/clear_descriptions?mode=suspicious"  
- 清空全部描述：curl -X POST "http://127.0.0.1:8000/admin/skills/clear_descriptions?mode=all"  
- 删除无效技能名：curl -X POST "http://127.0.0.1:8000/admin/skills/scrub_names"

常见坑（Top 10）
1) **唯一性冲突风险**：若系统某处将 description 纳入技能唯一键（如 5 元组），批量清空可能制造重复，需先对齐唯一策略。  
2) **误删/误清**：启发式规则可能有误报；建议先跑 stats，对可疑样本抽检。  
3) **无鉴权**：/admin 路径未做权限控制，任何人可操作。  
4) **全表扫描**：三端点都遍历全表；大库下内存与耗时显著。  
5) **关系名假设**：`s.monsters.clear()` 依赖 Skill↔Monster 的关系名为 `monsters`；若模型变更为经由 MonsterSkill，需要适配。  
6) **描述清空写空串**：而非设为 NULL；前端/查询需统一对待空串与 NULL。  
7) **国际化大小写**：TRIVIAL 集合仅少量中英大小写；可能漏掉其它语言/变体。  
8) **无干跑(dry-run)** 与过滤条件；无法预览将要变更的具体条目。  
9) **并发修改**：运行期间其它写入可能覆盖/被覆盖；缺少乐观锁。  
10) **不可恢复**：无回滚/回档机制；操作前请先 `/backup/export_json`。

变更指南（How to change safely）
- 加 `dry_run=true` 返回待变更清单与计数；确认后再执行。  
- 增量/限制：支持 `limit/offset` 或按 id 范围清理；对大表分批提交。  
- 鉴权与审计：加管理角色校验、记录操作者/时间/变更数量与样例。  
- 统一唯一策略：与 skills_service/backup 对齐（4 元组或 5 元组），避免清空描述后产生重复。  
- 写 NULL：将“清空”改为置 NULL，并在读取层统一规范化为空。  
- 提升准确率：将“机制关键词”与“评价关键词”表抽到配置，并可热更新/灰度。  

术语与约定
- 可疑描述（suspicious）：更像“怪物总结/评价”的文本，而非“技能机制说明”的文本。  
- 无效名称（invalid）：空或仅数字/横线/空白。