# server/app/main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .config import settings
from .db import Base, engine
from .middleware import TraceIDMiddleware

# 路由
from .routes import health, monsters, importing, tags, recalc, tasks, skills
# 可选 roles
try:
    from .routes import roles
    HAS_ROLES = True
except Exception:
    HAS_ROLES = False

# 可选：技能维护后台
try:
    from .routes import skills_admin
    HAS_SKILLS_ADMIN = True
except Exception:
    HAS_SKILLS_ADMIN = False

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

# 初始化表（你说会删库重建，这里直接 create_all）
Base.metadata.create_all(bind=engine)

# 路由挂载
app.include_router(health.router)
app.include_router(monsters.router)
app.include_router(importing.router)
app.include_router(tags.router)
app.include_router(recalc.router)
app.include_router(tasks.router)
app.include_router(skills.router)
if HAS_SKILLS_ADMIN:
    app.include_router(skills_admin.router)
if HAS_ROLES:
    app.include_router(roles.router)

# 统一异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "internal server error"})