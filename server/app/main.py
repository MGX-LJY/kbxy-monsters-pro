# server/app/main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import settings
from .db import Base, engine
from .middleware import TraceIDMiddleware

# 已有路由
from .routes import health, monsters, importing, recalc, tasks, skills, backup, utils
from .routes import tags  # 如无可删除此行以及 include_router
# 新增：派生/自动匹配接口
from .routes import derive

# roles 可能不存在则兜底
try:
    from .routes import roles
    HAS_ROLES = True
except Exception:
    HAS_ROLES = False

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TraceIDMiddleware)

Base.metadata.create_all(bind=engine)

app.include_router(health.router)
app.include_router(monsters.router)
app.include_router(importing.router)
app.include_router(backup.router)
app.include_router(utils.router)
app.include_router(skills.router)
app.include_router(recalc.router)
app.include_router(derive.router)  # << 新增
# 如你有 tags/roles，则保留
try:
    app.include_router(tags.router)
except Exception:
    pass
if HAS_ROLES:
    app.include_router(roles.router)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "internal server error"})