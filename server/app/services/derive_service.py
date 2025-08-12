# server/app/services/derive_service.py
from __future__ import annotations

from typing import Dict, Tuple, List

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Monster, MonsterDerived
from .tags_service import extract_signals, suggest_tags_for_monster, infer_role_for_monster
from .monsters_service import upsert_tags


def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    """
    从列（hp/speed/attack/defense/magic/resist）读取；为 0/None 回退 explain_json.raw_stats。
    """
    ex = monster.explain_json or {}
    raw = ex.get("raw_stats") or {}

    def pick(col_val, raw_key):
        if col_val is not None and float(col_val) != 0.0:
            return float(col_val)
        v = raw.get(raw_key)
        return float(v) if v is not None else 0.0

    hp = pick(monster.hp, "hp")
    speed = pick(monster.speed, "speed")
    attack = pick(monster.attack, "attack")
    defense = pick(monster.defense, "defense")
    magic = pick(monster.magic, "magic")
    resist = pick(monster.resist, "resist")
    return hp, speed, attack, defense, magic, resist


def compute_derived(monster: Monster) -> Dict[str, float]:
    """
    使用 tags_service 抽取的“信号”来计算派生五维（float 版本）。
    """
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    sig = extract_signals(monster)

    offense = (
        0.5 * attack
        + 0.2 * speed
        + (10.0 if sig["has_multi_hit"] else 0.0)
        + (12.0 if sig["has_crit_ignore"] else 0.0)
    )

    survive = (
        0.4 * hp
        + 0.3 * defense
        + 0.2 * resist
        + (10.0 if sig["has_survive_buff"] else 0.0)
    )

    control = (
        12.0 * float(sig["ctrl_count"])
        + (8.0 if sig["slow_or_accuracy"] else 0.0)
        + 0.1 * speed
    )

    tempo = (
        speed
        + (15.0 if sig["first_strike"] else 0.0)
        + (8.0 if sig["speed_up"] else 0.0)
    )

    pp_hits = int(sig["pp_hits"])
    pp_pressure = 20.0 * (1 if pp_hits > 0 else 0) + 5.0 * pp_hits

    return {
        "offense": float(offense),
        "survive": float(survive),
        "control": float(control),
        "tempo": float(tempo),
        "pp_pressure": float(pp_pressure),
    }


def _to_ints(d: Dict[str, float]) -> Dict[str, int]:
    return {k: int(round(float(v))) for k, v in d.items()}


def compute_derived_out(monster: Monster) -> Dict[str, int]:
    return _to_ints(compute_derived(monster))


def compute_and_persist(db: Session, monster: Monster) -> MonsterDerived:
    """
    写入/更新 MonsterDerived（调用方提交事务）。
    """
    vals = compute_derived_out(monster)
    md = monster.derived
    if not md:
        md = MonsterDerived(
            monster_id=monster.id,
            offense=vals["offense"],
            survive=vals["survive"],
            control=vals["control"],
            tempo=vals["tempo"],
            pp_pressure=vals["pp_pressure"],
        )
        db.add(md)
        monster.derived = md
    else:
        md.offense = vals["offense"]
        md.survive = vals["survive"]
        md.control = vals["control"]
        md.tempo = vals["tempo"]
        md.pp_pressure = vals["pp_pressure"]
    return md


def apply_role_tags(
    db: Session,
    monster: Monster,
    *,
    override_role_if_blank: bool = True,
    merge_tags: bool = True,
) -> None:
    """
    使用 tags_service 产出的 role+tags 写回 Monster。
    - override_role_if_blank=True：仅在 monster.role 为空时写入 role
    - merge_tags=True：将建议标签与现有标签合并去重后 upsert
    """
    role_suggest = infer_role_for_monster(monster)
    tags_suggest = suggest_tags_for_monster(monster)

    # role
    if override_role_if_blank:
        if not monster.role:
            monster.role = role_suggest
    else:
        monster.role = role_suggest

    # tags
    if merge_tags:
        existed = {t.name for t in (monster.tags or []) if getattr(t, "name", None)}
        merged = sorted({*existed, *tags_suggest})
        monster.tags = upsert_tags(db, merged)
    else:
        monster.tags = upsert_tags(db, tags_suggest)


def recompute_and_autolabel(db: Session, monster: Monster) -> MonsterDerived:
    """
    先用 tags_service 自动打 role/tags（role 仅在为空时写入；tags 与现有合并），
    再计算并落库派生五维。这样派生就能吃到已打的标签（如“PP压制/先手”等）。
    """
    apply_role_tags(db, monster, override_role_if_blank=True, merge_tags=True)
    md = compute_and_persist(db, monster)
    return md


def recompute_all(db: Session) -> int:
    """
    全量重算并自动补 role/tags；返回处理条数（不提交事务）。
    """
    mons: List[Monster] = db.scalars(select(Monster)).all()
    n = 0
    for m in mons:
        recompute_and_autolabel(db, m)
        n += 1
    return n


__all__ = [
    "compute_derived",
    "compute_derived_out",
    "compute_and_persist",
    "apply_role_tags",
    "recompute_and_autolabel",
    "recompute_all",
]