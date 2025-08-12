# server/app/routes/importing.py
from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
import csv
from io import StringIO
from typing import List, Dict, Any, Tuple, Optional, Set
import re

from ..db import SessionLocal
from ..models import Monster
from ..services.skills_service import upsert_skills
from ..services.monsters_service import upsert_tags
from ..services.derive_service import compute_and_persist

router = APIRouter(prefix="/import", tags=["import"])

# =========================
# Pydantic I/O
# =========================
class ImportPreviewOut(BaseModel):
    columns: List[str]
    total_rows: int
    sample: List[Dict[str, Any]]
    hints: List[str] = []


class ImportCommitOut(BaseModel):
    inserted: int
    updated: int
    skipped: int
    errors: List[Dict[str, Any]] = []


# =========================
# DB Session
# =========================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================
# Helpers
# =========================
def _decode_upload(file: UploadFile) -> str:
    """
    统一按 utf-8 读取；自动去 BOM；抛错给前端提示。
    """
    try:
        raw = file.file.read()
        if isinstance(raw, bytes):
            text = raw.decode("utf-8-sig")  # 兼容带 BOM
        else:
            text = str(raw)
        return text
    except Exception:
        raise HTTPException(status_code=400, detail="无法读取文件（请用 UTF-8 编码）")


def _sniff_dialect(sample: str) -> csv.Dialect:
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=",\t;")
    except Exception:
        dialect = csv.excel
        dialect.delimiter = ","
    return dialect


def _norm_key_map() -> Dict[str, str]:
    """
    允许大小写/下划线/中划线变体，以及常见中文同义。
    仅保留我们这一版需要的字段。
    """
    pairs = {
        "element": "element", "元素": "element", "系别": "element",
        "name_repo": "name_repo", "namefinal_repo": "name_repo", "仓库名": "name_repo",
        "name_final": "name_final", "名称": "name_final", "名字": "name_final",

        "hp": "hp", "体力": "hp",
        "speed": "speed", "速度": "speed",
        "attack": "attack", "攻击": "attack",
        "defense": "defense", "防御": "defense",
        "magic": "magic", "法术": "magic",
        "resist": "resist", "抗性": "resist",

        "total": "total", "合计": "total", "总和": "total",
        "summary": "summary", "总结": "summary", "简介": "summary",

        "skill_1_name": "skill_1_name", "技能1": "skill_1_name",
        "skill_1_desc": "skill_1_desc", "技能1描述": "skill_1_desc",
        "skill_2_name": "skill_2_name", "技能2": "skill_2_name",
        "skill_2_desc": "skill_2_desc", "技能2描述": "skill_2_desc",

        # 可选
        "tags": "tags", "标签": "tags",
        "role": "role", "定位": "role",
    }
    m: Dict[str, str] = {}
    for k, v in pairs.items():
        m[k] = v
        m[k.lower()] = v
        m[k.replace("-", "_").lower()] = v
    return m


def _normalize_headers(headers: List[str]) -> Tuple[List[str], Dict[int, str]]:
    """
    统一表头 => 我们内部 key；返回 (标准列名列表, 位置->key 映射)
    """
    norm = _norm_key_map()
    cols = []
    idx_map: Dict[int, str] = {}
    for i, h in enumerate(headers or []):
        k = (h or "").strip()
        key = norm.get(k) or norm.get(k.lower()) or norm.get(k.replace("-", "_").lower())
        cols.append(key or k)
        if key:
            idx_map[i] = key
    return cols, idx_map


def _get(row: Dict[str, Any], *keys: str, default=None):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def _to_float(v) -> float:
    try:
        if v in (None, "", "NULL", "null"):
            return 0.0
        return float(str(v).strip())
    except Exception:
      return 0.0


def _split_tags(v: Optional[str]) -> List[str]:
    if not v:
        return []
    s = str(v)
    if "，" in s and "," not in s:
        parts = [p.strip() for p in s.split("，")]
    else:
        parts = [p.strip() for p in s.split(",")]
    return [p for p in parts if p]


