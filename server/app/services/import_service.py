from typing import List, Dict, Tuple, Optional
import csv, io, re
from sqlalchemy.orm import Session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models import Monster, ImportJob
from .monsters_service import upsert_tags
from .rules_engine import calc_scores
from .skills_service import upsert_skills, derive_tags_from_texts

REQUIRED = ["name_final"]

# 列名映射（→ 统一到原始六维命名 + 其他字段）
HEADER_MAP = {
    # 名称/元素/定位
    "名称":"name_final","最终名称":"name_final","名字":"name_final","name":"name_final",
    "元素":"element","属性":"element","element":"element",
    "定位":"role","位置":"role","role":"role",

    # 六维（原始）
    "体力":"hp","生命":"hp","hp":"hp","survive":"hp",
    "速度":"speed","速":"speed","speed":"speed","tempo":"speed",
    "攻击":"attack","攻":"attack","attack":"attack","offense":"attack",
    "防御":"defense","defense":"defense",
    "法术":"magic","magic":"magic",
    "抗性":"resist","抗":"resist","resist":"resist","pp":"resist","PP":"resist",

    # 标签
    "标签":"tags","tag":"tags","tags":"tags",

    # 技能列（尽量多兼容，名称/说明）
    "关键技能":"skill","关键技能2":"skill","关键技能一":"skill","关键技能二":"skill",
    "技能":"skill","技能1":"skill","技能2":"skill","skill":"skill","skill1":"skill","skill2":"skill",
    "关键技能说明":"skill_desc","关键技能2说明":"skill_desc","技能说明":"skill_desc",
    "skill_desc":"skill_desc","skill1_desc":"skill_desc","skill2_desc":"skill_desc",

    # 文字描述
    "总结":"summary","评价":"summary","说明":"summary",
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

def _map_col(raw: str) -> str:
    key = _clean(raw); low = key.lower()
    return HEADER_MAP.get(key) or HEADER_MAP.get(low) or key

def _read_rows_with_duplicate_headers(text: str, delim: str) -> Tuple[List[str], List[List[str]]]:
    rdr = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(rdr)
    if not rows: return [], []
    headers_raw = rows[0]
    data_rows = rows[1:]

    # 规范表头，技能列允许重复：skill, skill, skill_desc...
    counts: Dict[str, int] = {}
    headers_norm: List[str] = []
    for h in headers_raw:
        m = _map_col(h)
        base = m
        # 技能列：出现多个时，自动编号 skill1/skill2/skill3...；说明列编号 skill1_desc...
        if m in ("skill", "skill_desc") or ("技能" in h) or ("skill" in h.lower()):
            idx = counts.get("skill", 0) + 1
            counts["skill"] = idx
            if "desc" in m or "说明" in h:
                base = f"skill{idx}_desc"
            else:
                base = f"skill{idx}"
        else:
            c = counts.get(m, 0) + 1
            counts[m] = c
            base = m if c == 1 else f"{m}__{c}"
        headers_norm.append(base)
    return headers_norm, data_rows

def parse_csv(file_bytes: bytes) -> Tuple[List[str], List[Dict]]:
    text = _clean(file_bytes.decode("utf-8", errors="ignore"))
    delim = _sniff_delimiter(text[:10000])

    headers, data_rows = _read_rows_with_duplicate_headers(text, delim)
    rows: List[Dict] = []
    for row in data_rows:
        item: Dict[str, str] = {}
        for i, v in enumerate(row):
            if i >= len(headers): break
            item[headers[i]] = _clean(v)
        rows.append(item)

    # 返回去重后的“语义列”
    semantic_cols = sorted({_map_col(h) for h in headers})
    return semantic_cols, rows

def preview(file_bytes: bytes) -> Dict:
    cols, rows = parse_csv(file_bytes)
    hints: List[str] = []
    if "name_final" not in cols:
        hints.append("缺少必填列: name_final")
    sample = rows[:10]
    return {"columns": cols, "total_rows": len(rows), "sample": sample, "hints": hints}

def commit(db: Session, file_bytes: bytes, *, idempotency_key: Optional[str] = None) -> Dict:
    from ..models import ImportJob  # 局部导入避免循环
    if idempotency_key:
        job = db.execute(select(ImportJob).where(ImportJob.key == idempotency_key)).scalar_one_or_none()
        if job and job.result_json:
            return job.result_json

    cols, rows = parse_csv(file_bytes)

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
                q = select(Monster).where(Monster.name_final == name)
                if element:
                    q = q.where(Monster.element == element)
                m = db.execute(q).scalar_one_or_none()
                is_new = m is None
                if is_new:
                    m = Monster(name_final=name)

                # —— 原始六维（尽量从原始列取；兼容旧列名）——
                hp      = _to_float(r.get("hp")      or r.get("base_survive"))
                speed   = _to_float(r.get("speed")   or r.get("base_tempo"))
                attack  = _to_float(r.get("attack")  or r.get("base_offense"))
                defense = _to_float(r.get("defense"))
                magic   = _to_float(r.get("magic"))
                resist  = _to_float(r.get("resist")  or r.get("base_pp"))

                # base_* 仍用于规则引擎；control 取「防御/法术」平均
                control = (defense + magic) / 2.0 if (defense or magic) else _to_float(r.get("base_control"))

                # 写入基础字段
                m.element = element
                m.role = _clean(r.get("role")) or None
                m.base_offense = attack
                m.base_survive = hp
                m.base_control = control
                m.base_tempo   = speed
                m.base_pp      = resist

                # 规则引擎（数值标签）
                res = calc_scores({
                    "base_offense": m.base_offense,
                    "base_survive": m.base_survive,
                    "base_control": m.base_control,
                    "base_tempo":   m.base_tempo,
                    "base_pp":      m.base_pp,
                })
                ex = dict(res.explain)
                ex["raw_stats"] = {
                    "hp": hp, "speed": speed, "attack": attack,
                    "defense": defense, "magic": magic, "resist": resist,
                    "sum": hp + speed + attack + defense + magic + resist,
                }

                # —— 解析技能（支持 skill1/skill2/... 以及 中文“关键技能”列重复）——
                skill_pairs: List[Tuple[str, str]] = []
                skill_names_only: List[str] = []
                i = 1
                while True:
                    nm = r.get(f"skill{i}")
                    ds = r.get(f"skill{i}_desc")
                    if nm:
                        skill_pairs.append((nm, ds or ""))
                        skill_names_only.append(nm)
                        i += 1
                    else:
                        break
                # 兜底：如果没有显式 skillN，但有 summary，可用作关键字来源
                summary = r.get("summary") or ""
                if not skill_pairs and summary:
                    # 仅做标签来源，不入库技能名
                    pass

                added_skills = upsert_skills(db, skill_pairs)
                # 绑定技能（避免重复）
                exist = {s.name for s in (m.skills or [])}
                for s in added_skills:
                    if s.name not in exist:
                        m.skills.append(s)

                # 技能标签（技能名+描述+summary）
                skill_texts = [s.name for s in (m.skills or [])] + [s.description for s in (m.skills or [])] + [summary]
                skill_tags = derive_tags_from_texts(skill_texts)

                # CSV 标签
                csv_tags = set(_split_tags(r.get("tags")))

                # 合并所有标签
                merged_tags = sorted(set(res.tags) | skill_tags | csv_tags)
                m.tags = upsert_tags(db, merged_tags)

                # 冗余：explain_json 里同时记录技能名，方便前端兜底显示
                ex["skill_names"] = [s.name for s in (m.skills or [])] or skill_names_only
                m.explain_json = ex

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