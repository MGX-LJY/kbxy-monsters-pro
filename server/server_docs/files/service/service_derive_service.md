---
file: server/app/services/derive_service.py
type: service
owner: backend
updated: 2025-08-23
stability: beta
deps: [SQLAlchemy Session/select, server/app/models.{Monster,MonsterDerived}, .tags_service.{extract_signals,suggest_tags_for_monster}, .monsters_service.upsert_tags]
exposes: [compute_derived, compute_derived_out, compute_and_persist, infer_role_for_monster, infer_role_details, recompute_and_autolabel, recompute_all]

# derive_service.py · 快速卡片

## TL;DR（30 秒）
- 职责：基于**六维**、**技能文本信号**与**已有样本分位**，计算派生五系（0~120），再推断**定位 role**（主攻/控制/辅助/坦克），并在必要时**补齐前缀标签**（buf_/deb_/util_）。
- 主要流程：`compute_derived_out` → 分位标准化 → 类别打分 → `_decide_role` →（可选）补标签 → 持久化 `MonsterDerived` 与 `monster.role`。
- 事务：**只写入/flush，不 commit**；由调用方（路由层）统一提交/回滚。

## 核心概念与数据来源
- 六维：`hp/speed/attack/defense/magic/resist`（从 `Monster` 读取，缺省按 0）。
- 信号：来自 `tags_service.extract_signals(monster)` 的基础信号 + 本文件的**正则补充**（如暴击、破甲、硬控、推进、PP 压制等）。
- 技能输入：兼容两类关系结构  
  - `monster.skills: [Skill 或 MonsterSkill(skill=Skill)]`  
  - `monster.monster_skills: [MonsterSkill]`  
  文本聚合并抽取关键词；技能威力用于主攻加成。
- 分位样本：从表 `MonsterDerived` 汇总历史值（如提供 `db`），用于将 0~120 的派生分映射至 0~100 **百分位**（空样本时走线性兜底）。

## 公开函数（怎么用）
- `compute_derived(monster) -> dict[str,float]`：返回五系**原始浮点**值（可>120，进位前）。
- `compute_derived_out(monster) -> dict[str,int]`：裁剪并四舍五入到 0~120。
- `compute_and_persist(db, monster) -> MonsterDerived`：计算并写入/更新 `MonsterDerived`（不 commit）。
- `infer_role_for_monster(monster, db=None) -> str`：只返回最终 `role`（若传 `db` 会用分位标准化）。
- `infer_role_details(monster, db=None) -> dict`：返回 `role/confidence/reason/scores/derived_percentile`。
- `recompute_and_autolabel(db, monster) -> MonsterDerived`：**一站式**重算派生 + 补前缀标签 + 写回 `monster.role`，并把 `role_*` 动态属性挂在返回的 `MonsterDerived` 上（便于响应透出）。
- `recompute_all(db) -> int`：对全库 Monster 逐一执行上述流程，返回处理数量。

## 公式概要（v2）
- 主攻 `offense`：以 `max(attack,magic)` 为主，`min(attack,magic)` 与 `speed` 为辅；再加成**暴击/无视防御/多段/必中/蓄力/破甲/降防降抗/标记**等信号；高威力技能（均值≥150/160）的**额外加分**；最终**封顶 130** 后再裁剪到 120。
- 生存 `survive`：`hp/defense/resist` 加权 + **治疗/护盾/减伤/反伤/免疫/净化/吸血/防抗提升/闪避**等信号。
- 控制 `control`：**硬控 > 软控**，再叠加 **降速/降命中/降攻/降魔/禁技**，以及 `0.10*speed` 的边际项。
- 节奏 `tempo`：`speed` 为主，配合**先手/再动/提速/推条/嘲讽**。
- PP 压制 `pp_pressure`：**扣PP/命中PP/驱散/禁技/偷增益/反转/转移/禁疗/疲劳/暴露**等信号线性组合。
- 归一化：`compute_derived_out` 将 0~120 的整数作为“量表分”；若提供 `db`，再通过历史样本计算**百分位（0~100）**参与定位。

