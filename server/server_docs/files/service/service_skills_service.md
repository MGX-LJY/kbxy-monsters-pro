---
file: server/app/services/skills_service.py
type: service
owner: backend
updated: 2025-08-23
stability: beta
deps: [SQLAlchemy Session/select, server/app/models.Skill, re]
exposes: [derive_tags_from_texts, upsert_skills]

skills_service.py · 快速卡片

TL;DR（30 秒）
- 两块能力：
  1) 文本→轻量标签：从技能名/描述关键词里提取便签（如“先手/驱散/净化/加速/减伤/暴击”等）。
  2) 技能 upsert：按 (name, element, kind, power) 唯一写入 Skill；自动清洗/规范化字段与描述覆盖策略。
- 不落事务、不提交；由调用方掌握提交时机。
- 与爬虫的统一化口径需要对齐：本文件仅做**轻度**规范化（尤其 element 不改写“特/无”），若来源有“特/无”等值，建议在进入此层前统一。

功能一：从文本派生轻量标签
- 入口：`derive_tags_from_texts(texts: Iterable[str]) -> Set[str]`
- 规则：内置 KEYWORD_TAGS 正则映射（可扩展），聚合多段文本后逐条匹配，返回去重集合。
- 用途：导入/展示时做“人类可读”的便签，不等同于新三类前缀标签 `buf_/deb_/util_`。
- 示例：
  ```
  derive_tags_from_texts(["先手攻击，命中后有几率眩晕", "可消除对方增益"])
  -> {"先手","控制","驱散"}
  ```

功能二：技能唯一 upsert
- 入口：`upsert_skills(db, items) -> List[Skill]`
  - items: `[(name, element, kind, power, description), ...]`
- 唯一键：`(name, element, kind, power)`（模型层已有唯一约束 `uq_skill_name_elem_kind_power`）。
- 预清洗/规范化：
  - 名称：`_is_valid_skill_name` 至少含中文或英文字母；纯数字/连字符视为无效（跳过）。
  - element：`_norm_element` 仅裁剪空白；空串→None（不做“特/无→特殊”的强映射）。
  - kind：`_norm_kind` 将常见同义合并为 `物理/法术/特殊`（如“法攻/魔攻/法伤→法术”，“变化/辅助→特殊”）。
  - power：`_norm_power` 从字符串里抽取首个整数（无则 None）。
- 覆盖策略（description）：
  - 新建：仅当新描述“像描述”（长度/标点/关键词启发式）才写入，否则写空串。
  - 命中已有记录：只有当**新描述像描述**且（旧描述不像描述 **或** 新描述更长）时才覆盖，避免反复抹掉高质量长描述。
- 返回值：所有成功命中或新建的 `Skill` 实体（带 id），便于上层建立 Monster 关联。

用法示例
- 从 CSV/爬虫映射到入参：
  ```
  items = [
    ("青龙搅海", "水系", "法术", 135, "有几率降低对方防御"),
    ("明王咒", "特殊", "特殊", None, "本回合蓄力，下回合伤害加倍"),
  ]
  skills = upsert_skills(db, items)
  # 上层再创建 MonsterSkill 关系或通过 association_proxy 绑定
  ```
- 配合文本便签：
  ```
  tags = derive_tags_from_texts([s.description for s in skills] + [extra_text])
  ```

与爬虫/其它层的口径对齐（重要）
- 爬虫 `crawler_server.normalize_skill_element/kind` 会把 `"特"|"无"→"特殊"`、`"技能/技"→"法术"` 等做强规范；本服务只做轻度裁剪与同义收敛。
- 为避免产生“同一技能因规范化差异而出现两条记录”的情况，建议：
  1) 在进入 `upsert_skills` 前统一调用爬虫的规范化函数，或
  2) 在本文件的 `_norm_element/_norm_kind` 中扩充与爬虫一致的映射表（推荐单一真源：爬虫映射）。

性能与并发建议
- 当前实现按条查询+可能插入，批量很大时会有 N 次 SELECT；可在调用前对 `items` 按唯一键去重。
- 超大批量可先一次性查询已有键的集合（name,element,kind,power→id）做本地命中，再对缺失部分批插。
- 唯一约束冲突由数据库保证；如多进程并发导入，建议在调用方捕获 `IntegrityError` 并重试读取。

边界与陷阱
- 名称校验：纯数字/符号会被过滤（例如 `"1"`、`"-"`）；请确保来源数据正确。
- 描述覆盖：以“像描述”与长度为启发式，少数情况下可能不覆盖更优但更短的描述（可按需调整策略）。
- power 解析：仅取首个整数；遇到“90~120”“100-150”这类区间时会取 90 或 100。
- element 未强制映射“特/无→特殊”，需在上游或本层扩展避免分叉。

自测清单
- [ ] 相同 (name,element,kind,power) 重复传入仅生成一条记录，且描述按规则有/无覆盖。
- [ ] 名称为纯数字/破折号被过滤，不产生记录。
- [ ] `"变化"`/`"辅助"` 等被归并为 `"特殊"`；`"法攻/魔攻/法伤"` 归并为 `"法术"`。
- [ ] 区间威力 `"120-140"` 被解析为 `120`；空/无效威力解析为 `None`。
- [ ] `derive_tags_from_texts` 能从多段文本混合正确识别“先手/驱散/净化/减伤/暴击”等标签。