# server/app/routes/importing.py
from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
import csv
from io import StringIO
from typing import List, Dict, Any, Tuple, Optional

from ..db import SessionLocal
from ..models import Monster
from ..services.skills_service import upsert_skills
from ..services.monsters_service import upsert_tags
from ..services.derive_service import compute_and_persist
from ..services.tags_service import (
    normalize_element,
    infer_role_and_tags_for_monster,
)

router = APIRouter(prefix="/import", tags=["import"])

# ---------- IO ----------
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

# ---------- DB ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- Helpers ----------
def _decode_upload(file: UploadFile) -> str:
    try:
        raw = file.file.read()
        return raw.decode("utf-8-sig") if isinstance(raw, bytes) else str(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="无法读取文件（请用 UTF-8 编码）")

def _sniff_dialect(sample: str) -> csv.Dialect:
    try:
        sniffer = csv.Sniffer()
        return sniffer.sniff(sample, delimiters=",\t;")
    except Exception:
        d = csv.excel
        d.delimiter = ","
        return d

def _norm_key_map() -> Dict[str, str]:
    pairs = {
        "element": "element", "元素": "element", "系别": "element",
        "name_repo": "name_repo", "仓库名": "name_repo",
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
        # 可选（本版忽略 CSV tags，不落库）
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
    norm = _norm_key_map()
    cols, idx_map = [], {}
    for i, h in enumerate(headers or []):
        k = (h or "").strip()
        key = norm.get(k) or norm.get(k.lower()) or norm.get(k.replace("-", "_").lower())
        cols.append(key or k)
        if key: idx_map[i] = key
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

def _pick_skill_pairs(row: Dict[str, Any]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    s1n = (_get(row, "skill_1_name") or "").strip()
    s1d = (_get(row, "skill_1_desc") or "").strip()
    s2n = (_get(row, "skill_2_name") or "").strip()
    s2d = (_get(row, "skill_2_desc") or "").strip()
    if s1n: out.append((s1n, s1d))
    if s2n: out.append((s2n, s2d))
    return out

# ---------- Preview ----------
@router.post("/preview", response_model=ImportPreviewOut)
async def preview(file: UploadFile = File(...)):
    text = _decode_upload(file)
    reader = csv.reader(StringIO(text), _sniff_dialect(text[:3000]))
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="空文件")

    headers = [h.strip() for h in rows[0]]
    _, idx_map = _normalize_headers(headers)

    sample: List[Dict[str, Any]] = []
    for r in rows[1:11]:
        d: Dict[str, Any] = {}
        for i, cell in enumerate(r):
            key = idx_map.get(i)
            if key: d[key] = cell
        if d: sample.append(d)

    required = ["element", "name_final", "hp", "speed", "attack", "defense", "magic", "resist"]
    missing = [k for k in required if k not in idx_map.values()]
    hints: List[str] = []
    if missing:
        hints.append(f"缺少字段: {', '.join(missing)}")

    return ImportPreviewOut(
        columns=[c for c in idx_map.values()],
        total_rows=max(0, len(rows) - 1),
        sample=sample,
        hints=hints,
    )

# ---------- Commit ----------
@router.post("/commit", response_model=ImportCommitOut)
async def commit(file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = _decode_upload(file)
    reader = csv.reader(StringIO(text), _sniff_dialect(text[:3000]))
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="空文件")

    headers = [h.strip() for h in rows[0]]
    _, idx_map = _normalize_headers(headers)

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

            # 查找/创建
            m = db.execute(
                select(Monster)
                .where(Monster.name_final == name_final)
                .options(selectinload(Monster.skills), selectinload(Monster.tags), selectinload(Monster.derived))
            ).scalar_one_or_none()

            is_new = False
            if not m:
                # ⚠️ 不要再传 name_repo，模型里没有这个字段（修复“全部跳过”的错误）
                m = Monster(name_final=name_final)
                db.add(m)
                db.flush()
                is_new = True

            # 元素 & 角色（角色若 CSV 没给，后面会自动推断）
            element = normalize_element((row.get("element") or "").strip())
            if element:
                m.element = element
            role_from_csv = (row.get("role") or "").strip()

            # 原始六维
            m.hp      = _to_float(row.get("hp"))
            m.speed   = _to_float(row.get("speed"))
            m.attack  = _to_float(row.get("attack"))
            m.defense = _to_float(row.get("defense"))
            m.magic   = _to_float(row.get("magic"))
            m.resist  = _to_float(row.get("resist"))

            # 说明/摘要（可顺便把 name_repo 存在 explain_json 里备查，但不入模型字段）
            summary = (row.get("summary") or "").strip()
            ex = m.explain_json or {}
            if summary:
                ex["summary"] = summary
            if row.get("name_repo"):
                ex["name_repo"] = (row.get("name_repo") or "").strip()
            ex["raw_stats"] = {
                "hp": m.hp, "speed": m.speed, "attack": m.attack,
                "defense": m.defense, "magic": m.magic, "resist": m.resist,
                "sum": m.hp + m.speed + m.attack + m.defense + m.magic + m.resist,
            }
            m.explain_json = ex

            # 技能（覆盖）
            skill_pairs = _pick_skill_pairs(row)
            if skill_pairs:
                if m.skills is None:
                    m.skills = []
                else:
                    m.skills.clear()
                skills = upsert_skills(db, skill_pairs)
                for s in skills:
                    m.skills.append(s)
                ex = m.explain_json or {}
                ex["skill_names"] = [s.name for s in m.skills]
                m.explain_json = ex

            # ⚙️ 统一用 tags 模块逻辑推断 role/tags（忽略 CSV 的 tags 列）
            if role_from_csv:
                m.role = role_from_csv
            else:
                role, tags = infer_role_and_tags_for_monster(m)
                m.role = role
                m.tags = upsert_tags(db, tags)

            # 计算并落库派生五维（含 pp_pressure）
            compute_and_persist(db, m)

            updated += 0 if is_new else 1
            inserted += 1 if is_new else 0

        except Exception as e:
            errors.append({"line": line_no, "error": str(e), "row": r})
            skipped += 1

    db.commit()
    return ImportCommitOut(inserted=inserted, updated=updated, skipped=skipped, errors=errors)