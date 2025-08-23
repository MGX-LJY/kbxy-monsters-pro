---
file: server/app/services/crawler_server.py
type: service
owner: backend
updated: 2025-08-23
stability: beta
deps: [DrissionPage.SessionPage, requests, bs4/BeautifulSoup, bs4.UnicodeDammit, re, logging]
exposes: [Kabu4399Crawler, SkillRow, MonsterRow, normalize_skill_element, normalize_skill_kind, classify_acq_type, pick_acquire_text, _to_public_json]

# crawler_server.py · 快速卡片

## TL;DR（30 秒）
- 职责：抓取 4399【卡布西游-妖怪大全】详情页，解析**六维**、**技能表**、**推荐配招**、**获取渠道**并推断**元素（系别）**，产出轻量 JSON。
- 解析策略：优先 **DrissionPage**（更稳的 DOM 选择器），失败则回退 **requests + UnicodeDammit**；核心解析用 **BeautifulSoup** 完成。
- 重要约定：对**技能属性/类型**做规范化映射（“特/无→特殊”，“技能/技→法术”，“状态/变化/辅助→特殊”）。
- 获取渠道：通过**候选片段收集 + 评分**挑选最可信一句，再用**正则分类器**映射为 `type`（如“活动获取宠物/可捕捉宠物/兑换/商店/BOSS宠物/任务获取/超进化/其它”）并给出 `new_type`（可获取？）与 `method`（原句）。
- 常见坑
  1) 站点结构与表头会变；解析使用了**多层兜底**与**启发式**，但**不保证 100% 正确**（尤其是获取渠道）。  
  2) DrissionPage 需要可用浏览环境；在无图形/权限受限环境可能失败，依赖 requests 兜底。  
  3) 抓取频率受限：已内置**随机节流**与**重试**，仍可能触发风控；建议加代理/延迟。  
  4) `new_type` 为“当期可获取”的**推断**，不作为**评测正确基准**（仅供提示与人工复核）。

## 数据模型（dataclass）
- `SkillRow`：`name, level?, element, kind, power?, description`
- `MonsterRow`：`name, element?, hp/speed/attack/defense/magic/resist, source_url, img_url?, type?, new_type?, method?, series_names[], skills[], recommended_names[], selected_skills[]`
- 均为**爬虫内部结构**；对外用 `_to_public_json(MonsterRow)` 抽取核心字段。

## 公开 API（函数/类）
| 名称 | 签名(简) | 作用 | 备注 |
|---|---|---|---|
| `normalize_skill_element` | (e:str\|None)->str\|None | 规范化技能属性 | `"特"/"无"→"特殊"` |
| `normalize_skill_kind` | (k:str\|None)->str\|None | 规范化技能类型 | `"技能"/"技"→"法术"；"状态/变化/辅助/特"→"特殊"` |
| `classify_acq_type` | (acq_text:str)->(type?:str, new?:bool) | 获取渠道分类 + 是否当前可获取 | 基于规则/正则与日期提示 |
| `pick_acquire_text` | (soup)->str | 从页面提取“获取方式/分布地”一句 | 表格+文本候选收集+评分 |
| `Kabu4399Crawler.fetch_detail` | (url)->MonsterRow\|None | 抓取**单个详情页**并解析 | 先 Drission，再 requests |
| `Kabu4399Crawler.crawl_all` | (persist?:callable)->Generator[MonsterRow] | 遍历列表页→详情页 | 支持 `persist(mon)` 钩子 |
| `_to_public_json` | (MonsterRow)->dict | 输出精简 JSON | 仅核心字段 |

## 抓取流程与数据流
1. **预热**：访问图鉴根目录拿站点 Cookie。  
2. **列表页**：遍历 `BASE/ROOT` 与 `CANDIDATE_SLUGS`（系别列表）生成若干列表页 → 抽取满足 `.../yaoguaidaquan/...*.html` 的详情链接，去重后产出。  
3. **详情页**：  
   - **六维表**：扫描表格，优先检测包含“种族值/资料/体力/速度/攻击/防御/法术/抗性”的表 → 推断每行的“名字 + 后续六列数字”。  
   - **技能表**：寻找含“技能表/技能名称/类型”的表 → 解析 `name/level/element/kind/power/description`，并做**规范化**。  
   - **推荐配招**：表格首列含“推荐配招/推荐技能”的行，解析技能名列表，去噪/去重。  
   - **元素（系别）推断**：URL 路径 slug → 面包屑文本 → 技能属性统计（多策略择优）。  
   - **获取渠道**：`pick_acquire_text()` 在文章主体内提取最佳一句 → `classify_acq_type()` 输出 `type/new_type` 并保留原始 `method`。  
   - **精选技能**：若有推荐配招则用推荐映射到 `skills`；没有则按**威力阈值/特殊关键词**自动挑选。  
