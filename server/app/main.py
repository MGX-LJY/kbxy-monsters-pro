# server/app/main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import settings
from .db import Base, engine
from .middleware import TraceIDMiddleware
from .routes import skills_admin
from .routes import utils
from .routes import backup
from .routes import tags  # 新增


# 路由
from .routes import health, monsters, importing, tags, recalc, tasks, skills
# roles 可能还没合并就先兜底
try:
    from .routes import roles
    HAS_ROLES = True
except Exception:
    HAS_ROLES = False

app = FastAPI(title=settings.app_name)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# TraceID
app.add_middleware(TraceIDMiddleware)

# 初始化表
Base.metadata.create_all(bind=engine)

# 路由挂载
app.include_router(health.router)
app.include_router(monsters.router)
app.include_router(importing.router)
app.include_router(tags.router)
app.include_router(recalc.router)
app.include_router(tasks.router)
app.include_router(skills.router)
app.include_router(skills_admin.router)
app.include_router(utils.router)
app.include_router(backup.router)
app.include_router(tags.router)
if HAS_ROLES:
    app.include_router(roles.router)

# 统一异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # 这里不要泄露内部错误细节，日志里再看
    return JSONResponse(status_code=500, content={"detail": "internal server error"})