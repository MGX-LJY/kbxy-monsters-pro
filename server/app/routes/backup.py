# server/app/routes/backup.py
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
import logging

from ..services.backup_service import backup_service

logger = logging.getLogger("kbxy.backup_routes")

router = APIRouter(prefix="/backup", tags=["backup"])


class BackupConfigUpdate(BaseModel):
    """备份配置更新请求"""
    auto_backup_enabled: Optional[bool] = None
    backup_interval_hours: Optional[int] = None
    max_backups: Optional[int] = None


class BackupCreate(BaseModel):
    """创建备份请求"""
    name: Optional[str] = None
    description: Optional[str] = None


class BackupInfo(BaseModel):
    """备份信息响应"""
    name: str
    created_at: str
    type: str  # manual, auto
    size: int
    files_count: Optional[int] = None
    description: Optional[str] = None
    backup_path: Optional[str] = None


class BackupListResponse(BaseModel):
    """备份列表响应"""
    total: int
    backups: List[Dict[str, Any]]


class RestoreResult(BaseModel):
    """还原结果响应"""
    success: bool
    message: str
    backup_name: str
    restored_at: str
    restored_files_count: Optional[int] = None
    restore_point_backup: Optional[str] = None


@router.get("/config")
async def get_backup_config() -> Dict[str, Any]:
    """获取备份配置"""
    try:
        return backup_service.get_config()
    except Exception as e:
        logger.error(f"Failed to get backup config: {e}")
        raise HTTPException(status_code=500, detail="获取备份配置失败")


@router.post("/config")
async def update_backup_config(config: BackupConfigUpdate) -> Dict[str, Any]:
    """更新备份配置"""
    try:
        config_dict = config.dict(exclude_unset=True)
        return backup_service.update_config(**config_dict)
    except Exception as e:
        logger.error(f"Failed to update backup config: {e}")
        raise HTTPException(status_code=500, detail="更新备份配置失败")


@router.post("/create")
async def create_backup(
    backup: BackupCreate = BackupCreate(), 
    background_tasks: BackgroundTasks = None
) -> Dict[str, Any]:
    """创建备份"""
    try:
        backup_info = backup_service.create_backup(backup.name)
        
        # 如果提供了描述，更新备份信息
        if backup.description:
            backup_info["description"] = backup.description
            # 这里应该更新备份信息文件，但为了简化暂时跳过
        
        return backup_info
    except Exception as e:
        logger.error(f"Failed to create backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_backups() -> BackupListResponse:
    """列出所有备份"""
    try:
        backups = backup_service.list_backups()
        return BackupListResponse(
            total=len(backups),
            backups=backups
        )
    except Exception as e:
        logger.error(f"Failed to list backups: {e}")
        raise HTTPException(status_code=500, detail="获取备份列表失败")


@router.get("/{backup_name}/info")
async def get_backup_info(backup_name: str) -> Dict[str, Any]:
    """获取特定备份的详细信息"""
    try:
        backup_info = backup_service.get_backup_info(backup_name)
        if not backup_info:
            raise HTTPException(status_code=404, detail="备份不存在")
        return backup_info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get backup info {backup_name}: {e}")
        raise HTTPException(status_code=500, detail="获取备份信息失败")


@router.post("/{backup_name}/restore")
async def restore_backup(backup_name: str) -> RestoreResult:
    """还原备份"""
    try:
        result = backup_service.restore_backup(backup_name)
        return RestoreResult(
            success=True,
            message="备份还原成功",
            backup_name=backup_name,
            restored_at=result["restored_at"],
            restored_files_count=result.get("restored_files_count"),
            restore_point_backup=result.get("restore_point_backup")
        )
    except Exception as e:
        logger.error(f"Failed to restore backup {backup_name}: {e}")
        return RestoreResult(
            success=False,
            message=str(e),
            backup_name=backup_name,
            restored_at="",
        )


@router.delete("/{backup_name}")
async def delete_backup(backup_name: str) -> Dict[str, Any]:
    """删除备份"""
    try:
        success = backup_service.delete_backup(backup_name)
        if not success:
            raise HTTPException(status_code=404, detail="备份不存在或删除失败")
        
        return {"message": f"备份 {backup_name} 已删除", "success": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete backup {backup_name}: {e}")
        raise HTTPException(status_code=500, detail="删除备份失败")


@router.post("/auto-backup")
async def trigger_auto_backup() -> Dict[str, Any]:
    """触发自动备份（如果满足条件）"""
    try:
        backup_info = backup_service.create_auto_backup()
        
        if backup_info is None:
            return {
                "message": "自动备份未启用或时间间隔未到",
                "created": False
            }
        
        return {
            "message": "自动备份创建成功",
            "created": True,
            "backup_info": backup_info
        }
    except Exception as e:
        logger.error(f"Failed to create auto backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_backup_status() -> Dict[str, Any]:
    """获取备份状态"""
    try:
        config = backup_service.get_config()
        backups = backup_service.list_backups()
        
        total_size = sum(backup.get("size", 0) for backup in backups)
        latest_backup = backups[0] if backups else None
        
        return {
            "total_backups": len(backups),
            "total_size": total_size,
            "latest_backup": latest_backup,
            "auto_backup_enabled": config.get("auto_backup_enabled", False),
            "last_backup_time": config.get("last_backup_time"),
            "should_auto_backup": backup_service.should_auto_backup()
        }
    except Exception as e:
        logger.error(f"Failed to get backup status: {e}")
        raise HTTPException(status_code=500, detail="获取备份状态失败")