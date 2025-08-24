# server/app/services/normalization.py
from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

__all__ = [
    "normalize_element",
    "normalize_kind",
    "parse_power",
    "canonical_power_int",
]

# ---------- 基础工具 ----------

def _clean(s: Optional[str]) -> str:
    if s is None:
        return ""
    # 统一全角/半角、去掉首尾空白、常见控制字符
    s = unicodedata.normalize("NFKC", str(s)).strip()
    # 去除中文顿号等两侧空白
    return re.sub(r"\s+", " ", s)

def _to_lower_no_space(s: str) -> str:
    return _clean(s).lower().replace(" ", "")

# ---------- 元素（属性）规范化 ----------
# 说明：用于“技能的元素/属性”字段。约定：
#   - "特" / "无" / "无属性" / "-" 等 → 统一为 "特殊"
#   - 其它值保留原文裁剪（因为项目里系别较多，统一真源是 type_chart）
#   - 空/未知 → 返回 None
_SPECIAL_TOKENS = {"特", "特殊", "无", "無", "无属性", "无系", "—", "-", "*"}

def normalize_element(value: Optional[str]) -> Optional[str]:
    s = _clean(value)
    if not s:
        return None
    key = _to_lower_no_space(s)
    if key in { _to_lower_no_space(x) for x in _SPECIAL_TOKENS }:
        return "特殊"
    # 兼容英文/拼音少量输入
    if key in {"none", "null"}:
        return "特殊"
    return s  # 其它保持原文（已裁剪/标准化）

# ---------- 类型（物理/法术/特殊）规范化 ----------
_KIND_MAP = {
    # 物理
    "物": "物理", "物理": "物理", "普攻": "物理", "近战": "物理", "physical": "物理",
    # 法术
    "法": "法术", "法术": "法术", "技能": "法术", "技": "法术",
    "法攻": "法术", "魔攻": "法术", "法伤": "法术", "spell": "法术", "magic": "法术",
    # 特殊（变化/辅助/状态等）
    "特": "特殊", "特殊": "特殊", "变化": "特殊", "辅助": "特殊", "状态": "特殊",
    "support": "特殊", "status": "特殊",
}

def normalize_kind(value: Optional[str]) -> Optional[str]:
    s = _clean(value)
    if not s:
        return None
    key = _to_lower_no_space(s)
    # 直接映射命中
    if key in { _to_lower_no_space(k): v for k, v in _KIND_MAP.items() }:
        # 找到首个等价键
        for k, v in _KIND_MAP.items():
            if _to_lower_no_space(k) == key:
                return v
    # 常见单字简写
    if key in {"物", "wuli"}:
        return "物理"
    if key in {"法", "fashu"}:
        return "法术"
    if key in {"特", "te", "bianhua", "fuzhu"}:
        return "特殊"
    return s  # 无法识别时，保留原文（已裁剪）

# ---------- 威力解析 ----------
# 输入可以是 int、"120"、"90-120"、"90~120"、"≤120"、">=120"、"120以上" 等
# 返回：(low:int|None, high:int|None, canonical:int|None, raw:str)
_RANGE_SEP = re.compile(r"\s*(?:-|~|～|至|to)\s*", re.I)
_NUM = re.compile(r"\d+")

def parse_power(value) -> Tuple[Optional[int], Optional[int], Optional[int], str]:
    raw = _clean(value)
    if raw == "":
        return None, None, None, ""

    # 纯数字 / 可转数字
    if isinstance(value, int):
        return value, value, value, str(value)
    if raw.isdigit():
        n = int(raw)
        return n, n, n, raw

    # 提取数字
    nums = list(map(int, _NUM.findall(raw)))
    # 识别区间分隔符
    if _RANGE_SEP.search(raw) and len(nums) >= 2:
        low, high = sorted(nums[:2])
        return low, high, low, raw  # 规范：区间以 low 作为唯一键的 canonical
    # 单值 + 上下界描述
    if nums:
        n = nums[0]
        low_words = ("≥", ">=", "以上", "不小于", "greaterthan", "morethan")
        high_words = ("≤", "<=", "以下", "不大于", "lessthan")
        r_low = any(w in raw for w in low_words)
        r_high = any(w in raw for w in high_words)
        if r_low and not r_high:
            return n, None, n, raw
        if r_high and not r_low:
            return None, n, n, raw
        # 含“约/大约/左右”等 → 视为单点
        return n, n, n, raw

    # 未识别
    return None, None, None, raw

def canonical_power_int(low: Optional[int], high: Optional[int], canonical: Optional[int]) -> Optional[int]:
    """
    统一出口：数据库唯一键 ‘power’ 使用的值。
    规则：优先 canonical；无则取 low；仍无则 None。
    """
    return canonical if canonical is not None else (low if low is not None else None)


# ---------- 简单自检 ----------
if __name__ == "__main__":
    assert normalize_element(" 特 ") == "特殊"
    assert normalize_element("无属性") == "特殊"
    assert normalize_element("火系") == "火系"

    assert normalize_kind("技") == "法术"
    assert normalize_kind("变化") == "特殊"
    assert normalize_kind("物理") == "物理"

    assert parse_power("90~120")[2] == 90
    assert parse_power("≥120")[0] == 120
    assert parse_power("≤120")[1] == 120