# server/app/services/import_service.py
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
    "名称":"name_final","最终名称":"name_final","名字":"name_final","name":"name_final",
    "元素":"element","属性":"element","element":"element",
    "定位":"role","位置":"role","role":"role",

    "体力":"hp","生命":"hp","hp":"hp","survive":"hp",
    "速度":"speed","速":"speed","speed":"speed","tempo":"speed",
    "攻击":"attack","攻":"attack","attack":"attack","offense":"attack",
    "防御":"defense","defense":"defense",
    "法术":"magic","magic":"magic",
    "抗性":"resist","抗":"resist","resist":"resist","pp":"resist","PP":"resist",

    "标签":"tags","tag":"tags","tags":"tags",

    # 下面几个只用于保存到 explain_json.summary（不再兜底当技能描述）
    "关键技能说明":"skill_desc","关键技能2说明":"skill_desc","技能说明":"skill_desc",
    "说明":"summary","总结":"summary","评价":"summary","描述":"summary","效果":"summary","介绍":"summary",

    # 英文直写（兼容性）
    "skill":"skill","skill1":"skill","skill2":"skill","skill3":"skill",
    "skill_desc":"skill_desc","skill1_desc":"skill_desc","skill2_desc":"skill_desc","skill3_desc":"skill_desc",
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

def _is_meaningful_desc(text: str) -> bool:
    t = _clean(text)
    if not t: return False
    if t.lower() in {"0","1","-","—","无","暂无","null","none","n/a","N/A"}: return False
    return (
        len(t) >= 6
        or re.search(r"[，。；、,.]", t)
        or re.search(r"(提高|降低|回复|免疫|伤害|回合|命中|几率|状态|先手|消除|减少|增加|额外|倍)", t)
    )

def _read_rows_with_duplicate_headers(text: str, delim: str) -> Tuple[List[str], List[List[str]]]:
    """
    规范表头（重难点修复）：
    - 精确识别三类带编号列：
        skill_#_name  -> skill{#}
        skill_#_desc  -> skill{#}_desc
        skill_#_is_core -> skill{#}_is_core
      同时兼容 skill-#-name / 无下划线的 skill1 / skill1_desc。
    - 中文'技能'/'关键技能'列（无编号）按出现顺序编号；'技能说明'映射到对应编号的 _desc；
      绝不把 '*_is_core' 当成技能名。
    - 排除“技能数量/次数/等级/CD/冷却”等非技能列。
    """
    rdr = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(rdr)
    if not rows: return [], []
    headers_raw = rows[0]
    data_rows = rows[1:]

    num_name = re.compile(r"^skill[_\-]?(\d+)[_\-]?name$", re.I)
    num_desc = re.compile(r"^skill[_\-]?(\d+)[_\-]?desc$", re.I)
    num_core = re.compile(r"^skill[_\-]?(\d+)[_\-]?is[_\-]?core$", re.I)
    simple_num = re.compile(r"^skill(\d+)$", re.I)
    simple_num_desc = re.compile(r"^skill(\d+)_desc$", re.I)

    neg_words = ("数量","个数","次数","等级","cd","CD","冷却","间隔")
    headers_norm: List[str] = []
    counts: Dict[str, int] = {}
    seq = 0  # 用于“无编号”的技能列顺序编号
    last_seq_for_desc = 0

    for h in headers_raw:
        hl = _clean(h)
        hlow = hl.lower()

        # 1) 显式编号：skill_#_* / skill# / skill#_desc / skill#_is_core
        m = num_name.match(hlow)
        if m:
            n = int(m.group(1))
            headers_norm.append(f"skill{n}")
            continue
        m = num_desc.match(hlow)
        if m:
            n = int(m.group(1))
            headers_norm.append(f"skill{n}_desc")
            continue
        m = num_core.match(hlow)
        if m:
            n = int(m.group(1))
            headers_norm.append(f"skill{n}_is_core")
            continue
        m = simple_num.match(hlow)
        if m:
            n = int(m.group(1))
            headers_norm.append(f"skill{n}")
            continue
        m = simple_num_desc.match(hlow)
        if m:
            n = int(m.group(1))
            headers_norm.append(f"skill{n}_desc")
            continue

        # 2) 中文/英文“技能*”但非数量/次数等
        has_skill_word = ("技能" in hl) or ("skill" in hlow)
        looks_desc = ("说明" in hl) or ("描述" in hl) or ("效果" in hl) or ("介绍" in hl) or ("desc" in hlow) or _map_col(hl) == "skill_desc"
        looks_negative = any(w in hl for w in neg_words)
        is_core_flag = ("is_core" in hlow) or ("是否核心" in hl) or ("关键" in hl and "是否" in hl)

        if has_skill_word and not looks_negative:
            # is_core 明确映射
            if is_core_flag:
                if seq == 0:
                    seq = 1  # 没有 name 也给个 1，后续可能不会用到
                headers_norm.append(f"skill{seq}_is_core")
                continue
            if looks_desc:
                if last_seq_for_desc == 0:
                    last_seq_for_desc = seq if seq > 0 else 1
                headers_norm.append(f"skill{last_seq_for_desc}_desc")
                continue
            # 普通“技能/关键技能”名列
            seq += 1
            last_seq_for_desc = seq
            headers_norm.append(f"skill{seq}")
            continue

        # 3) 其它列按语义映射 + 去重
        mkey = _map_col(hl)
        c = counts.get(mkey, 0) + 1
        counts[mkey] = c
        headers_norm.append(mkey if c == 1 else f"{mkey}__{c}")

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

