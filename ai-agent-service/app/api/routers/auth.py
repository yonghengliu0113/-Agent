"""登录态路由：对接 Java 业务系统完成登录与当前用户查询。"""
from typing import Any

from fastapi import APIRouter, HTTPException, Header

from app import deps
from app.api import helpers
from app.core import config
from services.resilient_client import ResilienceError

router = APIRouter()


@router.post("/api/auth/login")
def login(payload: dict[str, Any]) -> dict:
    """代理 Java 业务系统登录接口，让前端只需要访问 Agent 服务。"""
    try:
        response = deps.business_client.request_sync("POST", f"{config.BUSINESS_SERVICE_URL}/api/auth/login", json=payload)
        return response.json()
    except ResilienceError as exc:
        raise HTTPException(status_code=exc.status_code or 503, detail=exc.safe_message) from exc


@router.get("/api/auth/current-user")
def current_user(authorization: str | None = Header(default=None)) -> dict:
    """通过 Java 业务系统校验 Token 并返回当前登录用户。"""
    return helpers._current_login_user(authorization)
