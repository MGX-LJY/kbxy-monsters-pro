from __future__ import annotations

from pydantic import BaseModel
from pathlib import Path
import os

# 项目根目录：.../<project-root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 默认数据库文件名（仅开发环境）
DEFAULT_DB_FILENAME = "kbxy-dev.db"

class Settings(BaseModel):
    app_name: str = "kbxy-monsters-pro"
    # 环境：dev（本地开发）或 prod（docker生产环境），默认dev
    app_env: str = os.getenv("APP_ENV", "dev").lower()
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # 数据库路径：可通过 KBXY_DB_PATH 环境变量覆盖
    kbxy_db_path: str | None = os.getenv("KBXY_DB_PATH")

    # SQLite 超时配置
    # - busy_timeout_ms：遇到写锁时的等待时间（毫秒）
    # - connect_timeout_s：连接超时时间（秒）
    sqlite_busy_timeout_ms: int = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "4000"))
    sqlite_connect_timeout_s: float = float(os.getenv("SQLITE_CONNECT_TIMEOUT_S", "5"))

    # 标签识别配置：是否只使用推荐技能进行标签识别
    tag_use_selected_only: bool = os.getenv("TAG_USE_SELECTED_ONLY", "true").lower() in {"true", "1", "yes"}

    def default_db_filename(self) -> str:
        """返回默认数据库文件名"""
        return DEFAULT_DB_FILENAME

    def resolved_local_db_path(self) -> Path:
        """
        计算本地 SQLite 文件的最终绝对路径：
        - 若设置了 KBXY_DB_PATH：
            - 若为绝对路径：直接使用
            - 若为相对路径或仅文件名：拼到 <project-root>/data 下
        - 否则使用默认文件名（随环境变化），也拼到 <project-root>/data 下
        """
        raw = self.kbxy_db_path
        if raw:
            p = Path(os.path.expanduser(raw))
            if not p.is_absolute():
                p = PROJECT_ROOT / "data" / p
        else:
            p = PROJECT_ROOT / "data" / self.default_db_filename()
        return p.resolve()

settings = Settings()