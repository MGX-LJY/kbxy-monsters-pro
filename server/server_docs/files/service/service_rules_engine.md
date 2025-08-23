---
file: server/app/services/rules_engine.py
type: service
owner: backend
updated: 2025-08-23
stability: beta
deps: [dataclasses, typing]
exposes: [ScoreResult, DEFAULT_WEIGHTS, calc_scores]

# rules_engine.py · 快速卡片

## TL;DR（30 秒）
- 职责：用**线性权重**对五个基础分（`base_offense/survive/control/tempo/pp`）做加权，输出分数与一组**粗粒度标签**（强攻/耐久/控场/速攻/PP压制）。
- 特点：无数据库、无副作用、可插拔；返回同时包含完整 `explain`（权重、输入、分数、标签）。
- 现状：依赖 `base_*` 字段，已与新版数据结构（直接存六维 + 由 `derive_service` 计算派生五系）存在**脱节**；建议仅用于导入阶段的“简易打标”。

## 输入 / 输出
- 输入：`calc_scores(monster: dict, weights: dict|None=None)`
  - 期望键：`base_offense/base_survive/base_control/base_tempo/base_pp`（缺省按 0）
  - 可通过 `weights` 覆写默认权重（全部默认为 1.0）
- 输出：`ScoreResult`（dataclass）
  - `offense/survive/control/tempo/pp: float`
  - `tags: List[str]`（阈值规则生成）
  - `explain: Dict`：
    - `weights`（最终使用的权重）
    - `formula: "linear@v2025-08-12"`
    - `inputs`（原样回显 base_*）
    - `score`（各项分数）
    - `tags`（同上）

## 标签规则（默认阈值）
- `强攻`：`offense >= 120`
- `耐久`：`survive >= 120`
- `控场`：`control >= 120`
- `速攻`：`tempo >= 110`
- `PP压制`：`pp >= 95`
> 阈值与权重均可在调用侧通过 `weights` 或外部常量调整。

## 典型用法
```py
from server.app.services.rules_engine import calc_scores, DEFAULT_WEIGHTS

m = {
  "base_offense": 128, "base_survive": 92, "base_control": 77,
  "base_tempo": 115, "base_pp": 96
}
res = calc_scores(m)               # 线性加权
print(res.tags)                    # ["强攻","速攻","PP压制"]
print(res.explain["score"]["pp"])  # 96.0
```

## 与新版体系的协作/迁移建议
- 若项目已采用 `derive_service` 的**派生五系**（0~120）：
  - 方案 A（保守）：继续在**导入预览/快速打标**阶段使用本规则；落库/展示走 `derive_service`。
  - 方案 B（替换）：用派生五系替代本文件的 `base_*`：
    - `base_offense <- derived.offense`
    - `base_survive <- derived.survive`
    - `base_control <- derived.control`
    - `base_tempo   <- derived.tempo`
    - `base_pp      <- derived.pp_pressure`
    然后按需调低本文件阈值（派生值范围同为 0~120，但分布不同）。
  - 方案 C（弃用）：在导入后直接调用 `recompute_and_autolabel`，以统一口径输出标签与定位。
- 若仍从**六维**推导 `base_*`，可采用一个最小映射（示例）：
  - `base_offense = max(attack, magic)`
  - `base_survive = hp`
  - `base_control = (defense + magic)/2`
  - `base_tempo   = speed`
  - `base_pp      = resist`

## 常见坑
- `base_*` 缺失时默认为 0，可能导致全部不触发标签；请在导入前做字段映射或使用上面的派生替代方案。
- 权重相乘后会改变阈值的相对意义；调权的同时也应同步调整阈值。
- 本规则对**技能文本/效果**完全无感知，仅做数值线性合成；需要更细的定位请使用 `derive_service`。

## 自测清单
- [ ] `weights` 覆盖后 `explain["weights"]` 与分数一致。
- [ ] 不同 `base_*` 组合能正确触发/不触发对应标签。
- [ ] 与导入流程集成时，`explain["inputs"].raw_stats` 等上游追加信息不被覆盖（由调用方合并）。