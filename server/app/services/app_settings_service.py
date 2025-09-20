# server/app/services/app_settings_service.py
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from ..config import settings

logger = logging.getLogger("kbxy.app_settings")


class AppSettingsService:
    """应用设置管理服务 - 支持Docker环境的持久化设置"""
    
    def __init__(self):
        # 检查是否在Docker环境中，优先使用环境变量指定的路径
        if os.getenv("KBXY_DB_PATH"):
            # Docker环境，使用环境变量路径的目录
            db_path = Path(os.getenv("KBXY_DB_PATH"))
            self.data_root = db_path.parent
        else:
            # 本地环境，使用PROJECT_ROOT
            from ..config import PROJECT_ROOT
            self.data_root = PROJECT_ROOT / "data"
        
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.settings_file = self.data_root / "app_settings.json"
        
        # 默认设置 - 匹配前端设置需求
        self.default_settings = {
            "pageSize": 20,           # 每页显示数量
            "crawlLimit": "",         # 图鉴爬取数量上限
            "backupSettings": {       # 备份设置
                "auto_backup_enabled": False,
                "backup_interval_hours": 24,
                "max_backups": 30
            }
        }
        
        self._load_settings()
    
    def _load_settings(self):
        """加载应用设置"""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                # 合并默认设置和加载的设置
                self.current_settings = {**self.default_settings, **loaded_settings}
            else:
                self.current_settings = self.default_settings.copy()
                self._save_settings()
        except Exception as e:
            logger.error(f"Failed to load app settings: {e}")
            self.current_settings = self.default_settings.copy()
    
    def _save_settings(self):
        """保存应用设置"""
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.current_settings, f, ensure_ascii=False, indent=2)
            logger.info("App settings saved successfully")
        except Exception as e:
            logger.error(f"Failed to save app settings: {e}")
            raise Exception(f"设置保存失败: {str(e)}")
    
    def get_all_settings(self) -> Dict[str, Any]:
        """获取所有应用设置"""
        return self.current_settings.copy()
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """获取特定设置"""
        keys = key.split('.')
        value = self.current_settings
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """批量更新设置"""
        def deep_update(target: dict, source: dict) -> dict:
            for key, value in source.items():
                if isinstance(value, dict) and key in target and isinstance(target[key], dict):
                    deep_update(target[key], value)
                else:
                    target[key] = value
            return target
        
        deep_update(self.current_settings, updates)
        self._save_settings()
        return self.current_settings.copy()
    
    def update_setting(self, key: str, value: Any) -> Dict[str, Any]:
        """更新单个设置"""
        keys = key.split('.')
        target = self.current_settings
        
        # 导航到目标位置
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        
        # 设置值
        target[keys[-1]] = value
        self._save_settings()
        return self.current_settings.copy()
    
    def reset_settings(self) -> Dict[str, Any]:
        """重置为默认设置"""
        self.current_settings = self.default_settings.copy()
        self._save_settings()
        return self.current_settings.copy()
    
    def export_settings(self) -> str:
        """导出设置为JSON字符串"""
        return json.dumps(self.current_settings, ensure_ascii=False, indent=2)
    
    def import_settings(self, settings_json: str) -> Dict[str, Any]:
        """从JSON字符串导入设置"""
        try:
            imported_settings = json.loads(settings_json)
            # 验证导入的设置格式
            if not isinstance(imported_settings, dict):
                raise ValueError("Invalid settings format")
            
            self.current_settings = {**self.default_settings, **imported_settings}
            self._save_settings()
            return self.current_settings.copy()
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {str(e)}")
        except Exception as e:
            raise Exception(f"Settings import failed: {str(e)}")


# 单例实例
app_settings_service = AppSettingsService()