def _pick_skill_pairs(row: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    只解析 (name, desc) 对；不再需要 *_is_core 字段。
    """
    out: List[Tuple[str, str]] = []
    s1n = (_get(row, "skill_1_name") or "").strip()
    s1d = (_get(row, "skill_1_desc") or "").strip()
    s2n = (_get(row, "skill_2_name") or "").strip()
    s2d = (_get(row, "skill_2_desc") or "").strip()
    if s1n:
        out.append((s1n, s1d))
    if s2n:
        out.append((s2n, s2d))
    return out


# —— 元素规范化（把“金系/金”统一成“金”等等；未知保持原样） —— #
_ELEMENT_ALIAS = {
    "金系": "金", "木系": "木", "水系": "水", "火系": "火", "土系": "土",
    "风系": "风", "雷系": "雷", "冰系": "冰", "毒系": "毒", "妖系": "妖",
    "光系": "光", "暗系": "暗", "音系": "音",
}
def _normalize_element(val: str) -> str:
    s = (val or "").strip()
    if not s:
        return s
    return _ELEMENT_ALIAS.get(s, s)


# —— 导入时若 CSV 未提供 role/tags，可做轻量推断 —— #
_CTRL_PAT = [r"眩晕", r"昏迷", r"束缚", r"窒息", r"冰冻", r"睡眠", r"混乱", r"封印", r"禁锢"]
_SLOW_ACC_PAT = [r"降速", r"速度下降", r"命中下降", r"降低命中"]
_MULTI_HIT = [r"多段", r"连击", r"2~3次", r"3~6次", r"三连"]
_CRIT_OR_IGN = [r"暴击", r"必中", r"无视防御", r"破防"]
_SURVIVE = [r"回复", r"治疗", r"减伤", r"免疫", r"护盾"]
_FIRST = [r"先手", r"先制"]
_SPEED_UP = [r"加速", r"提速", r"速度提升"]
_PP = [r"能量消除", r"扣PP", r"减少技能次数", r"降技能次数"]

def _has_any(patterns: List[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)

def _infer_role_and_tags(m: Monster, existed: Optional[List[str]] = None) -> Tuple[str, List[str]]:
    """
    极简推断：当 CSV 未提供 role/tags 时使用。
    """
    existed_set: Set[str] = set((existed or []))

    # 原始六维
    hp, spd, atk, defe, mag, resi = (m.hp or 0), (m.speed or 0), (m.attack or 0), (m.defense or 0), (m.magic or 0), (m.resist or 0)

    # 技能文本
    parts: List[str] = [m.name_final or ""]
    for s in (m.skills or []):
        if s.name: parts.append(s.name)
        if s.description: parts.append(s.description)
    text = " ".join(parts)

    tags: List[str] = []

    # 统计类标签
    if spd >= 110: tags.append("高速")
    if atk >= 115: tags.append("强攻")
    if hp >= 115 or (defe + mag) / 2 >= 105 or resi >= 110: tags.append("耐久")
    if _has_any(_FIRST, text): tags.append("先手")
    if _has_any(_MULTI_HIT, text): tags.append("多段")
    if _has_any(_CTRL_PAT, text): tags.append("控制")
    if _has_any(_PP, text): tags.append("PP压制")
    if _has_any(_SURVIVE, text): tags.append("回复/增防")

    # 去重 + 与已存在合并
    merged: List[str] = []
    seen: Set[str] = set(existed_set)
    for t in tags + list(existed_set):
        if t and t not in seen:
            merged.append(t); seen.add(t)

    # 角色推断（只在 role 为空时）
    offensive = atk >= 115 or _has_any(_CRIT_OR_IGN + _MULTI_HIT, text)
    controlish = _has_any(_CTRL_PAT + _SLOW_ACC_PAT, text)
    supportish = _has_any(_SURVIVE + _SPEED_UP, text)
    tanky = hp >= 115 or resi >= 115

    if offensive and not controlish and not supportish:
        role = "主攻"
    elif controlish and not offensive:
        role = "控制"
    elif supportish and not offensive:
        role = "辅助"
    elif tanky and not offensive:
        role = "坦克"
    else:
        role = "通用"

    return role, merged


# =========================
# Preview
# =========================
@router.post("/preview", response_model=ImportPreviewOut)
async def preview(file: UploadFile = File(...)):
    text = _decode_upload(file)
    dialect = _sniff_dialect(text[:3000])
    reader = csv.reader(StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="空文件")

    headers = [h.strip() for h in rows[0]]
    _, idx_map = _normalize_headers(headers)

    # 采样
    sample_dicts: List[Dict[str, Any]] = []
    for r in rows[1:11]:
        d: Dict[str, Any] = {}
        for i, cell in enumerate(r):
            key = idx_map.get(i)
            if key:
                d[key] = cell
        if d:
            sample_dicts.append(d)

    hints: List[str] = []
    required = ["element", "name_final", "hp", "speed", "attack", "defense", "magic", "resist"]
    missing = [k for k in required if k not in idx_map.values()]
    if missing:
        hints.append(f"缺少字段: {', '.join(missing)}")

    return ImportPreviewOut(
        columns=[c for c in idx_map.values()],
        total_rows=max(0, len(rows) - 1),
        sample=sample_dicts,
        hints=hints,
    )


# =========================
# Commit
# =========================
@router.post("/commit", response_model=ImportCommitOut)
async def commit(file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = _decode_upload(file)
    dialect = _sniff_dialect(text[:3000])
    reader = csv.reader(StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="空文件")

    headers = [h.strip() for h in rows[0]]
    _, idx_map = _normalize_headers(headers)

    # 必填检查
    required = ["element", "name_final", "hp", "speed", "attack", "defense", "magic", "resist"]
    missing = [k for k in required if k not in idx_map.values()]
    if missing:
        raise HTTPException(status_code=400, detail=f"缺少字段: {', '.join(missing)}")

    inserted = updated = skipped = 0
    errors: List[Dict[str, Any]] = []

    for line_no, r in enumerate(rows[1:], start=2):
        try:
            row: Dict[str, Any] = {}
            for i, cell in enumerate(r):
                key = idx_map.get(i)
                if key:
                    row[key] = cell

            name_final = (row.get("name_final") or "").strip()
            if not name_final:
                skipped += 1
                continue

            # 先按 name_final 查；预加载集合关系，避免后续 N+1
            m = db.execute(
                select(Monster)
                .where(Monster.name_final == name_final)
                .options(selectinload(Monster.skills), selectinload(Monster.tags), selectinload(Monster.derived))
            ).scalar_one_or_none()

            is_new = False
            if not m:
                m = Monster(name_final=name_final, name_repo=(row.get("name_repo") or "").strip() or None)
                db.add(m)
                db.flush()  # 确保 m.id 存在，后面能建关联
                is_new = True

            # 基本信息
            element = _normalize_element((row.get("element") or "").strip())
            if element:
                m.element = element

            role_from_csv = (row.get("role") or "").strip()

            # 原始六维
            m.hp = _to_float(row.get("hp"))
            m.speed = _to_float(row.get("speed"))
            m.attack = _to_float(row.get("attack"))
            m.defense = _to_float(row.get("defense"))
            m.magic = _to_float(row.get("magic"))
            m.resist = _to_float(row.get("resist"))

            # 说明/摘要 & raw_stats
            summary = (row.get("summary") or "").strip()
            ex = m.explain_json or {}
            if summary:
                ex["summary"] = summary
            ex["raw_stats"] = {
                "hp": m.hp,
                "speed": m.speed,
                "attack": m.attack,
                "defense": m.defense,
                "magic": m.magic,
                "resist": m.resist,
                "sum": m.hp + m.speed + m.attack + m.defense + m.magic + m.resist,
            }
            m.explain_json = ex

            # 技能（覆盖式写入）
            skill_pairs = _pick_skill_pairs(row)
            if skill_pairs:
                if m.skills is None:
                    m.skills = []
                else:
                    m.skills.clear()
                skills = upsert_skills(db, skill_pairs)  # 返回 session 中的 Skill 对象
                for s in skills:
                    m.skills.append(s)
                # 记录 skill_names
                ex = m.explain_json or {}
                ex["skill_names"] = [s.name for s in m.skills]
                m.explain_json = ex

            # 标签（CSV 内带）→ upsert；否则留空，后面尝试自动推断
            tags_from_csv: List[str] = []
            if "tags" in row and row.get("tags"):
                tags_from_csv = _split_tags(str(row.get("tags")))
                m.tags = upsert_tags(db, tags_from_csv)

            # 若 role/tags 未提供，则自动推断一份（轻量规则）
            if not role_from_csv or role_from_csv.strip() == "":
                inferred_role, inferred_tags = _infer_role_and_tags(m, existed=tags_from_csv)
                m.role = inferred_role
                if not tags_from_csv:
                    m.tags = upsert_tags(db, inferred_tags)
            else:
                m.role = role_from_csv

            # 计算并落库派生五维（包含 pp_pressure；如果文本中无相关词，自然会是 0）
            compute_and_persist(db, m)

            updated += 0 if is_new else 1
            inserted += 1 if is_new else 0

        except Exception as e:
            errors.append({"line": line_no, "error": str(e), "row": r})
            skipped += 1

    db.commit()
    return ImportCommitOut(
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )