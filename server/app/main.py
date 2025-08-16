# server/app/main.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .db import Base, engine
from .middleware import TraceIDMiddleware

# 常规路由
from .routes import health, monsters, importing, recalc, tasks, skills, backup, utils, derive, crawl, warehouse, types


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

# 初始化表
Base.metadata.create_all(bind=engine)

# 注册路由
app.include_router(health.router)
app.include_router(monsters.router)
app.include_router(importing.router)  # 导入与爬虫相关接口（含 4399 测试/导入）
app.include_router(backup.router)
app.include_router(utils.router)
app.include_router(skills.router)
app.include_router(recalc.router)
app.include_router(derive.router)
app.include_router(crawl.router)
app.include_router(warehouse.router, prefix="", tags=["warehouse"])
# 任务相关（如存在则使用）
app.include_router(tasks.router)
app.include_router(types.router)

# 可选：tags、roles
if HAS_TAGS:
    app.include_router(tags.router)
if HAS_ROLES:
    app.include_router(roles.router)


# 全局异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": "internal server error"})