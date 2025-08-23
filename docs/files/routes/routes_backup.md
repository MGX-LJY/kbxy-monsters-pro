file: server/app/routes/backup.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, server/app/services/monsters_service.py]
exposes: [/stats, /export/monsters.csv, /backup/export_json, /backup/restore_json, /monsters/bulk_delete(DELETE|POST)]

TL;DR（30秒）
- 负责统计、CSV 导出、JSON 备份/恢复、批量删除。  
- 恢复逻辑支持按 id 与 (name, element) upsert；标签白名单；技能五元组唯一；收藏夹（含成员）可替换或合并。  
- 所有写操作包在事务里；导出为 StreamingResponse。

职责与边界
- 做什么：聚合统计；导出 monsters.csv；导出/导入备份（monsters+collections）；批量删除 Monster。
- 不做什么：派生值重算（导出时仅读已有 derived）；权限/认证；长任务排队。

HTTP 端点
- GET /stats —— 返回 total、with_skills、tags_total。幂等：是。
- GET /export/monsters.csv —— 导出筛选后的怪物及五维派生（空值按 0）。幂等：是。
- GET /backup/export_json —— 导出 monsters 与 collections 的结构化 JSON。幂等：是。
- POST /backup/restore_json?replace_links=bool（默认 true）—— 从 JSON 恢复/合并数据，返回导入汇总。幂等：重复相同载荷在 replace_links=true 下接近幂等（详见“事务与幂等”）。
- DELETE /monsters/bulk_delete —— 按 ids 批量删除，返回 {deleted}。
- POST /monsters/bulk_delete —— 同上（语义兼容）。

查询参数/请求体（节选）
- /export/monsters.csv：q, element, role, tag, sort=updated_at, order=desc。
- /backup/restore_json：Body 可为 {"monsters":[...], "collections":[...]} 或直接 [ ... ]（仅怪物）；replace_links（bool）控制是否替换原有关联。

输入/输出（要点）
- 导出 CSV 字段：id,name,element,role,offense,survive,control,tempo,pp_pressure,tags（tags 以“|”拼接）。derived 为空按 0。
- 备份 JSON（导出）：
  - monsters：id/name/element/role/possess/new_type/type/method/hp,speed,attack,defense,magic,resist/raw_stats/tags/skills/created_at/updated_at。
  - skills：name,element,kind,power,description（五元组代表唯一）。
  - collections：id,name,color,last_used_at,created_at,updated_at,items[monster_id]。
- 恢复 JSON（导入）：
  - 怪物：优先 id upsert，否则按 (name, element) 匹配；写入六维与 explain_json.raw_stats；可回写 created_at/updated_at。
  - 标签：仅接受 buf_/deb_/util_ 前缀；其余忽略。
  - 技能：按五元组查找/创建 Skill，并通过 MonsterSkill 关联，避免重复。
  - 收藏夹：按 id 或 name upsert；成员 items 去重、过滤不存在的 monster。

依赖与数据流
- 上游：路由层接收请求；/export 调用 services.monsters_service.list_monsters 做筛选与分页（page_size=100000）。
- 下游：读写 ORM 模型 Monster/Tag/Skill/MonsterSkill/Collection/CollectionItem；返回 StreamingResponse/JSON。
- 外部 IO：无（仅内存流与 DB）。

事务与幂等
- 事务：restore_json 与 bulk_delete 使用 db.begin 单事务；任一失败整体回滚。导出/统计为只读。
- 幂等：
  - restore_json 在 replace_links=true 时，多次导入同一载荷会得到稳定状态（近似幂等）；replace_links=false 为追加合并，严格幂等性取决于输入集合是否重复。
  - bulk_delete 使用主键集合去重，重复调用只会减少剩余条目。

错误与可观测性
- 400：restore_json 载荷格式错误（既非字典也非数组）。
- 422：常规参数校验失败（由 FastAPI/Pydantic 提供）。
- 数据库层可能抛出主键冲突（显式插入 id 时）；在事务中会整体回滚。
- Trace/日志：沿用全局中间件（x-trace-id）；此文件内未显式记录日志。

示例（最常用）
- curl "GET /stats"
- curl -OJ "GET /export/monsters.csv?q=青龙&order=desc"
- curl -OJ "GET /backup/export_json"
- curl -X POST -H "Content-Type: application/json" -d @backup.json "POST /backup/restore_json?replace_links=true"
- curl -X DELETE -H "Content-Type: application/json" -d '{"ids":[1,2,3]}' "/monsters/bulk_delete"

常见坑（Top 8）
1) /export/monsters.csv 使用 page_size=100000，如数据量大可能占用较多内存；必要时改为逐行流式写出。  
2) derived 五维可能不存在；导出时已按 0 处理，前端不要据此判断“已计算”。  
3) restore_json 默认 replace_links=true，会覆盖原有 tags/skills/收藏夹成员；若要追加，请显式传 false。  
4) 标签只接受 buf_/deb_/util_ 前缀；其他标签会被忽略，可能与期望不符。  
5) 技能以（name,element,kind,power,description）五元组为唯一；描述文本的微小差异会导致“判定为新技能”。  
6) 显式沿用 id 插入（Monster/Collection）在已占用时会抛冲突；谨慎使用。  
7) collections.items 中包含不存在的 monster_id 会被跳过，易造成数量对不上。  
8) 批量删除为硬删除，无软删除/回收站；操作不可逆。

变更指南（How to change safely）
- 扩展导出字段：先在 services.list_monsters 或模型层补齐数据，再更新 CSV/JSON 输出与文档、自测用例。  
- 调整幂等/去重规则：同步修改 Skill 五元组或标签白名单，并补充回归测试。  
- 性能优化：CSV 采用生成器逐行写出；/stats 可改聚合查询或增加索引。  
- 兼容性：对备份格式做新增字段时保证向后兼容（旧字段保留、默认值合理）。

术语与约定
- 标签前缀：buf_（增益）、deb_（减益）、util_（功能）。  
- 技能规范化与唯一：以五元组定义唯一性，避免重复 Skill 记录。  
- 原始六维：优先写入 explain_json.raw_stats，便于后续派生与审计。