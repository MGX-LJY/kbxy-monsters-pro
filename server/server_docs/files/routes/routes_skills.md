file: server/app/routes/skills.py
type: route
owner: backend
updated: 2025-08-23
stability: legacy
deps: [server/app/db.py, server/app/models.py]
exposes: [/monsters/{id}/skills(GET|PUT|POST)]

TL;DR（30秒）
- “简化版技能管理”路由：按名字与关联级描述维护某只怪物的技能集合。只用到 Skill.name，未覆盖 element/kind/power/selected 等高级字段。  
- 与 monsters.py 中的同名端点功能重叠且语义不同，存在路由冲突与数据一致性风险。

职责与边界
- 做什么：读取某怪物的技能列表（优先返回关联表描述）；用“名称+描述”的最小集合覆盖或设置该怪物的技能。  
- 不做什么：技能规范化（element/kind/power）、selected 标记、自动贴标与派生重算、幂等键、权限控制。

HTTP 端点
- GET /monsters/{monster_id}/skills —— 返回该怪物的技能清单；字段组合自 MonsterSkill 与 Skill。  
- PUT /monsters/{monster_id}/skills —— 覆盖式设置技能集合（按名称去重、缺省新建 Skill，仅写关联描述）；返回 {"ok": true}。  
- POST /monsters/{monster_id}/skills —— 与 PUT 等价（兼容写法）。

请求/响应（要点）
- PUT/POST Body:
  { "skills": [ { "name": string, "description"?: string } ] }
- GET Response（每项）:
  { "id": MonsterSkill.id, "name": Skill.name, "element": Skill.element?, "kind": Skill.kind?, "power": Skill.power?, "description": MonsterSkill.description || Skill.description || "" }

依赖与数据流
- 读取/写入通过 Monster.monster_skills ↔ MonsterSkill.skill；加载策略：selectinload(...).joinedload(...)，避免 N+1。  
- 新增 Skill 时仅设置 name，其它字段留空，待后续爬虫/管理补全。

事务与幂等
- 写接口：在本函数内完成增删改并立即 db.commit()。  
- 幂等：对相同载荷幂等（覆盖语义 + 名称去重）；但与系统其它“技能唯一策略”不一致可能造成跨路由幂等性失效。

错误与可观测性
- 404：monster 不存在。  
- 其它 DB 异常未捕获，冒泡为 500。  
- 未埋点、未记录变更数量。

示例（最常用）
- 读取：curl "http://127.0.0.1:8000/monsters/42/skills"
- 覆盖：curl -X PUT -H "Content-Type: application/json" -d '{"skills":[{"name":"明王咒","description":"回合蓄力"},{"name":"青龙搅海"}]}' http://127.0.0.1:8000/monsters/42/skills
- 兼容 POST：curl -X POST -H "Content-Type: application/json" -d '{"skills":[{"name":"水浪拍击","description":"强力物理"}]}' http://127.0.0.1:8000/monsters/42/skills

常见坑（Top 10）
1) 与 monsters.py 的 /monsters/{id}/skills(GET|PUT) 完全重叠；依赖 include_router 顺序，可能发生“哪个实现生效”不确定或注册冲突。  
2) 返回项的 id 是 MonsterSkill.id（关联 id），不是 Skill.id，前端若用它当技能主键会出错。  
3) 仅按 Skill.name 新建/匹配，忽略 element/kind/power/selected；与系统其它路径（采用 4/5 元组唯一）不一致，易导致重复/漂移。  
4) 写入后未触发 recompute_and_autolabel/compute_and_persist，导致派生与标签未更新。  
5) 覆盖语义：未包含在载荷中的旧技能会被删除；需要“追加”时必须先读取合并。  
6) 仅支持两字段（name/description）；无法设置选中态(selected)或元素/类型/威力等规范化信息。  
7) 读接口混合返回 MonsterSkill.description 与 Skill.description，来源不透明可能引发显示混乱。  
8) 新建 Skill 仅写 name，会污染全局技能字典（缺少元素/类型），后续补全成本增大。  
9) 无输入长度/数量校验；极端大载荷可能拖慢事务。  
10) 无审计日志；批量覆盖难以追踪差异。

变更指南（How to change safely）
- 统一：与 monsters.py 的技能端点合并，使用 upsert_skills 的规范化唯一策略（name, element, kind, power[, description]），并透传 selected。  
- 重算：写入后调用 recompute_and_autolabel 或 compute_and_persist，保持派生与标签一致。  
- 返回：GET 返回 Skill.id 与清晰的来源字段（e.g. rel_description 与 skill_description 分列）。  
- 路由：若保留本文件，修改前缀为 /skills-basic 或仅暴露 POST /monsters/{id}/skills/basic，避免冲突。  
- 校验与安全：限制 skills 数量与字段长度；为 name 做规范化（trim/全角空格清理）。  
- 可观测性：返回变更计数（added/updated/removed），增加日志与指标。  

术语与约定
- 覆盖式设置：以请求列表为准，删除未包含的旧关联。  
- 关联级描述：MonsterSkill.description，表示“该怪物-该技能”的专属文案，优先于 Skill.description。