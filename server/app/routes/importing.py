# server/app/routes/importing.py
from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select
import csv
from io import StringIO, TextIOWrapper
from typing import List, Dict, Any, Tuple, Optional

from ..db import SessionLocal
from ..models import Monster, Skill
from ..services.skills_service import upsert_skills
from ..services.monsters_service import upsert_tags  # 若 CSV 将来带 tags 可复用
from ..services.derive_service import compute_and_persist

router = APIRouter(prefix="/import", tags=["import"])


# ------------------------------
# Pydantic I/O
# ------------------------------
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


# ------------------------------
# Helpers
# ------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
    允许大小写/下划线变体，以及常见中文同义。
    仅保留我们这一版需要的字段。
    """
    pairs = {
        "element": "element", "元素": "element",
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

        # 如将来有 tags/role 也能导
        "tags": "tags", "标签": "tags",
        "role": "role", "定位": "role",
    }
    # 允许大小写/中划线/下划线变体
    m = {}
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


# ------------------------------
# Preview
# ------------------------------
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


# ------------------------------
# Commit
# ------------------------------
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

    # 逐行导入
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

            # 查找是否已存在（按 name_final 优先；退化到 name_repo）
            m = db.execute(select(Monster).where(Monster.name_final == name_final)).scalar_one_or_none()
            if not m:
                name_repo = (row.get("name_repo") or "").strip() or None
                m = Monster(
                    name_final=name_final,
                    name_repo=name_repo,
                )
                db.add(m)
                db.flush()
                is_new = True
            else:
                is_new = False

            # 写元素/定位（若提供）
            element = (row.get("element") or "").strip()
            if element:
                m.element = element
            role = (row.get("role") or "").strip()
            if role:
                m.role = role

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

            # 技能：两列(name/desc)对；没有 *_is_core 字段也完全OK
            skill_pairs = _pick_skill_pairs(row)
            if skill_pairs:
                # 替换当前技能为导入集
                if m.skills is None:
                    m.skills = []
                else:
                    m.skills.clear()
                skills = upsert_skills(db, skill_pairs)  # 返回 session 中的 Skill 对象
                for s in skills:
                    m.skills.append(s)
                # 写 skill_names 到 explain_json
                ex = m.explain_json or {}
                ex["skill_names"] = [s.name for s in m.skills]
                m.explain_json = ex

            # 若 CSV 自带标签（可选）
            if "tags" in row and row.get("tags"):
                tags = _split_tags(str(row.get("tags")))
                m.tags = upsert_tags(db, tags)

            # 计算并落库派生五维（MonsterDerived）
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