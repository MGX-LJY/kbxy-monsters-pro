file: server/app/routes/importing.py
type: route
owner: backend
updated: 2025-08-23
stability: beta
deps: [server/app/db.py, server/app/models.py, server/app/services/skills_service.py, server/app/services/derive_service.py]
exposes: [/import/preview(POST), /import/commit(POST)]

TL;DR（30秒）
- CSV/TSV 批量导入的**预览**与**提交**两端点：自动识别分隔符与表头别名；提交时写入六维与 raw_stats，覆盖技能（至多两条），并触发派生+自动贴标。  
- 预览仅解析前 10 行并提示缺失字段；提交按 `name_final` upsert（无则新建），返回插入/更新/跳过与错误明细。

职责与边界
- 做什么：解析上传文件 → 规范化列名 → 预览采样/缺字段提示 → 提交入库（覆盖技能、写 explain_json.raw_stats 与 summary）→ 重算派生与贴标。  
- 不做什么：标签/定位从 CSV 导入（统一由服务端规则生成）；并发/队列处理；长事务/全量回滚；Idempotency-Key 幂等。

HTTP 端点
- POST /import/preview —— 返回 {columns,total_rows,sample[≤10],hints[]}；仅解析不落库。幂等：是。  
- POST /import/commit —— 逐行 upsert 并在末尾一次性 commit；返回 {inserted,updated,skipped,errors[]}。幂等：对相同文件近似幂等（覆盖技能），但严格幂等未保证。

上传格式与字段映射
- 支持分隔符：`,`、`\t`、`;`（自动识别，失败回落逗号）。编码：UTF-8/UTF-8-SIG。  
- 必填字段（预览提示/提交校验）：`element,name_final,hp,speed,attack,defense,magic,resist`。  
- 表头别名（节选）：  
  - element：元素/系别  
  - name_final：名称/名字  
  - hp：体力；speed：速度；attack：攻击；defense：防御；magic：法术；resist：抗性  
  - summary：total/合计/summary/总结（写入 explain_json.summary）  
  - 技能：skill_1_name/技能1 + skill_1_desc/技能1描述；skill_2_name/技能2 + skill_2_desc/技能2描述  
  - 忽略列：tags/标签、role/定位、name_repo/仓库名（统一由服务端生成或无用）

输入/输出（要点）
- 预览响应：  
  - columns：识别出的列键（忽略列不计入）。  
  - total_rows：数据行数（不含表头）。  
  - sample：前 10 行映射后的键值。  
  - hints：缺失必填时提示 `"缺少字段: ..."`。  
- 提交行为：  
  - 匹配：以 `Monster.name_final` 查找；不存在则 `Monster(name_final=...)` 新建。  
  - 写入：element 与六维（float，非法视为 0.0）；`explain_json.raw_stats={六维,sum}`；若有 summary 写 `explain_json.summary`。  
  - 技能：提取最多两对 (name, desc)，**覆盖**现有关联（清空后重建），并在 `explain_json.skill_names` 记录名称清单。  
  - 派生：`recompute_and_autolabel(db, m)`，回写角色/标签并计算五维。  
  - 结果：{inserted,updated,skipped,errors[]}；errors 单项含 {line,error,row}（line 从 2 起算）。

依赖与数据流
- 解析：csv.Sniffer → _normalize_headers（别名映射/忽略列）→ 行映射。  
- 落库：SQLAlchemy ORM；技能通过 `services.skills_service.upsert_skills(db, pairs)`（此处**简化签名**：[(name, desc)]）。  
- 派生与贴标：`services.derive_service.recompute_and_autolabel`。

事务与幂等
- 事务：整个导入过程**一次性 db.commit()**；行内异常被捕获并加入 errors，但**未对失败行显式 rollback**（会话可能进入失败态）。  
- 幂等：同一文件重复提交通常得到相同结果（覆盖技能/重算派生），但不保证强幂等；没有 `Idempotency-Key`。  
- 粒度：行级错误不影响其他行提交（最佳努力）。

错误与可观测性
- 400：空文件/编码失败/缺字段。  
- 行级错误：加入 errors[] 并记为 skipped。  
- 未对 DB 异常统一降级（IntegrityError 等可能使会话失效，影响后续行）。  
- 无日志与指标埋点；依赖全局 trace（如有）。

示例（最常用）
- 预览：  
  - `curl -F "file=@/path/monsters.csv" http://127.0.0.1:8000/import/preview`  
- 提交：  
  - `curl -F "file=@/path/monsters.csv" http://127.0.0.1:8000/import/commit`

常见坑（Top 10）
1) **name_final 与其他路由的唯一键差异**：其他处多以 `Monster.name` 为主键语义；本路由用 `name_final` 匹配，可能出现双字段不一致导致重复实体或无法联动。  
2) 行内异常未 rollback：遇到约束/类型错误后会话可能进入 failed 状态；继续处理后续行可能串联失败。  
3) 技能仅支持两条（skill_1/skill_2），且为**覆盖**策略；超过两条的输入将被丢弃。  
4) `_to_float` 非法值置 0.0，易掩盖数据问题；建议校验并报错或提示。  
5) Sniffer 只抽样前 3000 字符判断分隔符；复杂表头或混合分隔可能误判。  
6) 预览的 columns/hints 基于首行；若中途列名变化将无法识别。  
7) 读取方式将整个文件读入内存；超大文件内存占用高。  
8) 忽略 CSV 的 tags/role：即便提供也不会落库；需由服务端自动贴标/定位。  
9) `upsert_skills` 在此处使用 (name, desc) 简化签名，可能与其他路径（基于元素/类型/威力等的五元组）策略不一致。  
10) 仅 `UTF-8/UTF-8-SIG`；其他编码（GBK 等）会 400。

变更指南（How to change safely）
- **字段统一**：尽快与全局对齐唯一键（统一用 `name` 或 `name,element` 组合），提供迁移脚本同步 `name_final`。  
- **健壮性**：行级异常时 `session.rollback()`，并继续下一行；或使用 `db.begin_nested()` 做行级 SAVEPOINT。  
- **幂等性**：支持 `Idempotency-Key`（散列文件内容）缓存上次结果；或提供 `dry_run=true`。  
- **性能**：流式解析（逐行 reader + 分批 flush/commit）；限制最大文件大小；为 name/name_final 建索引。  
- **技能扩展**：支持可变数量技能列表（skill_n_*），并与统一的技能五元组唯一策略接轨。  
- **校验**：将 `_to_float` 的“置 0”改为可配置策略（报错/警告/置 0）；对 summary 进行最大长度/清洗。  
- **可观测性**：埋点导入规模、失败原因 TopN、耗时分布；对 errors 做分页存储或输出文件下载。

术语与约定
- raw_stats：原始六维及其 sum，写入 `explain_json.raw_stats`，供派生与审计。  
- 覆盖策略：若解析到技能则清空并重建技能关联；否则保留现有关联。  
- 采样：预览仅展示前 10 行，不代表全量质量。