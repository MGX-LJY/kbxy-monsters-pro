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
    offense = monster.get("base_offense", 0) * w["offense"]
    survive = monster.get("base_survive", 0) * w["survive"]
    control = monster.get("base_control", 0) * w["control"]
    tempo = monster.get("base_tempo", 0) * w["tempo"]
    pp = monster.get("base_pp", 0) * w["pp"]
    tags: List[str] = []
    if offense >= 120: tags.append("强攻")
    if survive >= 120: tags.append("耐久")
    if pp >= 60: tags.append("PP压制")
    explain = {"weights": w, "formula": "linear", "inputs": monster}
    return ScoreResult(offense, survive, control, tempo, pp, tags, explain)
