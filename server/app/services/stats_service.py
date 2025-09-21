# server/app/services/stats_service.py
from __future__ import annotations

import statistics
import time
from typing import Dict, List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Monster


# 六维属性字段映射
STAT_FIELDS = {
    'hp': Monster.hp,
    'speed': Monster.speed, 
    'attack': Monster.attack,
    'defense': Monster.defense,
    'magic': Monster.magic,
    'resist': Monster.resist
}

STAT_LABELS = {
    'hp': '体力',
    'speed': '速度',
    'attack': '攻击', 
    'defense': '防御',
    'magic': '法术',
    'resist': '抗性'
}

# 缓存机制
_stats_cache: Dict = {}
_rankings_cache: Dict[int, Dict] = {}
_cache_timestamp: Optional[float] = None
CACHE_EXPIRY_SECONDS = 3600  # 1小时过期


def _is_cache_valid() -> bool:
    """检查缓存是否有效"""
    global _cache_timestamp
    if _cache_timestamp is None:
        return False
    return time.time() - _cache_timestamp < CACHE_EXPIRY_SECONDS


def _clear_cache():
    """清除所有缓存"""
    global _stats_cache, _rankings_cache, _cache_timestamp
    _stats_cache.clear()
    _rankings_cache.clear()
    _cache_timestamp = None


def _update_cache_timestamp():
    """更新缓存时间戳"""
    global _cache_timestamp
    _cache_timestamp = time.time()


def analyze_monster_stats(db: Session) -> Dict:
    """分析所有妖怪的属性统计数据（带缓存）"""
    
    # 检查缓存
    global _stats_cache
    if _is_cache_valid() and _stats_cache:
        return _stats_cache
    
    # 获取所有妖怪的属性数据
    monsters = db.scalars(select(Monster)).all()
    
    if not monsters:
        raise ValueError("没有找到妖怪数据")
    
    analysis = {}
    
    for stat_name, field in STAT_FIELDS.items():
        # 提取该属性的所有数值
        values = []
        for monster in monsters:
            value = getattr(monster, stat_name, 0)
            if value is not None:
                values.append(float(value))
        
        if not values:
            continue
            
        values.sort()
        total_count = len(values)
        
        # 基础统计指标
        min_val = min(values)
        max_val = max(values)
        mean = statistics.mean(values)
        median = statistics.median(values)
        std_dev = statistics.stdev(values) if len(values) > 1 else 0
        
        # 分位数
        q25 = statistics.quantiles(values, n=4)[0] if len(values) >= 4 else values[0]
        q75 = statistics.quantiles(values, n=4)[2] if len(values) >= 4 else values[-1]
        q90 = values[int(total_count * 0.9)] if total_count > 10 else values[-1]
        q95 = values[int(total_count * 0.95)] if total_count > 20 else values[-1]
        
        # 无双妖怪识别：使用IQR方法
        iqr = q75 - q25
        outlier_threshold = q75 + 1.5 * iqr
        
        # 如果IQR方法识别的异常值太少，使用95分位数的1.3倍
        outliers_by_iqr = [v for v in values if v > outlier_threshold]
        if len(outliers_by_iqr) < max(1, total_count * 0.01):  # 至少1%的妖怪
            outlier_threshold = q95 * 1.3
        
        outlier_count = len([v for v in values if v > outlier_threshold])
        
        analysis[stat_name] = {
            "stat_name": STAT_LABELS[stat_name],
            "total_count": total_count,
            "min_value": min_val,
            "max_value": max_val,
            "mean": round(mean, 2),
            "median": round(median, 2),
            "q25": round(q25, 2),
            "q75": round(q75, 2),
            "q90": round(q90, 2),
            "q95": round(q95, 2),
            "std_dev": round(std_dev, 2),
            "outlier_threshold": round(outlier_threshold, 2),
            "outlier_count": outlier_count
        }
    
    # 更新缓存
    _stats_cache = analysis
    _update_cache_timestamp()
    
    return analysis


def calculate_monster_ranking(db: Session, monster: Monster) -> Dict:
    """计算指定妖怪的属性排名（带缓存）"""
    
    # 检查妖怪排名缓存
    global _rankings_cache
    if _is_cache_valid() and monster.id in _rankings_cache:
        return _rankings_cache[monster.id]
    
    # 获取统计分析结果（也会利用缓存）
    stats_analysis = analyze_monster_stats(db)
    
    # 获取所有妖怪数据用于排名计算
    all_monsters = db.scalars(select(Monster)).all()
    
    ranking_result = {}
    
    for stat_name in STAT_FIELDS.keys():
        current_value = getattr(monster, stat_name, 0)
        if current_value is None:
            current_value = 0
        current_value = float(current_value)
        
        analysis = stats_analysis[stat_name]
        outlier_threshold = analysis["outlier_threshold"]
        
        # 提取该属性的所有数值进行排名
        all_values = []
        for m in all_monsters:
            value = getattr(m, stat_name, 0)
            if value is not None:
                all_values.append(float(value))
        
        all_values.sort()
        total_count = len(all_values)
        
        # 判断是否为无双妖怪
        is_outlier = current_value > outlier_threshold
        
        if is_outlier:
            # 无双妖怪：在异常值中的排名，映射到95-99分
            outlier_values = [v for v in all_values if v > outlier_threshold]
            outlier_values.sort(reverse=True)  # 降序
            
            outlier_rank = 1
            for i, v in enumerate(outlier_values):
                if v <= current_value:
                    outlier_rank = i + 1
                    break
            
            # 映射到95-99分
            percentile = 99 - (outlier_rank - 1) * (4 / max(1, len(outlier_values) - 1))
            percentile = max(95, min(99, percentile))
            tier = "顶级"
            
            # 在全体中的排名
            rank = len([v for v in all_values if v > current_value]) + 1
            
        else:
            # 普通妖怪：排除异常值后计算排名
            normal_values = [v for v in all_values if v <= outlier_threshold]
            normal_values.sort()
            
            # 在普通妖怪中的位置
            normal_rank = len([v for v in normal_values if v < current_value]) + 1
            normal_total = len(normal_values)
            
            if normal_total > 0:
                # 计算在普通妖怪中的百分比，映射到1-94分
                raw_percentile = (normal_rank / normal_total) * 100
                percentile = max(1, min(94, raw_percentile))
                
                # 基于百分比确定等级
                if percentile >= 85:
                    tier = "优秀"
                elif percentile >= 65:
                    tier = "良好"
                elif percentile >= 35:
                    tier = "一般"
                else:
                    tier = "较弱"
            else:
                percentile = 50
                tier = "一般"
            
            # 在全体中的排名
            rank = len([v for v in all_values if v > current_value]) + 1
        
        ranking_result[stat_name] = {
            "stat_name": STAT_LABELS[stat_name],
            "value": current_value,
            "percentile": round(percentile, 1),
            "tier": tier,
            "rank": rank,
            "total_count": total_count,
            "is_outlier": is_outlier
        }
    
    # 缓存结果
    _rankings_cache[monster.id] = ranking_result
    
    return ranking_result