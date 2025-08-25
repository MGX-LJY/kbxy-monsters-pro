# server/app/main.py
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles  # ← 新增

from .config import settings
from .db import Base, engine, startup_db_report_lines, DB_INFO
from .middleware import TraceIDMiddleware

from .routes import (
    health, monsters, skills, backup, utils, derive, crawl,
    warehouse, types, collections,
)
from .routes import images as images_routes  # ← 新增

# 可选路由（不存在也不报错）
try:
    from .routes import tags
    HAS_TAGS = True
except Exception:
    HAS_TAGS = False

try:
    from .routes import roles
    HAS_ROLES = True
except Exception:
    HAS_ROLES = False

logger = logging.getLogger("kbxy")

app = FastAPI(title=settings.app_name)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 追踪ID中间件
app.add_middleware(TraceIDMiddleware)

# ⚠️ 移除：不要在模块顶层执行 create_all（会与 --reload 竞态）
# Base.metadata.create_all(bind=engine)

# ---- 静态图片挂载 ----
def _images_dir() -> str:
    env_dir = os.getenv("MONSTERS_MEDIA_DIR")
    if env_dir:
        p = Path(env_dir).expanduser().resolve(); p.mkdir(parents=True, exist_ok=True); return str(p)
    here = Path(__file__).resolve().parent  # server/app
    p = here.parent / "images" / "monsters" # server/images/monsters
    p.mkdir(parents=True, exist_ok=True)
    return str(p)

app.mount("/media/monsters", StaticFiles(directory=_images_dir(), html=False), name="monsters_media")

# 注册路由（基础）
app.include_router(health.router)
app.include_router(monsters.router)
app.include_router(backup.router)
app.include_router(utils.router)
app.include_router(skills.router)
app.include_router(derive.router)
app.include_router(crawl.router)
app.include_router(warehouse.router, prefix="", tags=["warehouse"])
app.include_router(types.router)
app.include_router(collections.router, prefix="", tags=["collections"])
app.include_router(images_routes.router)  # ← 新增

# 可选：tags、roles
if HAS_TAGS:
    app.include_router(tags.router)
if HAS_ROLES:
    app.include_router(roles.router)

def _init_schema_once_with_lock():
    """
    只在 dev/test 环境做一次 schema 初始化（create_all, checkfirst=True），
    用文件锁避免 uvicorn --reload 进程/多次导入的竞态。
    """
    if settings.app_env not in ("dev", "test"):
        return

    parent_dir = DB_INFO.get("db_parent_dir")
    if not parent_dir:
        try:
            Base.metadata.create_all(bind=engine, checkfirst=True)
            logger.info("[startup] schema create_all (DATABASE_URL) executed.")
        except Exception:
            logger.exception("[startup] schema init failed (DATABASE_URL).")
        return

    lock_dir = Path(str(parent_dir))
    lock_file = lock_dir / ".schema.init.lock"

    acquired = False
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        acquired = True
    except FileExistsError:
        acquired = False

    if acquired:
        try:
            Base.metadata.create_all(bind=engine, checkfirst=True)
            logger.info("[startup] schema create_all executed (checkfirst=True).")
        except Exception:
            logger.exception("[startup] schema init failed.")
        finally:
            try:
                os.remove(lock_file)
            except Exception:
                pass
    else:
        logger.info("[startup] another process is initializing schema or it already exists; skip create_all.")

# 启动日志：环境 + DB 路径三件套 +（受控的）schema 初始化
@app.on_event("startup")
async def _startup_logs_and_schema():
    logger.info(f"[startup] APP_ENV={settings.app_env} APP_NAME={settings.app_name}")
    for line in startup_db_report_lines():
        logger.info(f"[startup] {line}")
    _init_schema_once_with_lock()
    # 预热图片索引（可选）
    try:
        from .services.image_service import get_image_resolver
        get_image_resolver().reindex()
    except Exception:
        logger.exception("[startup] image resolver warmup failed.")

# 全局异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "internal server error"})