## 定位逻辑（role）
1) 计算**分位空间**下的四类综合得分：  
   - 主攻：`1.00*offense + 0.35*tempo + 8.0*dps_sig - 0.15*control - 0.10*support_sig`  
   - 控制：`1.05*control + 0.20*tempo + 10*硬控 + 3.5*软控 + 2*(降速+降命中) - 0.10*offense`  
   - 辅助：`0.95*survive + 0.20*tempo + 8*(治疗+护盾) + 5*(净化+免疫) + 1.5*(防御/抗性↑) + 1.0*(转移/反转)`  
   - 坦克：`1.00*survive + 0.10*tempo + 5*(护盾+减伤) + 2*免疫 + 高HP/高Resist奖励 - 0.30*offense + 0.4*pp + 2.5*嘲讽`
2) 强规则：若**硬控存在**且控制分位 ≥ P75 → 直接“控制”；若**治疗/护盾/净化/免疫**≥2 且生存 ≥ P70 → “辅助”。
3) 常规比较：取最高两类，按差值与优先级（控制 > 辅助 > 主攻 > 坦克）决定；给出 `confidence` 与文字 `reason`。

## 标签补齐（仅当缺少 buf_/deb_/util_ 前缀）
- 若 `monster.tags` 中不含前缀标签，则调用 `suggest_tags_for_monster()` 获取建议，并通过 `upsert_tags()` 合并写回，**不覆盖**已有的非前缀标签。

## 事务与副作用
- 本服务**不 commit**；调用方需要在请求结束或任务内统一 `commit()/rollback()`。
- `recompute_and_autolabel` 会修改：`MonsterDerived`（插入/更新）、`monster.role`、必要时更新 `monster.tags`。

## 典型用法
```py
# 单个怪物：重算并落库
md = recompute_and_autolabel(db, monster)   # db.flush() 已在路由通用依赖中完成
# 仅取定位字符串（不落库）
role = infer_role_for_monster(monster, db=db)
# 全量重算
n = recompute_all(db)
```

## 边界与常见坑
- **空技能/弱文本**：信号不足时更依赖六维；结果更保守（可能“通用”或低置信度）。  
- **数据未导入分位样本**：`db` 缺失或为空时，分位退化为线性映射；线上效果会与历史分布略有偏差。  
- **关系结构不一致**：若仅填充了 `Monster.skills` 或仅 `Monster.monster_skills`，本服务均能兼容；但请保证 `description/power` 等字段在其一可用。  
- **性能**：`recompute_all` 会遍历全表，建议批处理与分页提交，避免长事务。

## 变更指南（How to change safely）
- **调权重**：集中在 `compute_derived()` 与 `_category_scores()`；调参后建议用一批金标集回归评测。  
- **新增信号**：在 `_detect_v2_signals()` 中添加正则/标签映射，并在相关打分处引用；同步更新文档与测试。  
- **改定位集**：若需新增“刺客/破盾”等类别，扩展 `_category_scores()` 与 `_decide_role()` 并更新前端枚举。  
- **多租户标签**：补齐标签时目前不区分租户；如有多用户场景需在上层服务按用户做隔离。  
- **可观测性**：在路由层把 `role/confidence/reason/derived_percentile` 透出，便于分析与调参。

## 自测清单
- [ ] 对有代表性的怪物，`compute_derived_out` 输出 0~120 的整数，单调符合预期。  
- [ ] 提供 `db` 与不提供 `db` 的定位结果差异在合理范围（分位标准化生效）。  
- [ ] 强规则命中：硬控+高控制分位 → role=控制；治疗/护盾/净化/免疫≥2+高生存 → role=辅助。  
- [ ] 补标签逻辑仅在**缺少前缀标签**时生效，且不覆盖非前缀标签。  
- [ ] `recompute_and_autolabel` 写入 `MonsterDerived` 与 `monster.role`，并能在同事务内回滚。