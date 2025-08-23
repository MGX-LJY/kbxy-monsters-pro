file: server/app/services/types_service.py
type: service
owner: backend
updated: 2025-08-23
stability: stable
deps: [pathlib.Path, json, threading, typing]
exposes: [TypeChartService, get_service, list_types, get_chart, get_effects, get_card, get_matrix]

TL;DR（30秒）
- 读取并热更新 data/type_chart.json，提供“属性克制”查询：倍率、标注、单属性卡片、全量矩阵。
- 统一类型名规范化（兼容是否带“系”与常见别名），缺失关系按 1.0 中性补齐。
- 线程安全（文件热加载加锁），对路由直接可用的便捷函数已提供。

核心职责
1) 配置加载与索引：读取 type_chart.json，按 mtime 热更新；构建“别名→规范名”索引。  
2) 查询接口：按视角（attack/defense）返回倍率、颜色（>1 红、<1 绿、=1 黑）、排序好的下拉项。  
3) 展示数据：单属性“卡片”含强弱分桶；全局 N×N 矩阵用于热力图/表格。

type_chart.json 预期结构（示意）
- 顶层：以规范类型名为键（如 火系、木系、机械…），每项为对象：
  - attack: { 对面类型: 倍率, … }
  - defense: { 对面类型: 倍率, … }
  - attack_ordinary: [未列出但视为 1.0 的类型列表]（可选）
  - defense_ordinary: [同上]（可选）
- 未显式给出的关系自动视为 1.0。

类型名规范化（内置别名）
- 同一类型是否带“系”均可识别（如 金 与 金系）。
- 常见别名：机器/机器系→机械；翼、风/翼→翼系；音→音系。
- normalize(t) 返回规范名；未识别时回落为原文。

主要方法（对外可用）
- TypeChartService(json_path)
  - chart() -> Dict：返回完整配置（自动热载）。  
  - all_types() -> List[str]：所有规范类型名（按索引聚合去重）。  
  - normalize(t: str) -> str：名称规范化。  
  - get_multiplier(self_type, vs_type, perspective="attack") -> float：倍率查询；未命中则 1.0。  
  - color_of(mult: float) -> str：倍率到颜色映射（red/green/black）。  
  - effects(vs: str, perspective="attack", sort=None) -> Dict：  
    返回 { vs, perspective, items }；items 为 [{type, multiplier, label, color}]，默认按 attack 降序 / defense 升序（可用 sort=asc/desc 覆盖）。  
  - card(self_type: str) -> Dict：  
    返回 { type, attack: {map,list,buckets}, defense: {…} }；buckets 分为 x4(≥4.0)、x2([2,4))、up(1~2)、even(=1)、down(0.5~1)、x05(≤0.5)。未配置的对面类型自动补 1.0。若 self_type 不存在于图，抛 KeyError。  
  - matrix(perspective="attack") -> Dict：  
    返回 { perspective, types, matrix }，types 为行列同序数组，matrix 为 N×N 倍率矩阵。

模块级便捷函数（路由常用）
- get_service() -> 单例 TypeChartService（默认路径：server/app/data/type_chart.json）
- list_types() -> List[str]
- get_chart() -> Dict[str, Any]
- get_effects(vs: str, perspective="attack", sort: Optional[str]=None) -> Dict[str, Any]
- get_card(self_type: str) -> Dict[str, Any]
- get_matrix(perspective="attack") -> Dict[str, Any]

排序与展示规则
- effects：attack 视角默认“高伤优先”（倍数降序），defense 视角默认“更耐打优先”（倍数升序）；同倍率再按类型名稳定排序。label 在倍率≠1.0 时展示“类型（×倍率）”。
- card：两侧列表均按倍率降序；buckets 便于在弹框中分组展示强弱关系。
- matrix：O(N²) 计算，N 为类型数，常规规模可直接返回给前端做热力图。

热更新与并发
- 每次读接口前检查文件 mtime，变化则重载并重建索引；用 threading.Lock 保证多线程安全。
- 单例 _service 在模块加载时初始化；多进程部署各进程各自维护热更新。

错误与边界
- get_multiplier：未知 self_type 或 vs_type 均回落 1.0（中性）；但 card 要求 self_type 必须存在（否则 KeyError）。
- json 顶层不是对象会抛 ValueError；找不到文件抛 FileNotFoundError。
- normalize 未识别时返回原字符串，后续查表可能走默认 1.0。

常见用法（简要）
- 下拉标注：get_effects("火系") 或 get_effects("火", "defense")。
- 单属性弹框：get_card("水系")，读取 attack/defense 下的 buckets 与 list。
- 克制矩阵：get_matrix("attack")，前端渲染热力图或表格；types[i], types[j] 对应 matrix[i][j]。

变更影响点
- 新增/修改类型或倍率：直接编辑 type_chart.json；接口会在 TTL=文件 mtime 变化时热加载，无需重启。
- 若扩展别名，请在 _rebuild_index 的 alias 字典补充，以保证 normalize 命中。