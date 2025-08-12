from typing import List, Dict, Tuple, Optional
import csv, io, re
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models import Monster, ImportJob
from .monsters_service import upsert_tags
from .rules_engine import calc_scores

REQUIRED = ["name_final"]
OPTIONAL = ["element","role","base_offense","base_survive","base_control","base_tempo","base_pp","tags"]

# 列名映射（中文/英文/别名 -> 内部字段）
HEADER_MAP = {
    "名称":"name_final", "最终名称":"name_final", "名字":"name_final", "name":"name_final",

    "元素":"element", "属性":"element", "element":"element",
    "定位":"role", "位置":"role", "role":"role",

    "攻":"base_offense", "攻击":"base_offense", "offense":"base_offense", "attack":"base_offense",
    "生":"base_survive", "生命":"base_survive", "体力":"base_survive", "survive":"base_survive", "hp":"base_survive",
    "控":"base_control", "控制":"base_control", "control":"base_control", "defense":"base_control", "magic":"base_control",
    "速":"base_tempo", "速度":"base_tempo", "tempo":"base_tempo", "speed":"base_tempo",
    "pp":"base_pp", "PP":"base_pp", "resist":"base_pp",

    "标签":"tags", "tag":"tags", "tags":"tags",
}

def _clean(s: str | None) -> str:
    return (s or "").replace("\ufeff","").replace("\u00A0"," ").replace("\u3000"," ").strip()

def _sniff_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        if "\t" in sample: return "\t"
        return ","

def _to_float(v: str | None) -> float:
    s = _clean(v)
    if not s: return 0.0
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return 0.0

def _split_tags(s: str | None) -> List[str]:
    parts = re.split(r"[\|,;\/\s]+", _clean(s))
    return [p for p in parts if p]

def _map_col(col: str) -> str:
    key = _clean(col)
    low = key.lower()
    return HEADER_MAP.get(key) or HEADER_MAP.get(low) or key

def parse_csv(file_bytes: bytes) -> Tuple[List[str], List[Dict]]:
    text = file_bytes.decode("utf-8", errors="ignore")
    text = _clean(text)
    delim = _sniff_delimiter(text[:10000])

    rdr = csv.DictReader(io.StringIO(text), delimiter=delim)
    raw_cols = rdr.fieldnames or []
    cols: List[str] = [_map_col(c) for c in raw_cols]

    rows: List[Dict] = []
    for r in rdr:
        nr: Dict[str, str] = {}
        for k, v in r.items():
            nr[_map_col(k)] = _clean(v)
        rows.append(nr)
    return cols, rows

def preview(file_bytes: bytes) -> Dict:
    cols, rows = parse_csv(file_bytes)
    hints: List[str] = []
    for req in REQUIRED:
        if req not in cols:
            hints.append(f"缺少必填列: {req}")
    sample = rows[:10]
    return {"columns": cols, "total_rows": len(rows), "sample": sample, "hints": hints}

def commit(db: Session, file_bytes: bytes, *, idempotency_key: Optional[str] = None) -> Dict:
    if idempotency_key:
        job = db.execute(select(ImportJob).where(ImportJob.key == idempotency_key)).scalar_one_or_none()
        if job and job.result_json:
            return job.result_json

    cols, rows = parse_csv(file_bytes)
    if "tags" not in cols:
        cols.append("tags")

    inserted = updated = skipped = 0
    errors: List[Dict] = []

    try:
        with db.begin():
            for idx, r in enumerate(rows, start=2):
                name = _clean(r.get("name_final"))
                if not name:
                    errors.append({"row": idx, "error": "missing name_final"})
                    skipped += 1
                    continue

                element = _clean(r.get("element")) or None

                # 查重
                q = select(Monster).where(Monster.name_final == name)
                if element:
                    q = q.where(Monster.element == element)
                m = db.execute(q).scalar_one_or_none()
                is_new = m is None
                if is_new:
                    m = Monster(name_final=name)

                # 基础字段
                m.element = element
                m.role = _clean(r.get("role")) or None
                m.base_offense = _to_float(r.get("base_offense"))
                m.base_survive = _to_float(r.get("base_survive"))
                m.base_control = _to_float(r.get("base_control"))
                m.base_tempo   = _to_float(r.get("base_tempo"))
                m.base_pp      = _to_float(r.get("base_pp"))

                # —— 计算得分 & 解释 & 计算标签 ——
                res = calc_scores({
                    "base_offense": m.base_offense,
                    "base_survive": m.base_survive,
                    "base_control": m.base_control,
                    "base_tempo":   m.base_tempo,
                    "base_pp":      m.base_pp,
                })
                m.explain_json = res.explain

                # —— 合并 CSV 标签 + 计算标签 并写回 ——
                csv_tags = _split_tags(r.get("tags"))
                merged = sorted(set(csv_tags) | set(res.tags))
                m.tags = upsert_tags(db, merged)

                if is_new:
                    db.add(m); inserted += 1
                else:
                    updated += 1

            result = {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors}
            if idempotency_key:
                job = db.execute(select(ImportJob).where(ImportJob.key == idempotency_key)).scalar_one_or_none()
                if not job:
                    job = ImportJob(key=idempotency_key, status="done", result_json=result)
                    db.add(job)
                else:
                    job.status = "done"; job.result_json = result
        return result
    except IntegrityError as e:
        return {"inserted": inserted, "updated": updated, "skipped": skipped,
                "errors": errors + [{"error": "db_integrity_error", "detail": str(e)}]}