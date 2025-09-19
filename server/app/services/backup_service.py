# server/app/services/backup_service.py
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import json
import logging

from ..config import settings, PROJECT_ROOT

logger = logging.getLogger("kbxy.backup")


class BackupService:
    """时光机式备份服务 - 类似macOS Time Machine"""
    
    def __init__(self):
        self.backup_root = PROJECT_ROOT / "data" / "backup"
        self.backup_root.mkdir(parents=True, exist_ok=True)
        
        # 备份配置文件
        self.config_file = self.backup_root / "backup_config.json"
        self._load_config()
    
    def _load_config(self):
        """加载备份配置"""
        default_config = {
            "auto_backup_enabled": False,
            "backup_interval_hours": 24,  # 24小时自动备份一次
            "max_backups": 30,  # 最多保留30个备份
            "last_backup_time": None
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.config = {**default_config, **config}
            except Exception as e:
                logger.error(f"Failed to load backup config: {e}")
                self.config = default_config
        else:
            self.config = default_config
            self._save_config()
    
    def _save_config(self):
        """保存备份配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save backup config: {e}")
    
    def get_config(self) -> Dict[str, Any]:
        """获取备份配置"""
        return self.config.copy()
    
    def update_config(self, **kwargs) -> Dict[str, Any]:
        """更新备份配置"""
        for key, value in kwargs.items():
            if key in self.config:
                self.config[key] = value
        self._save_config()
        return self.config.copy()
    
    def create_backup(self, backup_name: Optional[str] = None) -> Dict[str, Any]:
        """创建备份
        
        Args:
            backup_name: 备份名称，如果不提供则自动生成
        
        Returns:
            备份信息字典
        """
        timestamp = datetime.now()
        
        if not backup_name:
            # 简化备份文件名
            backup_name = timestamp.strftime('%m%d_%H%M')
        
        backup_dir = self.backup_root / backup_name
        backup_dir.mkdir(exist_ok=True)
        
        try:
            # 创建备份信息文件
            backup_info = {
                "name": backup_name,
                "created_at": timestamp.isoformat(),
                "type": "manual",  # manual 或 auto
                "size": 0,
                "files_count": 0,
                "description": "手动备份"
            }
            
            # 1. 备份数据库
            db_backup_path = backup_dir / "database"
            db_backup_path.mkdir(exist_ok=True)
            
            data_dir = PROJECT_ROOT / "data"
            db_files_backed = []
            
            for db_file in data_dir.glob("*.db*"):
                if db_file.is_file():
                    dest_path = db_backup_path / db_file.name
                    shutil.copy2(db_file, dest_path)
                    db_files_backed.append(db_file.name)
                    backup_info["files_count"] += 1
            
            # 2. 备份怪物图片
            images_backup_path = backup_dir / "images"
            images_backup_path.mkdir(exist_ok=True)
            
            images_source = PROJECT_ROOT / "server" / "images" / "monsters"
            images_backed = []
            
            if images_source.exists():
                for image_file in images_source.iterdir():
                    if image_file.is_file() and image_file.suffix.lower() in ['.jpg', '.jpeg', '.png']:
                        dest_path = images_backup_path / image_file.name
                        shutil.copy2(image_file, dest_path)
                        images_backed.append(image_file.name)
                        backup_info["files_count"] += 1
            
            # 3. 创建压缩包（可选，节省空间）
            zip_path = backup_dir.with_suffix('.zip')
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 添加数据库文件
                for db_file in db_backup_path.iterdir():
                    zipf.write(db_file, f"database/{db_file.name}")
                
                # 添加图片文件
                for img_file in images_backup_path.iterdir():
                    zipf.write(img_file, f"images/{img_file.name}")
            
            # 删除临时目录，只保留zip
            shutil.rmtree(backup_dir)
            
            # 计算备份大小
            backup_info["size"] = zip_path.stat().st_size
            backup_info["backup_path"] = str(zip_path.relative_to(self.backup_root))
            backup_info["database_files"] = db_files_backed
            backup_info["image_files"] = images_backed[:10]  # 只记录前10个图片文件名
            backup_info["total_images"] = len(images_backed)
            
            # 保存备份信息
            info_file = zip_path.with_suffix('.json')
            with open(info_file, 'w', encoding='utf-8') as f:
                json.dump(backup_info, f, ensure_ascii=False, indent=2)
            
            # 更新配置中的最后备份时间
            self.config["last_backup_time"] = timestamp.isoformat()
            self._save_config()
            
            # 清理旧备份
            self._cleanup_old_backups()
            
            logger.info(f"Backup created successfully: {backup_name}")
            return backup_info
            
        except Exception as e:
            logger.error(f"Failed to create backup {backup_name}: {e}")
            # 清理失败的备份
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            zip_path = backup_dir.with_suffix('.zip')
            if zip_path.exists():
                zip_path.unlink()
            raise Exception(f"备份创建失败: {str(e)}")
    
    def list_backups(self) -> List[Dict[str, Any]]:
        """列出所有备份"""
        backups = []
        
        for backup_zip in self.backup_root.glob("*.zip"):
            info_file = backup_zip.with_suffix('.json')
            
            if info_file.exists():
                try:
                    with open(info_file, 'r', encoding='utf-8') as f:
                        backup_info = json.load(f)
                    backups.append(backup_info)
                except Exception as e:
                    logger.error(f"Failed to read backup info {info_file}: {e}")
            else:
                # 没有信息文件，创建基础信息
                stat = backup_zip.stat()
                backup_info = {
                    "name": backup_zip.stem,
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "type": "unknown",
                    "size": stat.st_size,
                    "backup_path": backup_zip.name,
                    "description": "未知备份"
                }
                backups.append(backup_info)
        
        # 按创建时间倒序排列
        backups.sort(key=lambda x: x["created_at"], reverse=True)
        return backups
    
    def get_backup_info(self, backup_name: str) -> Optional[Dict[str, Any]]:
        """获取特定备份的详细信息"""
        info_file = self.backup_root / f"{backup_name}.json"
        
        if not info_file.exists():
            return None
        
        try:
            with open(info_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read backup info {backup_name}: {e}")
            return None
    
    def restore_backup(self, backup_name: str) -> Dict[str, Any]:
        """还原备份
        
        Args:
            backup_name: 备份名称
        
        Returns:
            还原结果信息
        """
        backup_zip = self.backup_root / f"{backup_name}.zip"
        
        if not backup_zip.exists():
            raise Exception(f"备份文件不存在: {backup_name}")
        
        try:
            # 解压备份文件
            temp_dir = self.backup_root / f"temp_restore_{backup_name}"
            temp_dir.mkdir(exist_ok=True)
            
            with zipfile.ZipFile(backup_zip, 'r') as zipf:
                zipf.extractall(temp_dir)
            
            restored_files = []
            
            # 1. 还原数据库文件
            db_backup_dir = temp_dir / "database"
            data_dir = PROJECT_ROOT / "data"
            
            if db_backup_dir.exists():
                for db_file in db_backup_dir.iterdir():
                    if db_file.is_file():
                        dest_path = data_dir / db_file.name
                        shutil.copy2(db_file, dest_path)
                        restored_files.append(f"database/{db_file.name}")
            
            # 2. 还原图片文件
            images_backup_dir = temp_dir / "images"
            images_target_dir = PROJECT_ROOT / "server" / "images" / "monsters"
            images_target_dir.mkdir(parents=True, exist_ok=True)
            
            if images_backup_dir.exists():
                # 清空现有图片
                for existing_img in images_target_dir.iterdir():
                    if existing_img.is_file():
                        existing_img.unlink()
                
                for img_file in images_backup_dir.iterdir():
                    if img_file.is_file():
                        dest_path = images_target_dir / img_file.name
                        shutil.copy2(img_file, dest_path)
                        restored_files.append(f"images/{img_file.name}")
            
            # 清理临时目录
            shutil.rmtree(temp_dir)
            
            result = {
                "backup_name": backup_name,
                "restored_at": datetime.now().isoformat(),
                "restored_files_count": len(restored_files),
                "restored_files": restored_files[:20]  # 只返回前20个文件名
            }
            
            logger.info(f"Backup restored successfully: {backup_name}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to restore backup {backup_name}: {e}")
            # 清理临时文件
            temp_dir = self.backup_root / f"temp_restore_{backup_name}"
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            raise Exception(f"备份还原失败: {str(e)}")
    
    def delete_backup(self, backup_name: str) -> bool:
        """删除备份"""
        backup_zip = self.backup_root / f"{backup_name}.zip"
        info_file = self.backup_root / f"{backup_name}.json"
        
        try:
            if backup_zip.exists():
                backup_zip.unlink()
            if info_file.exists():
                info_file.unlink()
            
            logger.info(f"Backup deleted: {backup_name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete backup {backup_name}: {e}")
            return False
    
    def _cleanup_old_backups(self):
        """清理旧备份，保持最大数量限制"""
        max_backups = self.config.get("max_backups", 30)
        backups = self.list_backups()
        
        if len(backups) > max_backups:
            # 删除最旧的备份
            backups_to_delete = backups[max_backups:]
            for backup in backups_to_delete:
                self.delete_backup(backup["name"])
            
            logger.info(f"Cleaned up {len(backups_to_delete)} old backups")
    
    def should_auto_backup(self) -> bool:
        """检查是否应该进行自动备份"""
        if not self.config.get("auto_backup_enabled", False):
            return False
        
        last_backup = self.config.get("last_backup_time")
        if not last_backup:
            return True
        
        try:
            last_backup_dt = datetime.fromisoformat(last_backup)
            hours_since_last = (datetime.now() - last_backup_dt).total_seconds() / 3600
            interval_hours = self.config.get("backup_interval_hours", 24)
            
            return hours_since_last >= interval_hours
        except Exception as e:
            logger.error(f"Failed to check auto backup timing: {e}")
            return False
    
    def create_auto_backup(self) -> Optional[Dict[str, Any]]:
        """创建自动备份"""
        if not self.should_auto_backup():
            return None
        
        # 简化自动备份文件名
        backup_name = f"auto_{datetime.now().strftime('%m%d_%H%M')}"
        backup_info = self.create_backup(backup_name)
        backup_info["type"] = "auto"
        backup_info["description"] = "自动备份"
        
        # 更新备份信息文件
        info_file = self.backup_root / f"{backup_name}.json"
        with open(info_file, 'w', encoding='utf-8') as f:
            json.dump(backup_info, f, ensure_ascii=False, indent=2)
        
        return backup_info


# 单例实例
backup_service = BackupService()