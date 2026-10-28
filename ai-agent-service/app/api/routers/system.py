"""系统与可观测性路由：健康检查、Prometheus 指标、服务状态与内部监控快照。"""
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Header
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import deps
from app.api import helpers

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """提供服务存活检查，便于前端、网关或部署平台判断 Agent 服务是否可用。"""
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False)
def prometheus_metrics() -> PlainTextResponse:
    """暴露 Prometheus 抓取端点，避免监控采集依赖业务接口。"""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/agent/status")
def status() -> dict:
    """返回 Agent 和 LLM 配置状态，用于排查前端无输出问题。"""
    return {
        "status": "ok",
        "llm": deps.agent.llm_status(),
        "queue": {
            "enabled": deps.agent_execution_queue.enabled,
            "active_worker": deps.agent_execution_queue.has_active_worker() if deps.agent_execution_queue.enabled else False,
        },
    }


@router.get("/api/staff/system/monitor")
def staff_system_monitor(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """返回坐席端轻量系统监控快照；局部指标读取失败不能影响页面整体可用性。"""
    helpers._require_staff_user(authorization)
    queue_snapshot = deps.agent_execution_queue.snapshot()
    metric_snapshot = helpers._system_metric_snapshot()
    return {
        "agent_status": {
            "status": "ok",
            "llm": deps.agent.llm_status(),
        },
        "queue": {
            "available": queue_snapshot.get("available", False),
            "enabled": queue_snapshot.get("enabled", False),
            "stream_depth": queue_snapshot.get("stream_depth"),
            "pending": queue_snapshot.get("pending"),
            "running": queue_snapshot.get("running"),
            "retrying": queue_snapshot.get("retrying"),
            "error": queue_snapshot.get("error"),
        },
        "worker": {
            "active": queue_snapshot.get("active_worker", False),
        },
        "dlq": {
            "count": queue_snapshot.get("dead_letter"),
        },
        "llm": metric_snapshot["llm"],
        "cache": metric_snapshot["cache"],
        "degraded": metric_snapshot["degraded"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
