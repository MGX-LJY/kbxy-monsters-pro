from typing import List, Dict, Tuple, Optional
import csv, io, re
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models import Monster, Tag, ImportJob
from .monsters_service import upsert_tags, apply_scores

REQUIRED = ["name_final"]
OPTIONAL = ["element","role","base_offense","base_survive","base_control","base_tempo","base_pp","tags"]

def sniff_delimiter(sample: str) -> str:
    if '\t' in sample: return '\t'
    return ','

def parse_csv(file_bytes: bytes) -> Tuple[List[str], List[Dict]]:
    text = file_bytes.decode("utf-8", errors="ignore")
    text = text.replace('\u00A0', ' ').replace('\u3000', ' ')
    delim = sniff_delimiter(text[:10000])
    rdr = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = [dict(r) for r in rdr]
    cols = rdr.fieldnames or []
    return cols, rows

def preview(file_bytes: bytes) -> Dict:
    cols, rows = parse_csv(file_bytes)
    hints: List[str] = []
    for req in REQUIRED:
        if req not in cols:
            hints.append(f"缺少必填列: {req}")
    sample = rows[:10]
    return {"columns": cols, "total_rows": len(rows), "sample": sample, "hints": hints}

def _split_tags(s: str) -> List[str]:
    import re
    parts = re.split(r'[\|,;\s]+', s.strip())
    return [p.strip() for p in parts if p.strip()]

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
                name = (r.get("name_final") or "").strip()
                if not name:
                    errors.append({"row": idx, "error": "missing name_final"})
                    skipped += 1
                    continue
                element = (r.get("element") or "").strip() or None

                q = select(Monster).where(Monster.name_final == name)
                if element:
                    q = q.where(Monster.element == element)
                m = db.execute(q).scalar_one_or_none()
                is_new = m is None
                if is_new:
                    m = Monster(name_final=name)

                m.element = element
                m.role = (r.get("role") or "").strip() or None
                for f in ["base_offense","base_survive","base_control","base_tempo","base_pp"]:
                    try:
                        setattr(m, f, float(r.get(f) or 0))
                    except ValueError:
                        setattr(m, f, 0.0)

                tag_str = r.get("tags") or ""
                tag_list = _split_tags(tag_str) if tag_str else []
                m.tags = upsert_tags(db, tag_list)
                apply_scores(m)

                if is_new:
                    db.add(m)
                    inserted += 1
                else:
                    updated += 1

            result = {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors}
            if idempotency_key:
                job = db.execute(select(ImportJob).where(ImportJob.key == idempotency_key)).scalar_one_or_none()
                if not job:
                    job = ImportJob(key=idempotency_key, status="done", result_json=result)
                    db.add(job)
                else:
                    job.status = "done"
                    job.result_json = result
        return result
    except IntegrityError as e:
        return {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors + [{"error": "db_integrity_error", "detail": str(e)}]}
