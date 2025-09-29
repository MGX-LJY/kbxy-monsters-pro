# server/app/services/combat_service.py
from typing import Dict
from ..models import Monster


class CombatAnalyzer:
    """战斗倾向分析器"""

    BALANCE_THRESHOLD = 5  # 平衡阈值

    @classmethod
    def calculate_combat_tendencies(cls, monster: Monster) -> Dict[str, str]:
        """计算妖怪战斗倾向"""
        # 获取基础数值，确保不为None
        hp = monster.hp or 0
        attack = monster.attack or 0
        defense = monster.defense or 0
        magic = monster.magic or 0
        resist = monster.resist or 0
        speed = monster.speed or 0

        # 计算四项战斗力数值
        main_physical_attack = attack + (hp * 0.1) + (speed * 0.05)
        main_magic_attack = magic + (hp * 0.1) + (resist * 0.05)
        main_physical_defense = defense + (hp * 0.2)
        main_magic_defense = resist + (hp * 0.2)

        # 攻击倾向判定
        attack_diff = abs(main_physical_attack - main_magic_attack)
        if attack_diff <= cls.BALANCE_THRESHOLD:
            attack_tendency = "攻击平衡"
        elif main_physical_attack > main_magic_attack:
            attack_tendency = "主物攻"
        else:
            attack_tendency = "主法攻"

        # 防御倾向判定
        defense_diff = abs(main_physical_defense - main_magic_defense)
        if defense_diff <= cls.BALANCE_THRESHOLD:
            defense_tendency = "防御平衡"
        elif main_physical_defense > main_magic_defense:
            defense_tendency = "主物防"
        else:
            defense_tendency = "主法防"

        return {
            "attack_tendency": attack_tendency,
            "defense_tendency": defense_tendency
        }