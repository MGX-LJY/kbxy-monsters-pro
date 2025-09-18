from __future__ import annotations

from pydantic import BaseModel
from pathlib import Path
import os

# 项目根目录：.../<project-root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 不同环境的默认 DB 文件名
ENV_DB_FILENAMES = {
    "dev": "kbxy-dev.db",
    "test": "kbxy-test.db",
}

class Settings(BaseModel):
    app_name: str = "kbxy-monsters-pro"
    # 仅支持 dev / test，其他值一律回落到 dev
    app_env: str = os.getenv("APP_ENV", "dev").lower()
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # 兼容历史：如果设置了 KBXY_DB_PATH（文件名或路径），作为本地文件名/路径覆盖
    kbxy_db_path: str | None = os.getenv("KBXY_DB_PATH")

    # 新增：SQLite 忙等待（毫秒）与连接超时（秒）
    # - busy_timeout_ms：当遇到写锁时，SQLite 在本连接上最多等待多久（毫秒）
    # - connect_timeout_s：sqlite3.connect 的"打开连接时等待锁"超时（秒）
    sqlite_busy_timeout_ms: int = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "4000"))
    sqlite_connect_timeout_s: float = float(os.getenv("SQLITE_CONNECT_TIMEOUT_S", "5"))

    # 新增：标签识别配置
    # - tag_use_selected_only：是否只使用推荐技能进行标签识别（默认True）
    tag_use_selected_only: bool = os.getenv("TAG_USE_SELECTED_ONLY", "true").lower() in {"true", "1", "yes"}

    def normalized_env(self) -> str:
        return "test" if self.app_env == "test" else "dev"

    def default_db_filename(self) -> str:
        return ENV_DB_FILENAMES[self.normalized_env()]

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