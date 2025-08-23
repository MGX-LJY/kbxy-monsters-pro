file: server/app/routes/type.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/services/types_service.py]
exposes: [/types/list(GET), /types/chart(GET), /types/effects(GET), /types/card(GET), /types/matrix(GET)]

TL;DR（30秒）
- 提供“属性相克”相关的只读查询：属性列表、总览图表、对战效果、单属性卡片、以及攻/守视角的全矩阵。
- 具体数据与算法全部在 `types_service`，本路由只做参数校验与异常转译（`/types/card` 将 `KeyError` → 404）。

职责与边界
- 做什么：把前端查询转发给 `types_service` 的 `list_types/get_chart/get_effects/get_card/get_matrix`。  
- 不做什么：数据维护、缓存、国际化、权限控制、复杂校验（值的有效性由 service 负责）。

HTTP 端点
- GET /types/list —— 返回 `{types: [...]}`，由 `list_types()` 提供（属性代码/名称列表）。  
- GET /types/chart —— 返回整体“相克图/概览”，由 `get_chart()` 生成（结构取决于 service）。  
- GET /types/effects —— 参数：
  - `vs` (str, required)：“对面属性”，原样传给 `get_effects`（是否支持多值取决于 service）。  
  - `perspective` (attack|defense, default=attack)：视角。  
  - `sort` (asc|desc, optional)：排序方向（可为空表示使用 service 默认）。  
  → 返回对该 `vs` 在指定视角下的效果列表/字典。  
- GET /types/card —— 参数：
  - `self_type` (str, required)：我方属性。  
  → 成功返回该属性的能力卡片；`get_card` 抛 `KeyError` 时转为 `404`。  
- GET /types/matrix —— 参数：
  - `perspective` (attack|defense, default=attack)。  
  → 返回完整攻/守视角矩阵，由 `get_matrix` 生成。

输入/输出（要点）
- 所有端点均为只读、无副作用；输出 JSON 结构以 `types_service` 为准。  
- `/types/effects` 与 `/types/matrix` 的排序/视角约束通过 `Query(..., pattern=)` 基本校验；**属性值合法性**在 service 端判断。

事务与幂等
- 纯读取，无数据库写入；同样请求在相同数据版本下结果稳定。

错误与可观测性
- `/types/card`：未知属性 → `HTTP 404`（由 `KeyError` 映射而来）。  
- 其它端点未捕获异常；如 service 抛错将冒泡为 `500`。  
- 无日志/指标/缓存头；可考虑为矩阵与图表增加缓存。

示例（最常用）
- 属性列表：`curl "http://127.0.0.1:8000/types/list"`  
- 总览图：`curl "http://127.0.0.1:8000/types/chart"`  
- 效果（以水系为对手，攻视角，降序）：`curl "http://127.0.0.1:8000/types/effects?vs=%E6%B0%B4%E7%B3%BB&perspective=attack&sort=desc"`  
- 单卡片（我方火系）：`curl "http://127.0.0.1:8000/types/card?self_type=%E7%81%AB%E7%B3%BB"`  
- 全矩阵（防守视角）：`curl "http://127.0.0.1:8000/types/matrix?perspective=defense"`

常见坑（Top 8）
1) `vs/self_type` 大小写与别名未在路由层归一化；需由 `types_service` 负责映射与容错。  
2) `/types/effects` 的 `vs` 是否支持多值（如逗号分隔）取决于 service；路由未做拆分。  
3) `sort` 为 `None` 时由 service 决定默认排序；前端应显式传入期望排序。  
4) 仅 `/types/card` 做了异常映射；其他函数抛错会直接 500。  
5) 无缓存可能导致频繁请求压力；矩阵/图表属于静态数据，建议加缓存头或服务端缓存。  
6) 无 i18n：若属性代码为英文/内部码，前端需要自行做中文映射。  
7) 未限制返回体大小；大矩阵在移动端渲染可能卡顿。  
8) 无版本化；调整 `types_service` 的数据结构会直接影响前端。

变更指南（How to change safely）
- 统一异常：为 `/types/effects`、`/types/matrix` 增加参数校验与错误转译（400/404）。  
- 输入归一化：在路由层对 `vs/self_type` 做 trim/lower/映射，减少前端依赖。  
- 缓存：对 `/types/chart`、`/types/matrix` 增加 `ETag`/`Cache-Control` 或应用侧缓存。  
- 扩展多值：若 `get_effects` 支持多对手属性，约定 `vs=a,b` 并在路由拆分传递。  
- 文档化：在 `types_service` 补充返回结构示例，便于前端消费。  

术语与约定
- 视角（perspective）：`attack` 表示“我方攻击对对面属性的效果”，`defense` 表示“我方防守承受对面属性的效果”。  
- 矩阵（matrix）：所有属性两两之间的效果表，用于可视化热力/查表。