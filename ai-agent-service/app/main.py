"""FastAPI 应用装配：中间件、生命周期事件与路由挂载。业务逻辑不写在这里。"""
from datetime import datetime, timezone
from pathlib import Path
import asyncio
import os
import time

from fastapi import FastAPI, Request

from app import deps
from app.api import helpers
from app.core import config
from services.observability import HTTP_LATENCY, HTTP_REQUESTS, set_request_context, tracer
from services.runtime_protection import metrics
from app.api.routers import system
from app.api.routers import auth
from app.api.routers import agent
from app.api.routers import chat
from app.api.routers import evaluation
from app.api.routers import customer
from app.api.routers import internal
from app.api.routers import staff

app = FastAPI(title="Enterprise Customer Agent Service", version="0.1.0")

handoff_recovery_task: asyncio.Task | None = None


@app.middleware("http")
async def observe_request(request: Request, call_next):
    """为每个请求注入 Trace ID 并记录延迟，方便跨 API、Worker 与下游服务排障。"""
    request_id, trace_id = set_request_context(request.headers.get("X-Request-ID"), request.headers.get("X-Trace-ID"))
    started = time.perf_counter()
    try:
        with tracer.start_as_current_span("agent.api.request") as span:
            span.set_attribute("http.request.method", request.method)
            span.set_attribute("url.path", request.url.path)
            span.set_attribute("agent.request_id", request_id)
            response = await call_next(request)
    except Exception:
        metrics.observe(request.url.path, 500, (time.perf_counter() - started) * 1000)
        HTTP_REQUESTS.labels(request.url.path, request.method, "500").inc()
        raise
    metrics.observe(request.url.path, response.status_code, (time.perf_counter() - started) * 1000)
    HTTP_REQUESTS.labels(request.url.path, request.method, str(response.status_code)).inc()
    HTTP_LATENCY.labels(request.url.path, request.method).observe(time.perf_counter() - started)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Trace-ID"] = trace_id
    return response


@app.on_event("startup")
def startup_checks() -> None:
    """服务启动时只检查外部依赖状态，禁止在线 API 进程承载评测 Worker。"""
    deps.agent.rag.check_startup()
    if config.startup_ready_file:
        # 就绪文件仅在显式配置时生成；用于 loopback 健康探测受限的本地 Windows 环境。
        ready_path = Path(config.startup_ready_file).resolve()
        ready_path.parent.mkdir(parents=True, exist_ok=True)
        ready_path.write_text(
            f"pid={os.getpid()}\nready_at={datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )


@app.on_event("startup")
async def start_handoff_recovery() -> None:
    """启动失联坐席会话回收任务，避免活跃人工会话永久卡死。"""
    global handoff_recovery_task
    handoff_recovery_task = asyncio.create_task(helpers._recover_stale_handoffs())


@app.on_event("shutdown")
async def stop_handoff_recovery() -> None:
    """服务停止时取消后台回收任务，避免测试或热重载残留协程。"""
    if handoff_recovery_task:
        handoff_recovery_task.cancel()
        try:
            await handoff_recovery_task
        except asyncio.CancelledError:
            pass
    if config.startup_ready_file:
        Path(config.startup_ready_file).resolve().unlink(missing_ok=True)


# 路由装配：按职责挂载，各路由路径互不重叠。
for _router in (
    system.router,
    auth.router,
    agent.router,
    chat.router,
    evaluation.router,
    customer.router,
    internal.router,
    staff.router,
):
    app.include_router(_router)