def preview(file_bytes: bytes) -> Dict:
    cols, rows = parse_csv(file_bytes)
    hints: List[str] = []
    if "name_final" not in cols:
        hints.append("缺少必填列: name_final")
    sample = rows[:10]
    return {"columns": cols, "total_rows": len(rows), "sample": sample, "hints": hints}

def _truthy(v: str | None) -> bool:
    s = (v or "").strip().lower()
    return s in {"1","true","yes","y","是","核心","core"}

def _extract_skills_from_row(r: Dict[str, str]) -> List[Tuple[str, str]]:
    """
    仅从 skill{n} / skill{n}_desc / skill{n}_is_core 提取 (name, desc)。
    - 只保留 is_core 为真（关键技能）的条目；如未提供 is_core 列，则默认保留。
    - 优先用 skill{n}_desc，必要时在右侧 3 列内寻找“像描述”的文本。
    - 去重按名称。
    """
    keys = list(r.keys())
    nums: List[int] = []
    for k in keys:
        m = re.match(r"^skill(\d+)(?:_desc|_is_core)?$", k)
        if m:
            nums.append(int(m.group(1)))
    nums = sorted(set(nums))

    out: List[Tuple[str, str]] = []
    for n in nums:
        name = (r.get(f"skill{n}") or "").strip()
        if not name:
            continue

        # is_core 过滤（有列时才检查）
        core_key = f"skill{n}_is_core"
        if core_key in r and not _truthy(r.get(core_key)):
            continue

        desc = (r.get(f"skill{n}_desc") or "").strip()
        if not _is_meaningful_desc(desc):
            # 在 skill{n} 右侧 3 列找像描述的文本（避免拿到 '1'）
            try:
                idx = keys.index(f"skill{n}")
            except ValueError:
                idx = -1
            if idx >= 0:
                for nk in keys[idx+1: idx+4]:
                    if nk.endswith("_desc"):  # 已经尝试过
                        continue
                    cand = (r.get(nk) or "").strip()
                    if _is_meaningful_desc(cand):
                        desc = cand
                        break

        out.append((name, desc))

    # 去重（按名称）
    seen: set[str] = set()
    dedup: List[Tuple[str, str]] = []
    for nm, ds in out:
        if nm in seen: continue
        seen.add(nm)
        dedup.append((nm, ds))
    return dedup

def _derive_role(tags: List[str], hp: float, attack: float, defense: float, magic: float, speed: float, resist: float) -> str:
    T = set(tags or [])
    if {"控制","控场"} & T: return "控制"
    if {"驱散","净化","加速","免疫异常","减伤","回复"} & T: return "辅助"
    if "强攻" in T or attack >= max(defense, magic, speed, hp, resist): return "主攻"
    if hp >= max(attack, defense, magic, speed, resist) or resist >= max(attack, defense, magic, speed, hp): return "坦克"
    return "通用"

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
                name = _clean(r.get("name_final") or r.get("name_repo") or r.get("名称"))
                if not name or name.lower() == "string":
                    skipped += 1
                    continue

                element = _clean(r.get("element") or r.get("元素")) or None
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
                m.role = _clean(r.get("role"))
                m.base_offense = attack
                m.base_survive = hp
                m.base_control = control
                m.base_tempo   = speed
                m.base_pp      = resist

                # 计算标签 + explain
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

                # 技能（仅关键技能）
                skill_pairs = _extract_skills_from_row(r)
                summary = r.get("summary") or ""   # 主观评价单独存放
                added_skills = upsert_skills(db, skill_pairs)

                # 绑定技能（严格去重）
                existed_ids = {s.id for s in (m.skills or [])}
                for s in added_skills:
                    if s.id not in existed_ids:
                        m.skills.append(s)
                        existed_ids.add(s.id)

                # 合并标签（数值+技能文本+summary）
                skill_texts = [s.name for s in (m.skills or [])] + [s.description for s in (m.skills or [])] + [summary]
                skill_tags = derive_tags_from_texts(skill_texts)
                csv_tags = set(_split_tags(r.get("tags")))
                merged_tags = sorted(set(res.tags) | skill_tags | csv_tags)
                m.tags = upsert_tags(db, merged_tags)

                # role 兜底
                if not m.role or not m.role.strip():
                    m.role = _derive_role(merged_tags, hp, attack, defense, magic, speed, resist)

                # explain：技能名兜底 + 主观评价
                ex["skill_names"] = [s.name for s in (m.skills or [])] or [p[0] for p in skill_pairs]
                ex["summary"] = summary
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