file: server/app/routes/crawl.py
type: route
owner: backend
updated: 2025-08-23
stability: stable
deps: [server/app/db.py, server/app/models.py, server/app/services/crawler_service.py, server/app/services/skills_service.py, server/app/services/derive_service.py]
exposes: [/api/v1/crawl/samples(GET|POST), /api/v1/crawl/fetch_one(GET|POST), /api/v1/crawl/crawl_all(POST)]

TL;DR（30秒）
- 4399 图鉴爬虫路由：抓样本、抓单页、全量抓取并入库。  
- 输出的技能字段在路由层即做统一映射（element/kind 规范化，过滤“推荐配招”等噪声）。  
- 入库以 Monster.name 唯一；Skill 全局去重唯一键为 (name, element, kind, power)，description 不参与唯一但会保存。

职责与边界
- 做什么：调用爬虫抓取详情；对外返回精简且已规范化的怪物/技能字段；可选择写库并触发派生/自动标签。  
- 不做什么：反爬处理/重试策略暴露；并发抓取；长任务调度；鉴权/限流。

HTTP 端点
- GET|POST /api/v1/crawl/samples  
  - 作用：从列表页遍历抓若干条带精选技能的样本，返回数组。幂等：是（读取）。
- GET /api/v1/crawl/fetch_one?url=...  
  - 作用：抓取单个详情页并返回规范化 payload；失败返回 {"detail":"fetch failed"}。幂等：是（读取）。
- POST /api/v1/crawl/fetch_one  
  - 作用：同 GET，但从 JSON Body 中读取 {"url": "..."}。
- POST /api/v1/crawl/crawl_all  
  - 作用：全量/批量爬取并入库；支持限制 slugs、覆盖/跳过逻辑；逐条提交事务。幂等：取决于 skip_existing/overwrite 组合（见下）。

查询参数/请求体（节选）
- /samples：limit（int，默认10，1..100）。  
- /fetch_one (POST Body)：{"url": string}。  
- /crawl_all (POST Body)：  
  - limit?: int —— 最多处理的入库条数（insert+update 总和）。  
  - overwrite: bool = false —— True 覆盖基础字段；False 仅补齐空字段。  
  - skip_existing: bool = true —— True 且库中已存在同名则跳过。  
  - slugs?: string[] —— 限定候选 slug（内部设置 crawler.CANDIDATE_SLUGS）。  
  - derive: bool = true —— 入库后是否重算派生并自动贴标签。

输入/输出（要点）
- 对外 payload（_to_payload）：  
  - name, element, hp, speed, attack, defense, magic, resist, type, new_type, method, selected_skills[]。  
  - selected_skills 项（_skill_public）：{name, element(规范化), kind(规范化), power, description, level}；过滤“推荐配招/推荐技能/推荐配招：”等标题噪声。
- /crawl_all 响应：{ok, fetched, inserted, updated, skills_changed, skipped}。

依赖与数据流
- 爬虫：services.crawler_service.Kabu4399Crawler  
  - iter_list_pages/iter_detail_urls → fetch_detail(url) → MonsterRow/SkillRow。  
- 规范化：normalize_skill_element / normalize_skill_kind（在路由层也复用）。  
- 入库：_upsert_one → services.skills_service.upsert_skills（批量 upsert Skill）→ 建立 MonsterSkill 关联 → services.derive_service.recompute_and_autolabel（可选）。  
- DB 会话：/crawl_all 内部使用 SessionLocal()；_upsert_one 依赖传入 Session。

事务与幂等
- 事务：/crawl_all 逐条怪物入库并 db.commit()；单条失败不影响已提交记录。  
- 幂等：  
  - skip_existing=true 时，多次运行主要产生 skipped；  
  - skip_existing=false 且 overwrite=false 时，多次运行仅补齐空字段（近似幂等）；  
  - overwrite=true 时，多次运行会重复覆盖（非幂等）。  
- Skill 去重唯一键：(name, element(规范化), kind(规范化), power)；description 不参与唯一，但会被写入/更新到 Skill.description；MonsterSkill 若已存在则仅在字段为空时补 level/description，并将 selected 置 true。

