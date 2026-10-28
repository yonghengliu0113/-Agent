"""内部回调路由：Java 业务系统把工单状态同步回会话。"""
from typing import Any

from fastapi import APIRouter, HTTPException, Header

from app import deps
from app.api import helpers
from app.core import config

router = APIRouter()


@router.post("/api/internal/tickets/status-sync")
def sync_ticket_status_to_conversation(payload: dict[str, Any], internal_secret: str | None = Header(default=None, alias="X-Agent-Internal-Secret")) -> dict[str, Any]:
    """接收 Java 工单状态回调，并写入同一关联客户会话。"""
    if internal_secret != config.AGENT_INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="内部服务身份校验失败")
    ticket_no, session_id = str(payload.get("ticketNo") or "").strip(), str(payload.get("externalSessionNo") or "").strip()
    if not ticket_no or not session_id:
        raise HTTPException(status_code=400, detail="工单状态同步缺少必要关联字段")
    session = deps.chat_sessions.get_by_session_no(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="未找到工单关联会话")
    helpers._ensure_ticket_session_customer_match(ticket_no, payload, session)
    status = str(payload.get("status") or "PROCESSING").upper()
    # 同一状态回调允许安全重放，避免网络重试生成重复客户提示。
    for item in reversed(deps.chat_messages.list_by_session(session_id)):
        extra = item.get("extra_data") or {}
        if extra.get("message_source") == "ticket_status_sync" and extra.get("ticket_no") == ticket_no and extra.get("ticket_status") == status:
            return {"status": "duplicate", "session_id": session_id}
    label = {"PENDING_ASSIGN": "待分派", "PENDING_PROCESS": "待处理", "PROCESSING": "处理中", "REOPENED": "已重新打开", "CLOSED": "已处理完成"}.get(status, status)
    deps.chat_messages.save(session_id, "system", f"工单 {ticket_no} 状态已更新为“{label}”。", sender_id="ticket-status-sync", extra_data={"route_target": "human", "message_source": "ticket_status_sync", "customer_visible": True, "ticket_no": ticket_no, "ticket_status": status})
    deps.chat_sessions.update_status(session_id, "TICKET_STATUS_UPDATED")
    return {"status": "success", "session_id": session_id}
