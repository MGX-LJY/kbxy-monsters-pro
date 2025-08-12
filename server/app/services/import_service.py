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

HEADER_MAP = {
    # 基础
    "名称":"name_final","最终名称":"name_final","名字":"name_final","name":"name_final",
    "元素":"element","属性":"element","element":"element",
    "定位":"role","位置":"role","role":"role",
    # 六维
    "体力":"hp","生命":"hp","hp":"hp","survive":"hp",
    "速度":"speed","速":"speed","speed":"speed","tempo":"speed",
    "攻击":"attack","攻":"attack","attack":"attack","offense":"attack",
    "防御":"defense","defense":"defense",
    "法术":"magic","magic":"magic",
    "抗性":"resist","抗":"resist","resist":"resist","pp":"resist","PP":"resist",
    # 标签
    "标签":"tags","tag":"tags","tags":"tags",
    # 技能（名称/说明，允许重复）
    "关键技能":"skill","关键技能2":"skill","关键技能一":"skill","关键技能二":"skill",
    "技能":"skill","技能1":"skill","技能2":"skill","skill":"skill","skill1":"skill","skill2":"skill",
    "关键技能说明":"skill_desc","关键技能2说明":"skill_desc","技能说明":"skill_desc",
    "skill_desc":"skill_desc","skill1_desc":"skill_desc","skill2_desc":"skill_desc",
    # 文本总结
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

    counts: Dict[str, int] = {}
    headers_norm: List[str] = []
    for h in headers_raw:
        m = _map_col(h)
        if m in ("skill", "skill_desc") or ("技能" in h) or ("skill" in h.lower()):
            idx = counts.get("skill", 0) + 1
            counts["skill"] = idx
            base = f"skill{idx}_desc" if ("desc" in m or "说明" in h) else f"skill{idx}"
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

    semantic_cols = sorted({_map_col(h) for h in headers})
    return semantic_cols, rows

# —— 自动推断定位（role）——
def _derive_role(tags: List[str], hp: float, attack: float, defense: float, magic: float, speed: float, resist: float) -> str:
    T = set(tags or [])
    if {"控制","控场"} & T: return "控制"
    if {"驱散","净化","加速","免疫异常","减伤","回复"} & T: return "辅助"
    if "强攻" in T or attack >= max(defense, magic, speed, hp, resist): return "主攻"
    if hp >= max(attack, defense, magic, speed, resist) or resist >= max(attack, defense, magic, speed, hp): return "坦克"
    return "通用"

# —— 从一行数据里抽取技能（支持 skill1/skill2/...；并智能把紧挨着的一列长文本当作描述）——
def _extract_skills_from_row(r: Dict[str, str]) -> List[Tuple[str, str]]:
    keys = list(r.keys())  # 保序
    out: List[Tuple[str, str]] = []
    i = 0
    while i < len(keys):
        k = keys[i]
        v = r.get(k) or ""
        if re.fullmatch(r"skill\d+", k) and v:
            # 先找显式 *_desc
            num = re.sub(r"[^0-9]", "", k) or ""
            desc = r.get(f"skill{num}_desc") or ""
            # 邻列推断（如果没有显式 desc）
            if not desc and i + 1 < len(keys):
                nk = keys[i + 1]
                nv = r.get(nk) or ""
                if (not nk.endswith("_desc")) and len(nv) >= 8 and re.search(r"[，。；、,.]|(提高|降低|回复|免疫|伤害|回合|命中|几率|状态|先手|消除|减少|增加)", nv):
                    desc = nv
                    i += 1  # 跳过作为描述的列
            out.append((v, desc))
        i += 1
    # 去重（按名称，保持顺序）
    seen: set[str] = set()
    dedup: List[Tuple[str, str]] = []
    for name, desc in out:
        if name in seen:  # 去重复技能名
            continue
        seen.add(name)
        dedup.append((name, desc))
    return dedup

def preview(file_bytes: bytes) -> Dict:
    cols, rows = parse_csv(file_bytes)
    hints: List[str] = []
    if "name_final" not in cols:
        hints.append("缺少必填列: name_final")
    sample = rows[:10]
    return {"columns": cols, "total_rows": len(rows), "sample": sample, "hints": hints}

def commit(db: Session, file_bytes: bytes, *, idempotency_key: Optional[str] = None) -> Dict:
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
                # 跳过明显脏数据
                if not name or name.lower() == "string":
                    skipped += 1
                    continue

                element = _clean(r.get("element")) or None
                q = select(Monster).where(Monster.name_final == name)
                if element: q = q.where(Monster.element == element)
                m = db.execute(q).scalar_one_or_none()
                is_new = m is None
                if is_new: m = Monster(name_final=name)

                # 六维
                hp      = _to_float(r.get("hp"))
                speed   = _to_float(r.get("speed"))
                attack  = _to_float(r.get("attack"))
                defense = _to_float(r.get("defense"))
                magic   = _to_float(r.get("magic"))
                resist  = _to_float(r.get("resist"))
                control = (defense + magic) / 2.0 if (defense or magic) else _to_float(r.get("base_control"))

                m.element = element
                m.role = _clean(r.get("role")) or m.role  # 不覆盖已有
                m.base_offense = attack
                m.base_survive = hp
                m.base_control = control
                m.base_tempo   = speed
                m.base_pp      = resist

                # 数值标签 & explain
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

                # 技能（含描述，强力去重）
                skill_pairs = _extract_skills_from_row(r)
                summary = r.get("summary") or ""
                added_skills = upsert_skills(db, skill_pairs)

                # 绑定技能：去重（既防已有重复，也防同一导入重复）
                existed_ids = {s.id for s in (m.skills or [])}
                seen_ids = set(existed_ids)
                for s in added_skills:
                    if s.id in seen_ids:
                        continue
                    m.skills.append(s)
                    seen_ids.add(s.id)

                # 技能标签 + CSV 标签 + 数值标签
                skill_texts = [s.name for s in (m.skills or [])] + [s.description for s in (m.skills or [])] + [summary]
                skill_tags = derive_tags_from_texts(skill_texts)
                csv_tags = set(_split_tags(r.get("tags")))
                merged_tags = sorted(set(res.tags) | skill_tags | csv_tags)
                m.tags = upsert_tags(db, merged_tags)

                # 补 role：若为空则根据标签/六维推断
                if not m.role or not m.role.strip():
                    m.role = _derive_role(merged_tags, hp, attack, defense, magic, speed, resist)

                # explain 冗余技能名（兜底）
                ex["skill_names"] = [s.name for s in (m.skills or [])] or [p[0] for p in skill_pairs]
                m.explain_json = ex

                if is_new: db.add(m); inserted += 1
                else: updated += 1

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