import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from starlette.requests import Request

class TraceIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        trace_id = str(uuid.uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response
