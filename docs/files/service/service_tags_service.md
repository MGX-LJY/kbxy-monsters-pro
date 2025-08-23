---
file: server/app/services/tags_service.py
type: service
owner: backend
updated: 2025-08-23
stability: beta
deps: [sqlalchemy.select/selectinload, httpx(optional), re/json/threading/time, Path/os, uuid, lru_cache]
exposes: [load_catalog, get_patterns_from_catalog, get_i18n_map, get_all_codes, get_keywords_map, suggest_tags_grouped, suggest_tags_for_monster, extract_signals, ai_classify_text, ai_suggest_tags_grouped, ai_suggest_tags_for_monster, start_ai_batch_tagging, get_ai_batch_progress, cancel_ai_batch, cleanup_finished_jobs, infer_role_for_monster, derive, CODE2CN, CN2CODE, ALL_CODES]

tags_service.py · 快速卡片

TL;DR（30 秒）
- 统一“标签目录”加载与热更新；支持新旧两版 schema（by_code / 分三类）。
- 两条打标链路：
  1) 正则：从技能名/描述文本匹配目录里的模式 → `suggest_tags_grouped/for_monster`。
  2) AI：DeepSeek 分类器只在固定标签集合内多选 → `ai_*`；可与正则做“修复并集（repair_union）”。
- 严格守卫 `util_pp_drain`（PP 压制）：只有命中“明确减少对手技能次数/PP”才给标。
- 派生支持：`extract_signals` 输出 v2 信号供派生与定位；并提供到 `derive_service` 的轻量转发。

核心职责与数据流
- 怪物 → 聚合技能文本（名+描述）→ 正则/AI → 标签代码（buf_/deb_/util_）→ 上层写库（通常配合 monsters_service.set_tags_and_rederive）。
- 目录（config/tags_catalog.json）提供三块：分类集合、正则片段/宏、关键词（用于 AI 修复验证片段）。

环境变量（配置项）
- TAGS_CATALOG_PATH：目录 JSON 路径（默认：当前文件旁的 config/tags_catalog.json）
- TAGS_CATALOG_TTL：热更新 TTL 秒（默认 5s），到期或 mtime 变更自动重载（线程安全）
- TAG_WRITE_STRATEGY：选择最终写库来源：ai | regex | repair_union（默认 ai）
- TAG_AI_REPAIR_VERIFY：repair_union 时是否用关键词校验新增 AI 标签（默认开启）
- DEEPSEEK_API_URL / DEEPSEEK_MODEL / DEEPSEEK_API_KEY：AI 分类接口参数（必须提供 KEY 才能走 AI）
  注意：代码内有默认 KEY 字符串，仅为占位；请在运行环境**务必覆盖**，切勿把真实密钥提交到仓库。

目录 schema（自动兼容）
- i18n：{ zh, en, ... } 代码→多语言名；导出 `CODE2CN/CN2CODE/ALL_CODES` 方便显示。
- categories：{ buff[], debuff[], special[] } 三类标签集合。
- patterns：
  - 旧：{ global_macros, by_code: {code: [regex,...]} }
  - 新：{ fragments(=宏), buff/debuff/special: {code: [regex,...]} }
- keywords：{ code: ["关键词A", "关键词B"] }（用于 AI 修复时的“片段佐证”）
- `load_catalog()` 负责读取/展开宏/编译正则并缓存；`get_patterns_from_catalog(compiled=True|False)` 返回按三类分组的 code→[pattern]。

正则标签建议
- `suggest_tags_grouped(monster) -> {"buff":[...],"debuff":[...],"special":[...]}`  
  从技能名/描述聚合文本匹配目录正则；对 `util_pp_drain` 额外套 `_pp_drain_strict` 二次判定（必须明确“减少/扣/降低 对手 技能次数/PP”）。
- `suggest_tags_for_monster(monster) -> [code,...]` 仅拍平并去重。

派生信号（供 derive_service 使用）
- `extract_signals(monster) -> Dict[str,object]`  
  基于正则结果与文本启发式输出进攻/生存/控制/节奏/压制相关布尔或计数信号（如 hard_cc/first_strike/pp_hits 等）。派生服务用它计算 0~120 的五系与定位。

AI 分类路径
- `ai_classify_text(text)`：构造 system prompt（只允许既定三类代码），temperature=0，`response_format=json_object`，最长 8k 字截断；LRU 缓存。
- `ai_suggest_tags_grouped(monster)`：对怪物聚合文本做分组输出。
- `ai_suggest_tags_for_monster(monster)`：与正则结果对齐并按策略选取：
  - ai：仅用 AI
  - regex：仅用正则
  - repair_union：正则 ∪ AI（AI 新增项在 `TAG_AI_REPAIR_VERIFY` 打开时需命中 `keywords` 的片段才纳入）

批量 AI 打标（后台线程）
- `start_ai_batch_tagging(ids, db_factory) -> job_id`：启动守护线程，逐 id 读取 Monster（含 skills/tags），跑策略选取的标签并 `upsert_tags+commit`。  
  进度/控制：
  - `get_ai_batch_progress(job_id)`：done/failed/percent/ETA 等（内存注册表 `_BatchRegistry`，非持久化）
  - `cancel_ai_batch(job_id)`：设置取消标记，任务逐个中断
  - `cleanup_finished_jobs(older_than_seconds=3600)`：清理已完成且超时未读的作业
- 注意：作业状态仅在当前进程内存，若多进程/重启会丢失；高并发时建议引入外部队列/任务表。

常用调用片段
- 单个怪物（正则或 AI）→ 写库并重算派生/定位
  ```
  from server.app.services import tags_service, monsters_service
  tags = tags_service.suggest_tags_for_monster(monster)  # 或 ai_suggest_tags_for_monster
  monsters_service.set_tags_and_rederive(db, monster, tags)  # 内部会 recompute & autolabel
  ```
- 获取中文名映射（展示用）
  ```
  code2cn = tags_service.get_i18n_map("zh")
  ```
- 手动强制刷新目录
  ```
  tags_service.load_catalog(force=True)
  ```

关键规则与边界
- PP 压制极慎：只有明确“减少对方技能次数/PP”才给 `util_pp_drain`（排除“PP 为 0 则…”这类条件句）。
- 目录正则异常会被忽略（尝试编译失败即跳过），避免阻塞加载。
- AI 需 `httpx` 且必须设置 `DEEPSEEK_API_KEY`；网络失败会抛出异常（上层需捕获或回退正则策略）。
- 线程模型：批量打标在**单进程内**的守护线程执行；多进程部署建议迁移到任务队列。
- 文本来源：聚合“技能名 + 描述”（两套关系均兼容），请确保导入/爬虫已尽量提供描述文本以提升召回。
- 非确定性：AI 即便 temperature=0 仍可能有轻微抖动；repair_union 可在保持召回的同时用关键词做保守校验。

自测清单
- [ ] 目录改动后 ≤TTL 自动热更新，宏展开正常，正则可编译。
- [ ] `util_pp_drain` 仅在严格叙述时出现；含“PP 为 0 则…”不应被标。
- [ ] 正则/AI/repair_union 三策略输出与期望一致（含关键词校验样例）。
- [ ] `extract_signals` 与 derive_service 计算链路可用（硬控存在时 control 信号>0 等）。
- [ ] 批量作业可创建/查询/取消/清理；重启后作业状态丢失符合预期。