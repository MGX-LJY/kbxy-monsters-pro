from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from .config import settings
from .db import Base, engine
from .routes import health, monsters, importing, tags, recalc, tasks
from .middleware import TraceIDMiddleware

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
app.include_router(tags.router)
app.include_router(recalc.router)
app.include_router(tasks.router)

def _problem(status: int, code: str, title: str, detail: str, trace_id: str):
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            "trace_id": trace_id,
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    trace_id = getattr(request.state, "trace_id", "")
    return _problem(exc.status_code, "HTTP_ERROR", "HTTP Error", exc.detail or "HTTP error", trace_id)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    trace_id = getattr(request.state, "trace_id", "")
    return _problem(422, "VALIDATION_ERROR", "Validation Error", str(exc.errors()), trace_id)

@app.exception_handler(Exception)
async def problem_handler(request: Request, exc: Exception):
    trace_id = getattr(request.state, "trace_id", "")
    return _problem(500, "INTERNAL_ERROR", "Internal Server Error", str(exc), trace_id)