4. 产物：`MonsterRow`（含 `skills/recommended_names/selected_skills` 等）→ 可通过 `_to_public_json` 下发给接口层或直接返回。

## 获取渠道提取（算法要点）
- **候选收集**：  
  - **表格**：在 `table/tr/td` 里找包含“获得/获取/分布地”的单元格或行；按“获得方式/获取方式/获得：/获取：/分布地：”加权。  
  - **正文**：扫描 `p/li/div/section/span`，按句拆分，只保留含“获/获取/可获得”或“分布地：”的句子。  
- **清洗与评分**：去全角/空白/噪声；过滤“无/未知/暂无”等否定、以及广告/攻略类阻断词；对出现**日期**、“获得方式”表述、若干正向词（罗盘/商店/活动/挑战…）加分。  
- **结果**：取分数最高的一句作为 `method`；再用 `PATTERNS`（有序正则）映射 **type**，并通过 `_UNAVAILABLE/_AVAILABLE_HINT/日期词**起**` 判定 `new_type`。

> 评测提醒：**type/new_type/method 是启发式推断**，不作为“原版 crawler_server.py 解析正确基准”。

## 配置与可调参数
- `throttle_range=(0.6,1.2)`：请求间隔的随机范围（秒）。  
- `max_retries=3`：详情/列表页请求失败的重试次数。  
- `timeout=15.0`：网络请求超时（秒）。  
- `headers`：附加 HTTP 头；默认设置 UA/语言/Referer。  
- `CANDIDATE_SLUGS` / `SLUG2ELEM`：列表页路径与元素映射（可扩展）。

## 可观测性与容错
- 失败日志：`log.warning/log.info/log.exception`（包含 URL 与重试次数）。  
- 回退路径：DrissionPage 失败→requests 获取并用 `UnicodeDammit` 解码。  
- 解析稳健性：表结构/顺序变化时，多处使用**近似匹配**与**模糊定位**（表头关键词、数字列计数、正则提取）。  
- 去重：`seen_urls` 防重复抓取；系列页返回多行时选择**六维和最大**的作为“最佳条目”。

## 使用示例
- **单页抓取**
  - `crawler = Kabu4399Crawler(); mon = crawler.fetch_detail(url)`
  - `json_obj = _to_public_json(mon)` → 直接作为 `/api/v1/crawl/fetch_one` 的响应体。
- **全站遍历**
  - `for mon in crawler.crawl_all(persist=example_persist): ...`  
  - 通过 `persist(mon: MonsterRow)` 将结果写入 DB/队列；示例 `example_persist` 记录了基本摘要。

## 变更指南（How to change safely）
- **站点结构变更**：优先更新 `pick_main_container/表头识别/技能表识别`；再调整获取渠道 `PATTERNS/ACQ_KEYWORDS`。  
- **规则收敛**：将获取渠道分类/元素推断/精选技能的阈值与模式提取到**可配置表**，便于 A/B 与灰度。  
- **并发与限速**：大量抓取时上调 `throttle_range` 并拆批；必要时加入代理池与失败队列。  
- **健壮性提升**：对 `fetch_detail` 增加“空字段回退/默认值”；对 `_bs4_parse_stats_table` 加更多表头别名。  
- **法务/礼貌抓取**：遵守目标站点 robots/ToS；设置合理 UA 与速率；如对方要求请停止抓取。  
- **产物稳定**：保持 `_to_public_json` 字段名与接口层 Schema 对齐（如 `selected_skills[]` 的键名与类型）。

## 自测清单
- [ ] 对典型详情页可稳定解析出：`name + 6 维 + 至少 1 个技能`。  
- [ ] 存在“推荐配招”的页面，`selected_skills` 优先依据推荐；否则采用阈值/关键词自动挑选。  
- [ ] 获取渠道：能从正文或表格中提取一句合理 `method`，并给出非空 `type`（大类）或 `new_type`（可获取提示）。  
- [ ] 元素推断：URL slug、面包屑、技能统计至少命中其一；冲突时以 URL/面包屑为先。  
- [ ] 错误容忍：Drission 失效时 requests 兜底依然可解析大多数页面；网络错误在重试后跳过不中断整体。  
- [ ] 全站遍历：`iter_detail_urls` 能产出去重后的详情链接集合；`crawl_all` 在持久化失败时只记录错误不中断主循环。