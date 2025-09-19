# server/app/services/backup_scheduler.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from .backup_service import backup_service

logger = logging.getLogger("kbxy.backup_scheduler")


class BackupScheduler:
    """备份任务调度器"""
    
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._check_interval = 3600  # 每小时检查一次
    
    async def start(self):
        """启动备份调度器"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Backup scheduler started")
    
    async def stop(self):
        """停止备份调度器"""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Backup scheduler stopped")
    
    async def _scheduler_loop(self):
        """调度器主循环"""
        while self._running:
            try:
                # 检查是否需要自动备份
                if backup_service.should_auto_backup():
                    logger.info("Starting automatic backup...")
                    backup_info = backup_service.create_auto_backup()
                    
                    if backup_info:
                        logger.info(f"Automatic backup created: {backup_info['name']}")
                    else:
                        logger.debug("Auto backup conditions not met")
                
                # 等待下次检查
                await asyncio.sleep(self._check_interval)
                
            except asyncio.CancelledError:
                logger.info("Backup scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"Error in backup scheduler: {e}")
                # 出错后等待较短时间再重试
                await asyncio.sleep(300)  # 5分钟后重试
    
    @property
    def is_running(self) -> bool:
        """检查调度器是否正在运行"""
        return self._running and self._task is not None and not self._task.done()


# 全局调度器实例
backup_scheduler = BackupScheduler()