# server/app/services/rules_engine.py
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class ScoreResult:
    offense: float
    survive: float
    control: float
    tempo: float
    pp: float
    tags: List[str]
    explain: Dict

DEFAULT_WEIGHTS = {
    "offense": 1.0, "survive": 1.0, "control": 1.0, "tempo": 1.0, "pp": 1.0
}

def calc_scores(monster: dict, weights: Dict[str, float] | None = None) -> ScoreResult:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    offense = float(monster.get("base_offense", 0)) * w["offense"]
    survive = float(monster.get("base_survive", 0)) * w["survive"]
    control = float(monster.get("base_control", 0)) * w["control"]
    tempo   = float(monster.get("base_tempo", 0))   * w["tempo"]
    pp      = float(monster.get("base_pp", 0))      * w["pp"]

    # —— 标签规则（可按你需求再调阈值）——
    tags: List[str] = []
    if offense >= 120: tags.append("强攻")
    if survive >= 120: tags.append("耐久")
    if control >= 120: tags.append("控场")
    if tempo   >= 110: tags.append("速攻")
    if pp      >= 95:  tags.append("PP压制")

    explain = {
        "weights": w,
        "formula": "linear@v2025-08-12",
        "inputs": {
            "base_offense": monster.get("base_offense", 0),
            "base_survive": monster.get("base_survive", 0),
            "base_control": monster.get("base_control", 0),
            "base_tempo": monster.get("base_tempo", 0),
            "base_pp": monster.get("base_pp", 0),
        },
        "score": {"offense": offense, "survive": survive, "control": control, "tempo": tempo, "pp": pp},
        "tags": tags
    }
    return ScoreResult(offense, survive, control, tempo, pp, tags, explain)