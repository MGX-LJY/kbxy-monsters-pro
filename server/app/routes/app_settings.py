# server/app/routes/app_settings.py
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from pydantic import BaseModel

from ..services.app_settings_service import app_settings_service

router = APIRouter(prefix="/app-settings", tags=["app-settings"])


class SettingUpdateRequest(BaseModel):
    key: str
    value: Any


class SettingsUpdateRequest(BaseModel):
    settings: Dict[str, Any]


class SettingsImportRequest(BaseModel):
    settings_json: str


@router.get("/")
async def get_all_settings() -> Dict[str, Any]:
    """获取所有应用设置"""
    try:
        return {
            "success": True,
            "data": app_settings_service.get_all_settings()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{setting_key}")
async def get_setting(setting_key: str) -> Dict[str, Any]:
    """获取特定设置"""
    try:
        value = app_settings_service.get_setting(setting_key)
        return {
            "success": True,
            "data": {
                "key": setting_key,
                "value": value
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{setting_key}")
async def update_setting(setting_key: str, request: SettingUpdateRequest) -> Dict[str, Any]:
    """更新单个设置"""
    try:
        updated_settings = app_settings_service.update_setting(request.key, request.value)
        return {
            "success": True,
            "message": f"设置 {request.key} 已更新",
            "data": updated_settings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/")
async def update_settings(request: SettingsUpdateRequest) -> Dict[str, Any]:
    """批量更新设置"""
    try:
        updated_settings = app_settings_service.update_settings(request.settings)
        return {
            "success": True,
            "message": "设置已更新",
            "data": updated_settings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_settings() -> Dict[str, Any]:
    """重置为默认设置"""
    try:
        default_settings = app_settings_service.reset_settings()
        return {
            "success": True,
            "message": "设置已重置为默认值",
            "data": default_settings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/export/json")
async def export_settings() -> Dict[str, Any]:
    """导出设置为JSON"""
    try:
        settings_json = app_settings_service.export_settings()
        return {
            "success": True,
            "data": {
                "settings_json": settings_json
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import/json")
async def import_settings(request: SettingsImportRequest) -> Dict[str, Any]:
    """从JSON导入设置"""
    try:
        imported_settings = app_settings_service.import_settings(request.settings_json)
        return {
            "success": True,
            "message": "设置导入成功",
            "data": imported_settings
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))