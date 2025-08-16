# server/app/services/types_service.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import threading


class TypeChartService:
    """
    负责：
      - 加载与热更新 type_chart.json
      - 类型名规范化（含别名/是否带“系”）
      - 倍率查询（attack/defense）
      - 下拉标注数据（effects）
      - 单属性克制“卡片”数据（card）——已做强弱分桶
      - 全量矩阵（matrix）——可做热力图/表格
    """

    def __init__(self, json_path: Path):
        self._path = json_path
        self._lock = threading.Lock()
        self._chart: Dict[str, Any] = {}
        self._mtime: float = 0.0
        self._index: Dict[str, str] = {}
        self._load(force=True)

    # ---------- 基础：加载/索引 ----------

    def _load(self, force: bool = False) -> None:
        with self._lock:
            if not self._path.exists():
                raise FileNotFoundError(f"type_chart.json not found: {self._path}")
            m = self._path.stat().st_mtime
            if force or m != self._mtime:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("type_chart.json must be an object at top level")
                self._chart = data
                self._mtime = m
                self._rebuild_index()

    def _rebuild_index(self) -> None:
        """
        建立“名称 → 规范名”的索引，兼容：
          - 是否带“系”（金 / 金系、翼 / 翼系等）
          - 常见别名（机器 → 机械、翼 → 翼系、风/翼 → 翼系、音 → 音系）
          - 也扫描嵌套键与 ordinary 列表，确保 union 完整
        """
        idx: Dict[str, str] = {}

        def put(src: str, canonical: str):
            if src not in idx:
                idx[src] = canonical

        # 顶层 key
        for t in self._chart.keys():
            put(t, t)
            put(t.replace("系", ""), t)

        # 嵌套出现过的类型也纳入
        for v in self._chart.values():
            for k in ("attack", "defense"):
                for t in (v.get(k) or {}).keys():
                    put(t, t)
                    put(t.replace("系", ""), t)
            for k in ("attack_ordinary", "defense_ordinary"):
                for t in (v.get(k) or []):
                    put(t, t)
                    put(t.replace("系", ""), t)

        # 常见别名
        alias = {
            "机器": "机械",
            "机器系": "机械",
            "翼": "翼系",
            "风/翼": "翼系",
            "音": "音系",
        }
        for a, b in alias.items():
            b_norm = idx.get(b, b)
            put(a, b_norm)
            put(a.replace("系", ""), b_norm)

        self._index = idx

    # ---------- 对外：读取/规范化 ----------

    def chart(self) -> Dict[str, Any]:
        self._load()
        return self._chart

    def all_types(self) -> List[str]:
        self._load()
        # 用索引的 value 去重 & 排序，保证 union 完整
        return sorted(set(self._index.values()))

    def normalize(self, t: str) -> str:
        self._load()
        s = (t or "").strip()
        return self._index.get(s) or self._index.get(s.replace("系", "")) or s

    # ---------- 核心：倍率/颜色 ----------

    def get_multiplier(self, self_type: str, vs_type: str, perspective: str = "attack") -> float:
        """
        self_type: 我方属性
        vs_type:   对面属性
        perspective: "attack"=我方打别人；"defense"=别人打我方
        """
        self._load()
        st = self.normalize(self_type)
        vt = self.normalize(vs_type)
        node = self._chart.get(st, {})
        table = node.get(perspective) or {}
        if vt in table:
            return float(table[vt])
        # 若文件里有 *_ordinary，命中按 1.0
        ordinary = node.get(f"{perspective}_ordinary") or []
        if vt in ordinary:
            return 1.0
        # 补全逻辑：未显式列出则视为中性 1.0
        return 1.0

    @staticmethod
    def color_of(mult: float) -> str:
        # 你的 UI 规范：高=红、低=绿、等于 1.0 = 黑
        return "red" if mult > 1.0 else ("green" if mult < 1.0 else "black")

    # ---------- 供 /types/effects 使用：给“下拉筛选栏”的标注/排序 ----------

    def effects(self, vs: str, perspective: str = "attack", sort: Optional[str] = None) -> Dict[str, Any]:
        """
        返回：对“对面属性=vs”时，各我方属性在该视角的倍率/文案/颜色，并按默认规则排序：
          - attack 视角：倍数降序（越疼排前）
          - defense 视角：倍数升序（越耐打排前）
        可用 sort=asc/desc 覆盖默认排序。
        """
        self._load()
        vs_norm = self.normalize(vs)
        types = self.all_types()
        items = []
        for t in types:
            m = self.get_multiplier(t, vs_norm, perspective)
            label = t if m == 1.0 else f"{t}（×{m}）"
            items.append({"type": t, "multiplier": m, "label": label, "color": self.color_of(m)})

        eff_sort = sort or ("desc" if perspective == "attack" else "asc")
        reverse = eff_sort == "desc"
        # 二级 key 用名称保证稳定
        items.sort(key=lambda x: (x["multiplier"], x["type"]), reverse=reverse)
        return {"vs": vs_norm, "perspective": perspective, "items": items}

    # ---------- 供“属性克制弹框”使用：单属性卡片（含强弱分桶+完整列表） ----------

    def card(self, self_type: str) -> Dict[str, Any]:
        """
        返回一个“卡片”结构，便于前端在弹框中展示某个属性的完整克制关系：
          - attack / defense 各自：
              - map: { 对面属性: 倍率 }
              - list: [{ vs, multiplier, color, label }]
              - buckets: 分桶（x4 / x2 / up / even / down / x05）
        """
        self._load()
        st = self.normalize(self_type)
        if st not in self._chart:
            raise KeyError(f"type '{self_type}' not found")

        def build_side(persp: str) -> Dict[str, Any]:
            table: Dict[str, float] = dict(self._chart[st].get(persp) or {})
            # 用并集补齐中性关系，保证弹框里“全类型可见”
            for t in self.all_types():
                table.setdefault(t, 1.0)

            arr = [{
                "vs": t,
                "multiplier": float(v),
                "color": self.color_of(float(v)),
                "label": t if v == 1.0 else f"{t}（×{v}）",
            } for t, v in table.items()]

            # 展示时通常按倍率从高到低
            arr.sort(key=lambda x: (-x["multiplier"], x["vs"]))

            buckets = {
                "x4":  [x for x in arr if x["multiplier"] >= 4.0],
                "x2":  [x for x in arr if 2.0 <= x["multiplier"] < 4.0],
                "up":  [x for x in arr if 1.0 < x["multiplier"] < 2.0],
                "even": [x for x in arr if x["multiplier"] == 1.0],       # ordinary
                "down": [x for x in arr if 0.5 < x["multiplier"] < 1.0],
                "x05": [x for x in arr if x["multiplier"] <= 0.5],
            }
            return {"map": table, "list": arr, "buckets": buckets}

        return {"type": st, "attack": build_side("attack"), "defense": build_side("defense")}

    # ---------- 供“全局克制图”使用：矩阵 ----------

    def matrix(self, perspective: str = "attack") -> Dict[str, Any]:
        """
        返回 N×N 的倍率矩阵：
          - types: 有序类型数组（行/列同序）
          - matrix: [[m11, m12, ...], [m21, m22, ...], ...]
        你可以在前端渲染成表格或热力图。
        """
        self._load()
        types = self.all_types()
        mat: List[List[float]] = []
        for st in types:
            row: List[float] = []
            for vt in types:
                row.append(self.get_multiplier(st, vt, perspective))
            mat.append(row)
        return {"perspective": perspective, "types": types, "matrix": mat}


# ---------- 单例与便捷函数 ----------

_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
_DEFAULT_JSON = _DATA_DIR / "type_chart.json"
_service = TypeChartService(_DEFAULT_JSON)


def get_service() -> TypeChartService:
    return _service


# 便于在路由里直接调用的函数（可选）
def list_types() -> List[str]:
    return _service.all_types()


def get_chart() -> Dict[str, Any]:
    return _service.chart()


def get_effects(vs: str, perspective: str = "attack", sort: Optional[str] = None) -> Dict[str, Any]:
    return _service.effects(vs, perspective, sort)


def get_card(self_type: str) -> Dict[str, Any]:
    return _service.card(self_type)


def get_matrix(perspective: str = "attack") -> Dict[str, Any]:
    return _service.matrix(perspective)