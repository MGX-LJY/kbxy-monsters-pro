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
from ..services.derive_service import recompute_and_autolabel

router = APIRouter(prefix="/import", tags=["import"])

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

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _decode_upload(file: UploadFile) -> str:
    try:
        raw = file.file.read()
        return raw.decode("utf-8-sig") if isinstance(raw, bytes) else str(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="无法读取文件（请用 UTF-8 编码）")

def _sniff_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",\t;")
    except Exception:
        d = csv.excel; d.delimiter = ","; return d

def _norm_key_map() -> Dict[str, str]:
    pairs = {
        "element":"element","元素":"element","系别":"element",
        "name_final":"name_final","名称":"name_final","名字":"name_final",
        "hp":"hp","体力":"hp","speed":"speed","速度":"speed",
        "attack":"attack","攻击":"attack","defense":"defense","防御":"defense",
        "magic":"magic","法术":"magic","resist":"resist","抗性":"resist",
        "total":"total","合计":"total","summary":"summary","总结":"summary","简介":"summary",
        "skill_1_name":"skill_1_name","技能1":"skill_1_name",
        "skill_1_desc":"skill_1_desc","技能1描述":"skill_1_desc",
        "skill_2_name":"skill_2_name","技能2":"skill_2_name",
        "skill_2_desc":"skill_2_desc","技能2描述":"skill_2_desc",
        # 忽略 CSV 的 tags/role（统一由服务端规则生成）
        "tags":"_ignore","标签":"_ignore","role":"_ignore","定位":"_ignore",
        "name_repo":"_ignore","仓库名":"_ignore",
    }
    m: Dict[str,str] = {}
    for k,v in pairs.items():
        m[k]=v; m[k.lower()]=v; m[k.replace("-","_").lower()]=v
    return m

def _normalize_headers(headers: List[str]) -> Tuple[List[str], Dict[int, str]]:
    norm = _norm_key_map()
    cols, idx_map = [], {}
    for i,h in enumerate(headers or []):
        key = norm.get(h) or norm.get(h.lower()) or norm.get(h.replace("-","_").lower())
        cols.append(key or h)
        if key and key != "_ignore":
            idx_map[i] = key
    return cols, idx_map

def _to_float(v) -> float:
    try:
        if v in (None,"","NULL","null"): return 0.0
        return float(str(v).strip())
    except Exception:
        return 0.0

def _pick_skill_pairs(row: Dict[str, Any]):
    out = []
    s1n = (row.get("skill_1_name") or "").strip()
    s1d = (row.get("skill_1_desc") or "").strip()
    s2n = (row.get("skill_2_name") or "").strip()
    s2d = (row.get("skill_2_desc") or "").strip()
    if s1n: out.append((s1n, s1d))
    if s2n: out.append((s2n, s2d))
    return out

@router.post("/preview", response_model=ImportPreviewOut)
async def preview(file: UploadFile = File(...)):
    text = _decode_upload(file)
    dialect = _sniff_dialect(text[:3000])
    rows = list(csv.reader(StringIO(text), dialect))
    if not rows: raise HTTPException(400, "空文件")
    headers = [h.strip() for h in rows[0]]
    _, idx_map = _normalize_headers(headers)

    sample = []
    for r in rows[1:11]:
        d = {}
        for i,cell in enumerate(r):
            key = idx_map.get(i)
            if key: d[key]=cell
        if d: sample.append(d)

    required = ["element","name_final","hp","speed","attack","defense","magic","resist"]
    missing = [k for k in required if k not in idx_map.values()]
    hints = [f"缺少字段: {', '.join(missing)}"] if missing else []
    return ImportPreviewOut(columns=list(idx_map.values()), total_rows=max(0,len(rows)-1), sample=sample, hints=hints)

@router.post("/commit", response_model=ImportCommitOut)
async def commit(file: UploadFile = File(...), db: Session = Depends(get_db)):
    text = _decode_upload(file)
    dialect = _sniff_dialect(text[:3000])
    rows = list(csv.reader(StringIO(text), dialect))
    if not rows: raise HTTPException(400, "空文件")

    headers = [h.strip() for h in rows[0]]
    _, idx_map = _normalize_headers(headers)

    required = ["element","name_final","hp","speed","attack","defense","magic","resist"]
    missing = [k for k in required if k not in idx_map.values()]
    if missing: raise HTTPException(400, f"缺少字段: {', '.join(missing)}")

    inserted = updated = skipped = 0
    errors: List[Dict[str, Any]] = []

    for line_no, r in enumerate(rows[1:], start=2):
        try:
            row = {}
            for i,cell in enumerate(r):
                key = idx_map.get(i)
                if key: row[key]=cell

            name_final = (row.get("name_final") or "").strip()
            if not name_final:
                skipped += 1; continue

            m = db.execute(
                select(Monster)
                .where(Monster.name_final == name_final)
                .options(selectinload(Monster.skills), selectinload(Monster.tags), selectinload(Monster.derived))
            ).scalar_one_or_none()

            is_new = False
            if not m:
                m = Monster(name_final=name_final)
                db.add(m); db.flush()
                is_new = True

            m.element = (row.get("element") or "").strip() or None
            m.hp      = _to_float(row.get("hp"))
            m.speed   = _to_float(row.get("speed"))
            m.attack  = _to_float(row.get("attack"))
            m.defense = _to_float(row.get("defense"))
            m.magic   = _to_float(row.get("magic"))
            m.resist  = _to_float(row.get("resist"))

            # 写 raw_stats/summary
            ex = m.explain_json or {}
            ex["raw_stats"] = {
                "hp": m.hp, "speed": m.speed, "attack": m.attack,
                "defense": m.defense, "magic": m.magic, "resist": m.resist,
                "sum": m.hp + m.speed + m.attack + m.defense + m.magic + m.resist,
            }
            summary = (row.get("summary") or "").strip()
            if summary: ex["summary"] = summary
            m.explain_json = ex

            # 技能（覆盖）
            pairs = _pick_skill_pairs(row)
            if pairs:
                if m.skills is None: m.skills = []
                else: m.skills.clear()
                for s in upsert_skills(db, pairs):
                    m.skills.append(s)
                ex = m.explain_json or {}
                ex["skill_names"] = [s.name for s in m.skills]
                m.explain_json = ex

            # 统一通过 tags_service 贴标签+定位，并据此计算派生
            recompute_and_autolabel(db, m)

            if is_new: inserted += 1
            else: updated += 1
        except Exception as e:
            errors.append({"line": line_no, "error": str(e), "row": r})
            skipped += 1

    db.commit()
    return ImportCommitOut(inserted=inserted, updated=updated, skipped=skipped, errors=errors)