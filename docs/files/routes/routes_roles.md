file: server/app/routes/roles.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, sqlalchemy.func]
exposes: [/roles(GET)]

TL;DR（30秒）
- 统计各“角色（role）”下怪物数量的简易聚合接口。过滤空/NULL，按数量降序返回 [{name, count}]。

职责与边界
- 做什么：对 Monster.role 做分组计数与排序，提供角色分布概览。
- 不做什么：角色归一化（同义词合并）、派生与回写、分页/筛选。

HTTP 端点
- GET /roles —— 返回所有非空角色的计数列表。幂等：是（读取）。

查询参数/请求体（节选）
- 无。

输入/输出（要点）
- 输出数组项：{name: string, count: number}
- 仅统计 role 不为 NULL 且不为空串的记录；按 count 降序。

依赖与数据流
- DB 会话（SessionLocal）→ ORM 聚合：query(Monster.role, count(Monster.id)) → filter(role is not null and role != "") → group_by(role) → order_by(count desc)。

事务与幂等
- 只读查询，无事务写入；相同数据状态下结果稳定。

错误与可观测性
- 未显式错误处理；DB 异常将抛出 500。
- 无日志与指标；依赖全局 trace（如有）。

示例（最常用）
- curl "http://127.0.0.1:8000/roles"
- 响应示例：[{"name":"输出核心","count":128},{"name":"控制辅助","count":74}]

常见坑（Top 6）
1) 角色值未做归一化（大小写/同义词/前后空白），会导致同义项拆分统计。  
2) 未包含空/NULL 角色；如果大量怪物未定位，将在结果中缺失。  
3) 无分页；角色种类极多时返回体可能偏大（一般可控）。  
4) 排序仅按数量；无法二次排序（如同数按名称）。  
5) 性能在大表上依赖索引；建议为 monsters.role 建索引以优化 group by。  
6) 角色来源若依赖派生/贴标流程，未及时落库会使统计滞后。

变更指南（How to change safely）
- 增加标准化：在查询前对 role 做 TRIM/LOWER 或引入映射表合并同义。  
- 增加查询参数：min_count、order(=count|name)、dir(=asc|desc)、q（按名称模糊过滤）。  
- 性能：为 monsters(role) 建索引；或将结果缓存/定时预计算。  
- 可观测性：记录总角色数与 TopN 角色分布，用于前端图表与监控。

术语与约定
- role：怪物定位/角色；由派生与标签规则写入或人工设定。