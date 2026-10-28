"""客户侧路由：工单、订单、物流、通知与跟进事项。"""
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from app import deps
from app.api import helpers
from app.core import config
from services.resilient_client import ResilienceError

router = APIRouter()


@router.get("/api/customer/tickets/{ticket_no}")
def get_customer_ticket(ticket_no: str, authorization: str | None = Header(default=None)) -> dict:
    """代理查询客户自己的工单详情，让客户侧页面能刷新 Java 业务系统中的最新状态。"""
    helpers._current_login_user(authorization)
    result = deps.ticket_tools.query_ticket_status(ticket_no, helpers._bearer_token(authorization))
    if result.get("status") == "success":
        return result["data"]
    if result.get("error") == "4xx":
        return {"ticketNo": ticket_no, "status": "状态暂不可同步", "source": "HISTORY_FALLBACK"}
    raise HTTPException(status_code=503, detail="业务工单服务暂时不可用")


@router.get("/api/customer/tickets/{ticket_no}/change-requests")
def get_customer_ticket_change_requests(ticket_no: str, authorization: str | None = Header(default=None)) -> list[dict]:
    """代理查询客户工单的履约变更申请进度，供工单详情页展示。"""
    helpers._current_login_user(authorization)
    try:
        response = deps.business_client.request_sync(
            "GET",
            f"{config.BUSINESS_SERVICE_URL}/api/tickets/{ticket_no}/change-requests",
            headers={"Authorization": authorization},
        )
        return response.json()
    except ResilienceError as exc:
        # 旧工单在 Java 侧无变更申请记录时返回空列表，不把历史数据缺失当故障弹窗。
        if exc.status_code == 404:
            return []
        raise HTTPException(status_code=exc.status_code or 503, detail=exc.safe_message) from exc


@router.get("/api/customer/tickets")
def list_customer_tickets(authorization: str | None = Header(default=None)) -> list[dict]:
    """代理查询当前客户自己的工单列表，供客户侧工单列表和进度面板使用。"""
    helpers._current_login_user(authorization)
    result = deps.ticket_tools.list_customer_tickets(helpers._bearer_token(authorization))
    if result.get("status") == "success":
        return result["data"]
    raise HTTPException(status_code=503, detail="业务工单列表服务暂时不可用")


@router.post("/api/customer/tickets/{ticket_no}/urge")
def urge_customer_ticket(
    ticket_no: str,
    payload: dict[str, Any] | None = None,
    authorization: str | None = Header(default=None),
) -> dict:
    """代理客户催办自己的工单，催办由 Java 按 Token 校验归属并落库。"""
    helpers._current_login_user(authorization)
    key = str((payload or {}).get("idempotency_key") or uuid.uuid4())
    result = deps.ticket_tools.urge_ticket(ticket_no, str((payload or {}).get("reason") or "客户催办处理进度"), helpers._bearer_token(authorization), key)
    if result.get("status") == "success":
        return result["data"]
    raise HTTPException(status_code=503, detail="业务工单催办服务暂时不可用")


@router.get("/api/customer/orders")
def list_customer_orders(authorization: str | None = Header(default=None)) -> list[dict]:
    """代理查询当前客户订单列表，供客户侧选择订单后发起咨询。"""
    current_user_data = helpers._current_login_user(authorization)
    result = deps.order_tools.query_customer_orders(current_user_data["customer_id"], helpers._bearer_token(authorization))
    if result.get("status") in {"success", "empty"}:
        return result.get("data", [])
    raise HTTPException(status_code=503, detail="业务订单服务暂时不可用")


@router.get("/api/customer/orders/{order_no}")
def get_customer_order_detail(order_no: str, authorization: str | None = Header(default=None)) -> dict:
    """代理当前客户订单详情，避免浏览器绕过 Agent 服务直接访问核心业务系统。"""
    helpers._current_login_user(authorization)
    result = deps.order_tools.query_order_detail(order_no, helpers._bearer_token(authorization))
    if result.get("status") == "success":
        return result["data"]
    if result.get("status") == "empty":
        raise HTTPException(status_code=404, detail="订单不存在或无权查看")
    raise HTTPException(status_code=503, detail="业务订单服务暂时不可用")


@router.get("/api/customer/orders/{order_no}/logistics")
def get_customer_order_logistics(order_no: str, authorization: str | None = Header(default=None)) -> dict:
    """代理当前客户订单的物流轨迹，订单归属由 Java 服务二次校验。"""
    helpers._current_login_user(authorization)
    result = deps.order_tools.query_order_logistics(order_no, helpers._bearer_token(authorization))
    if result.get("status") == "success":
        return result["data"]
    if result.get("status") == "empty":
        raise HTTPException(status_code=404, detail="物流信息暂不可用")
    raise HTTPException(status_code=503, detail="物流服务暂时不可用")


@router.get("/api/customer/notifications")
def list_customer_notifications(
    limit: int = 50,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """查询当前客户自己的站内通知，不返回内部错误和工具原始结果。"""
    current_user = helpers._current_login_user(authorization)
    rows = deps.followup_notifications.list_notifications(int(current_user["customer_id"]), min(max(limit, 1), 100))
    return [
        {
            "notification_id": row.get("notification_id"),
            "session_id": row.get("session_no"),
            "followup_id": row.get("followup_id"),
            "type": row.get("notification_type"),
            "title": row.get("title"),
            "content": row.get("content"),
            "is_read": bool(row.get("is_read")),
            "created_at": row.get("created_at"),
            "read_at": row.get("read_at"),
        }
        for row in rows
    ]


@router.get("/api/customer/notifications/unread-count")
def customer_notification_unread_count(authorization: str | None = Header(default=None)) -> dict[str, int]:
    """返回当前客户未读通知数量，供前端角标轻量轮询。"""
    current_user = helpers._current_login_user(authorization)
    return {"count": deps.followup_notifications.unread_count(int(current_user["customer_id"]))}


@router.post("/api/customer/notifications/{notification_id}/read")
def mark_customer_notification_read(
    notification_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """仅允许通知所属客户标记已读。"""
    current_user = helpers._current_login_user(authorization)
    if not deps.followup_notifications.mark_read(notification_id, int(current_user["customer_id"])):
        raise HTTPException(status_code=404, detail="通知不存在")
    return {"notification_id": notification_id, "is_read": True}


@router.get("/api/customer/follow-ups")
def list_customer_followups(
    limit: int = 50,
    authorization: str | None = Header(default=None),
) -> list[dict[str, Any]]:
    """查询当前客户的复核任务，只展示调度状态与安全结果摘要。"""
    current_user = helpers._current_login_user(authorization)
    rows = deps.followup_notifications.list_followups(int(current_user["customer_id"]), min(max(limit, 1), 100))
    return [
        {
            "followup_id": row.get("followup_id"),
            "session_id": row.get("session_no"),
            "task_type": row.get("task_type"),
            "order_no": row.get("order_no"),
            "scheduled_at": row.get("scheduled_at"),
            "status": row.get("status"),
            "result": row.get("result_summary"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }
        for row in rows
    ]


@router.post("/api/customer/follow-ups/{followup_id}/cancel")
def cancel_customer_followup(
    followup_id: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """取消尚未执行的本人复核任务；运行中或已完成任务不能伪装取消成功。"""
    current_user = helpers._current_login_user(authorization)
    if not deps.followup_notifications.cancel_followup(followup_id, int(current_user["customer_id"])):
        raise HTTPException(status_code=409, detail="任务不存在或当前状态不可取消")
    return {"followup_id": followup_id, "status": "CANCELLED"}