错误与可观测性
- /fetch_one 抓取失败返回 {"detail":"fetch failed"}；其余异常未显式捕获，依赖全局错误处理中间件。  
- 未显式记录日志（log 定义未使用）；建议在抓取失败、入库冲突、派生失败处增加关键日志。  
- 无速率限制/鉴权头处理。

示例（最常用）
- 抓 5 条样本：curl "http://127.0.0.1:8000/api/v1/crawl/samples?limit=5"  
- 抓单页（GET）：curl "http://127.0.0.1:8000/api/v1/crawl/fetch_one?url=https://news.4399.com/kabuxiyou/yaoguaidaquan/xxx.html"  
- 抓单页（POST）：curl -X POST -H "Content-Type: application/json" -d '{"url":"https://news.4399.com/kabuxiyou/yaoguaidaquan/xxx.html"}' http://127.0.0.1:8000/api/v1/crawl/fetch_one  
- 全量入库（默认跳过已存在）：curl -X POST -H "Content-Type: application/json" -d '{"skip_existing":true,"limit":100}' http://127.0.0.1:8000/api/v1/crawl/crawl_all  
- 覆盖入库并重算派生：curl -X POST -H "Content-Type: application/json" -d '{"overwrite":true,"derive":true,"limit":50}' http://127.0.0.1:8000/api/v1/crawl/crawl_all  
- 指定 slugs：curl -X POST -H "Content-Type: application/json" -d '{"slugs":["shuixi","huoxi"]}' http://127.0.0.1:8000/api/v1/crawl/crawl_all

常见坑（Top 10）
1) Skill 唯一键为 4 元组（name, element, kind, power），与备份恢复（可能使用 5 元组含 description）存在差异，容易出现“同名不同描述”的并行记录策略冲突。  
2) overwrite=false 仅补齐“空值”；已有非空但不准确的字段不会被更新。  
3) selected_skills 会去重并保留“后出现”的描述与 level；来源页顺序改变可能导致写入的描述不同。  
4) /crawl_all 按怪物逐条提交；中途失败不会回滚已提交的记录，批次一致性需由上层保证。  
5) skip_existing=true 依据 name 判断存在；若站点更名或同名不同形态将被跳过。  
6) 依赖爬虫的 HTML 结构；站点改版可能导致 fetch_detail 返回 None，从而大量 skipped。  
7) CANDIDATE_SLUGS 通过 Body.slugs 动态覆盖，仅影响本次调用。  
8) MonsterSkill 已存在时仅在空值时补 level/description；想强制更新需扩展逻辑或传 overwrite 的更细粒度控制。  
9) 路由层未做并发/速率限制；全量抓取可能压测目标站点与本地 DB。  
10) /samples 与 /fetch_one 返回的不入库，字段规范化与过滤逻辑与入库逻辑一致，但不会写派生/标签。

变更指南（How to change safely）
- 统一 Skill 唯一策略：若要改为 5 元组，请同时更新 skills_service.upsert_skills 与 backup/restore 流程，并编写迁移脚本去重合并。  
- 扩展 payload 字段：在 _to_payload 增字段前先确认前端/导入方的兼容性；保持字段名稳定。  
- 性能与稳健：为爬虫增加重试与节流；为 /crawl_all 增加批量 commit 或流水线队列；考虑 dry-run 统计模式。  
- 可观测性：增加抓取/入库关键日志与指标（fetched/inserted/updated/skipped、耗时、失败原因 TopN）。

术语与约定
- 规范化映射：normalize_skill_element（"特"|"无"→"特殊"；单字元素→"X系"）/normalize_skill_kind（"技能/技"→"法术"；"状态/变化/辅助/特"→"特殊"）。  
- “精选技能”：指页面中标注的推荐或高优先级技能，路由层会过滤标题性噪声后输出。  
- 派生与自动标签：recompute_and_autolabel 在入库时按需调用，读取接口不落库。