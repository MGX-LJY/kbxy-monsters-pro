---
file: server/app/middleware.py
type: infra
owner: backend
updated: 2025-08-23
stability: stable
deps: [starlette, fastapi]
exposes: [TraceIDMiddleware]

# middleware.py · 快速卡片

## TL;DR（30 秒）
- 职责：为每个请求生成一个 `trace_id`（UUID4），写入 `request.state.trace_id`，并在响应头加 `x-trace-id`，用于链路追踪与问题定位。
- 当前策略：**始终新建** `trace_id`，不读取客户端传入的同名头。
- 常见坑
  1) **无法复用上游 TraceID**：网关/前端若已传 `x-trace-id`，现在不会沿用，导致跨服务链路断裂。
  2) **异常路径的头设置**：若下游抛未捕获异常，中间件需确保仍能把 `x-trace-id` 写回（建议 `try/finally`）。
  3) **异步任务上下文丢失**：`request.state.trace_id` 在后台任务/线程内不可见（建议切 `contextvars`）。

## 职责与边界
- 做什么：贯穿请求-响应的最小追踪 ID 注入。
- 不做什么：不记录日志、不落库、不关心采样/追踪系统（如 OTEL）。

## 公开接口
- `class TraceIDMiddleware(BaseHTTPMiddleware)`

## 依赖与数据流
- 上游：无（当前不读取来访 `x-trace-id`）。
- 下游：
  - `request.state.trace_id`：供路由/服务层日志使用。
  - 响应头 `x-trace-id`：回传给调用方，便于报错时定位。

## 交互细节
- 生成方式：`uuid.uuid4()` → `str`。
- 注入点：`dispatch()` 内先写 `request.state`，调用 `call_next(request)` 后设置响应头。

## 示例（在路由/服务层写日志）
Python:
```py
from fastapi import APIRouter, Request
import logging

router = APIRouter()
log = logging.getLogger(__name__)

@router.get("/health")
def health(request: Request):
    log.info("health probe", extra={"trace_id": getattr(request.state, "trace_id", None)})
    return {"ok": True}
```

Shell（查看回包头）:
```
curl -i http://127.0.0.1:8000/health | grep -i x-trace-id
```

## 变更指南（How to change safely）
- 兼容上游 TraceID（推荐）  
  允许复用已存在的头，空缺时再生成：
  ```py
  incoming = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
  trace_id = incoming or str(uuid.uuid4())
  ```
- 异常也写回头（稳妥）  
  用 `try/finally` 确保无论 `call_next` 成功与否，都设置响应头：
  ```py
  async def dispatch(...):
      trace_id = incoming or str(uuid.uuid4())
      request.state.trace_id = trace_id
      try:
          response = await call_next(request)
      except Exception:
          # 可选择在此记录日志，随后让全局异常处理接管
          raise
      finally:
          # 注意：需要有 response 对象时再设置头；否则交给全局异常处理器设置
          pass
  ```
  更简洁做法是在全局异常处理器中也读取 `request.state.trace_id` 并写入响应头。
- 后台/跨线程可见性  
  如需在 `BackgroundTasks`、线程池、协程外层保持 trace，使用 `contextvars.ContextVar`：
  ```py
  from contextvars import ContextVar
  TRACE_ID: ContextVar[str|None] = ContextVar("TRACE_ID", default=None)
  # 中间件中 set；日志/任务中 get 即可
  ```
- 开放配置（可选）  
  允许通过环境变量控制：是否信任上游头、接收头名列表、是否降级到 `x-request-id`。

## 自测清单
- [ ] 无上游头：响应包含 `x-trace-id`，值为 UUID4。
- [ ] 有上游头：若开启复用策略，响应回传同一 ID。
- [ ] 异常请求：500 场景下仍能在响应或日志中看到同一 `trace_id`。
- [ ] 日志中 `trace_id` 与响应头一致（便于排障）。