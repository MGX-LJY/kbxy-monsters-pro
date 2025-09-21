# server/app/routes/stats.py
from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..db import SessionLocal
from ..dependencies import get_db
from ..models import Monster
from ..services.stats_service import analyze_monster_stats, calculate_monster_ranking
from ..services import stats_service

router = APIRouter()



class StatsAnalysis(BaseModel):
    """属性统计分析结果"""
    stat_name: str
    total_count: int
    min_value: float
    max_value: float
    mean: float
    median: float
    q25: float
    q75: float
    q90: float
    q95: float
    std_dev: float
    outlier_threshold: float
    outlier_count: int


class MonsterRanking(BaseModel):
    """妖怪属性排名结果"""
    stat_name: str
    value: float
    percentile: float
    tier: str
    rank: int
    total_count: int
    is_outlier: bool


@router.get("/analysis", response_model=Dict[str, StatsAnalysis])
async def get_stats_analysis(db: Session = Depends(get_db)):
    """获取所有属性的统计分析"""
    try:
        analysis = analyze_monster_stats(db)
        return analysis
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"统计分析失败: {str(e)}")


@router.get("/monster/{monster_id}/ranking", response_model=Dict[str, MonsterRanking])
async def get_monster_ranking(monster_id: int, db: Session = Depends(get_db)):
    """获取指定妖怪的属性排名"""
    try:
        # 检查妖怪是否存在
        monster = db.scalar(select(Monster).where(Monster.id == monster_id))
        if not monster:
            raise HTTPException(status_code=404, detail="妖怪未找到")
        
        ranking = calculate_monster_ranking(db, monster)
        return ranking
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"排名计算失败: {str(e)}")


@router.post("/batch-ranking", response_model=Dict[int, Dict[str, MonsterRanking]])
async def get_batch_monster_ranking(
    monster_ids: List[int], 
    db: Session = Depends(get_db)
):
    """批量获取多个妖怪的属性排名"""
    try:
        # 检查所有妖怪是否存在
        monsters = db.scalars(
            select(Monster).where(Monster.id.in_(monster_ids))
        ).all()
        
        if len(monsters) != len(monster_ids):
            found_ids = {m.id for m in monsters}
            missing_ids = set(monster_ids) - found_ids
            raise HTTPException(
                status_code=404, 
                detail=f"妖怪未找到: {list(missing_ids)}"
            )
        
        result = {}
        for monster in monsters:
            result[monster.id] = calculate_monster_ranking(db, monster)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量排名计算失败: {str(e)}")


@router.post("/clear-cache")
async def clear_stats_cache():
    """清除统计分析缓存"""
    try:
        stats_service._clear_cache()
        return {"message": "缓存已清除", "success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"清除缓存失败: {str(e)}")


@router.get("/cache-info")
async def get_cache_info():
    """获取缓存信息"""
    try:
        is_valid = stats_service._is_cache_valid()
        rankings_count = len(stats_service._rankings_cache)
        has_stats = bool(stats_service._stats_cache)
        
        timestamp = stats_service._cache_timestamp
        cache_age = None
        if timestamp:
            import time
            cache_age = int(time.time() - timestamp)
        
        return {
            "cache_valid": is_valid,
            "rankings_cached": rankings_count,
            "stats_cached": has_stats,
            "cache_age_seconds": cache_age,
            "expiry_seconds": stats_service.CACHE_EXPIRY_SECONDS
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取缓存信息失败: {str(e)}")