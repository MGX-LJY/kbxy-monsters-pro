from __future__ import annotations

import os
import logging
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import settings

logger = logging.getLogger("kbxy")

# 供启动日志使用的信息
DB_INFO: dict[str, str | bool | int | float | None] = {
    "using_database_url": False,       # 是否使用了环境变量 DATABASE_URL
    "db_file_abs_path": None,          # 本地 DB 绝对路径
    "db_parent_dir": None,             # 父目录
    "writable": None,                  # OK / FAIL / IGNORED
    "busy_timeout_ms": None,           # 实际生效的 busy_timeout（毫秒）
    "connect_timeout_s": settings.sqlite_connect_timeout_s,  # 连接时的超时时间（秒）
    "note": "",                        # 说明文字
}

# 计算最终连接串优先级：DATABASE_URL > 本地文件
_database_url_env = os.getenv("DATABASE_URL")
if _database_url_env:
    FINAL_DATABASE_URL = _database_url_env
    DB_INFO["using_database_url"] = True
    # 依旧计算一遍本地路径，但注明被忽略，便于排障
    p = settings.resolved_local_db_path()
    DB_INFO["db_file_abs_path"] = str(p)
    DB_INFO["db_parent_dir"] = str(p.parent)
    DB_INFO["writable"] = "IGNORED"
    DB_INFO["note"] = "DATABASE_URL is set; local SQLite file path is ignored."
else:
    p: Path = settings.resolved_local_db_path()

    # 确保 /data 目录存在
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"[db] ensured data directory exists: {p.parent}")
    except Exception as e:
        logger.error(f"[db] failed to create data directory {p.parent}: {e}")

    # 检查父目录写权限
    writable_ok = os.access(p.parent, os.W_OK)
    DB_INFO["db_file_abs_path"] = str(p)
    DB_INFO["db_parent_dir"] = str(p.parent)
    DB_INFO["writable"] = "OK" if writable_ok else "FAIL"

    FINAL_DATABASE_URL = f"sqlite+pysqlite:///{p}"

# 连接参数：
# - check_same_thread=False：允许跨线程使用同一连接池中的连接
# - timeout：sqlite3.connect 的“打开连接时等待锁”超时（秒）
engine = create_engine(
    FINAL_DATABASE_URL,
    echo=False,
    future=True,
    connect_args={
        "check_same_thread": False,
        "timeout": settings.sqlite_connect_timeout_s,
    },
)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    每个新连接建立时设置 SQLite PRAGMA：
    - WAL、foreign_keys、synchronous
    - busy_timeout（毫秒），用于写锁等待
    并回读 busy_timeout 以便启动日志展示实际值
    """
    cursor = dbapi_connection.cursor()
    # 写入 PRAGMA
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.execute(f"PRAGMA busy_timeout={int(settings.sqlite_busy_timeout_ms)};")
    # 回读 busy_timeout
    cursor.execute("PRAGMA busy_timeout;")
    row = cursor.fetchone()
    try:
        DB_INFO["busy_timeout_ms"] = int(row[0]) if row and row[0] is not None else None
    except Exception:
        DB_INFO["busy_timeout_ms"] = None
    cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

def startup_db_report_lines() -> list[str]:
    """
    返回用于启动日志的多行信息：
    - DB 绝对路径 / 父目录 / 写权限
    - Busy timeout (ms) / Connect timeout (s)
    - （可选）说明
    """
    lines: list[str] = []
    if DB_INFO["using_database_url"]:
        lines.append("DB in use: DATABASE_URL (local file ignored)")
    lines.append(f"DB absolute path: {DB_INFO['db_file_abs_path']}")
    lines.append(f"Parent dir: {DB_INFO['db_parent_dir']}")
    lines.append(f"Writable: {DB_INFO['writable']}")
    lines.append(f"Busy timeout (ms): {DB_INFO['busy_timeout_ms']}")
    lines.append(f"Connect timeout (s): {DB_INFO['connect_timeout_s']}")
    note = DB_INFO.get("note")
    if note:
        lines.append(str(note))
    return lines