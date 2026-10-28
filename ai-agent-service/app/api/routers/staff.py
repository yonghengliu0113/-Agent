"""坐席侧路由：工单上下文、回复草稿与发送、在线心跳、人工接管会话。"""
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse

from app import deps
from app.api import helpers
from app.core import config
from services.resilient_client import ResilienceError

router = APIRouter()


@router.get("/api/staff/handoff/sessions/{session_id}/attachment/{message_id}")
def download_staff_handoff_attachment(session_id: str, message_id: int, authorization: str | None = Header(default=None)):
    """坐席下载人工会话中的客户附件；待接入与本人已接入会话均可见。"""
    staff_user = helpers._require_staff_user(authorization)
    helpers._get_staff_visible_handoff_session(session_id, staff_user)
    message = helpers._find_attachment_message(session_id, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="附件不存在")
    attachment = (message.get("extra_data") or {}).get("attachment") or {}
    file_path = config.UPLOAD_ROOT / session_id / str(attachment.get("stored_name") or "")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    return FileResponse(str(file_path), filename=str(attachment.get("name") or file_path.name))


@router.get("/api/staff/tickets/{ticket_no}/context")
def get_staff_ticket_context(
    ticket_no: str,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """返回工单关联会话中的 AI 决策依据(风险原因、知识引用、工具结果、内部建议)，供坐席判断转人工原因。"""
    staff_user = helpers._require_staff_user(authorization)
    ticket = helpers._get_staff_ticket(ticket_no, authorization)
    handler = ticket.get("handlerId")
    # 待分派工单允许坐席在领取前查看 AI 依据；已领取工单仅限处理人本人查看。
    if handler is not None and str(handler) != str(staff_user.get("user_id")):
        raise HTTPException(status_code=403, detail="工单已被其他坐席领取，无权查看 AI 决策依据")
    try:
        context = helpers._find_ticket_chat_context(ticket_no, ticket)
    except HTTPException:
        context = None

    session_id = None
    handoff_reason = None
    ai_evidence: list[dict[str, Any]] = []
    if context:
        session = context["session"]
        session_id = session["session_id"]
        handoff_reason = session.get("handoff_reason")
        # 只提取 AI 消息中的决策依据；客户消息与坐席回复不属于“AI 依据”范畴。
        for message in deps.chat_messages.list_by_session(session_id):
            if message.get("sender_type") != "ai":
                continue
            extra = message.get("extra_data") or {}
            ticket_data = (extra.get("ticket_result") or {}).get("data") or {}
            ai_evidence.append({
                "message_id": message["id"],
                "created_at": message.get("created_at"),
                "customer_message": extra.get("customer_message") or message.get("content"),
                "decision_type": extra.get("decision_type"),
                "service_status": extra.get("service_status"),
                "risk_reasons": extra.get("risk_reasons") or [],
                "internal_suggestion": extra.get("internal_suggestion"),
                "citations": helpers._staff_citation_payloads(extra.get("citations") or []),
                "tool_results": helpers._staff_tool_result_payloads(extra.get("tool_results") or []),
                "ticket_result": {
                    "ticketNo": ticket_data.get("ticketNo"),
                    "status": ticket_data.get("status"),
                } if ticket_data else None,
            })
    return {
        "ticket_no": ticket_no,
        "ticket": ticket,
        "session_id": session_id,
        "handoff_reason": handoff_reason,
        "ai_evidence": ai_evidence,
    }


@router.get("/api/staff/tickets/{ticket_no}/messages")
def get_staff_ticket_messages(
    ticket_no: str,
    after_message_id: int = 0,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """返回工单关联会话的对话正文，供坐席在工作台内直接与客户沟通。

    改造前坐席只有 AI 决策依据（/context），没有对话正文，导致工单页无法和客户交流。
    权限与 /context 完全一致：待分派工单可读，已领取工单仅限处理人本人。
    内部扩展字段经 _staff_safe_handoff_messages 过滤，只保留客户可见正文与路由标记。
    """
    staff_user = helpers._require_staff_user(authorization)
    ticket = helpers._get_staff_ticket(ticket_no, authorization)
    handler = ticket.get("handlerId")
    if handler is not None and str(handler) != str(staff_user.get("user_id")):
        raise HTTPException(status_code=403, detail="工单已被其他坐席领取，无权查看客户对话")
    try:
        context = helpers._find_ticket_chat_context(ticket_no, ticket)
    except HTTPException:
        context = None
    if not context:
        # 工单尚未绑定会话时返回空对话，前端据此提示“该工单暂无客户对话”。
        return {"ticket_no": ticket_no, "session_id": None, "messages": []}
    session_id = context["session"]["session_id"]
    messages = [
        message
        for message in deps.chat_messages.list_by_session(session_id)
        if int(message.get("id") or 0) > after_message_id
    ]
    return {
        "ticket_no": ticket_no,
        "session_id": session_id,
        "messages": helpers._staff_safe_handoff_messages(messages),
    }


@router.post("/api/staff/tickets/{ticket_no}/reply/draft")
def draft_staff_ticket_reply(
    ticket_no: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict:
    """根据坐席填写的处理结果生成客户安全话术草稿，但不自动发送给客户。"""
    staff_user = helpers._require_staff_user(authorization)
    ticket = helpers._get_staff_ticket(ticket_no, authorization)
    # 草稿同样属于客户可见沟通，必须由当前工单处理人操作，不能只依赖“工单可见”。
    helpers._require_staff_ticket_owner(ticket, staff_user)
    context = helpers._find_ticket_chat_context(ticket_no, ticket)
    close_reason = str(payload.get("close_reason") or payload.get("processing_result") or "").strip()
    # 仅传入关联会话中客户可见的最近消息；草稿服务会继续脱敏并过滤内部字段。
    messages = deps.chat_messages.list_by_session(context["session"]["session_id"])
    draft_result = deps.staff_reply_draft_service.generate_with_metadata(
        ticket=ticket,
        processing_result=close_reason,
        messages=messages,
    )
    return {
        "ticket_no": ticket_no,
        "session_id": context["session"]["session_id"],
        "draft_message": draft_result.draft_message,
        # 仅向坐席展示生成来源，方便判断是否需要重点润色；不向客户侧透出。
        "generation_mode": draft_result.generation_mode,
        # 仅向已鉴权座席说明安全降级类别，便于重新生成或人工编辑；不包含供应商原始异常。
        "fallback_reason": draft_result.fallback_reason,
    }


@router.post("/api/staff/tickets/{ticket_no}/reply/send")
def send_staff_ticket_reply(
    ticket_no: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict:
    """保存坐席确认后的客户可见回复，客户侧会话历史刷新后即可看到。"""
    staff_user = helpers._require_staff_user(authorization)
    ticket = helpers._get_staff_ticket(ticket_no, authorization)
    # 发送客户消息前再次校验归属，避免未领取或他人名下工单被越权回复。
    helpers._require_staff_ticket_owner(ticket, staff_user)
    context = helpers._find_ticket_chat_context(ticket_no, ticket)
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="发送内容不能为空")

    session_id = context["session"]["session_id"]
    saved_message = deps.chat_messages.save(
        session_no=session_id,
        sender_type="staff",
        sender_id=str(staff_user.get("user_id")),
        content=message,
        extra_data={
            "ticket_no": ticket_no,
            # 通道路由是后端持久化契约，前端不得依据 sender_type 猜测消息应显示在哪个页签。
            "route_target": "human",
            "customer_visible": True,
            "message_source": "staff_confirmed_reply",
            "staff_user": {
                "user_id": staff_user.get("user_id"),
                "display_name": staff_user.get("display_name"),
            },
        },
    )
    # 坐席确认发送后，会话状态进入人工已回复，客户侧列表能看到进度变化。
    deps.chat_sessions.update_status(session_id, "STAFF_REPLIED")
    return {"status": "success", "session_id": session_id, "message": saved_message}


@router.post("/api/staff/presence/heartbeat")
def heartbeat_staff_presence(authorization: str | None = Header(default=None)) -> dict:
    """接收坐席工作台心跳，真实在线状态仅由短 TTL 保存。"""
    staff_user = helpers._require_staff_user(authorization)
    online = deps.staff_presence.heartbeat(str(staff_user.get("user_id")))
    return {"online": online, "ttl_seconds": deps.staff_presence.ttl_seconds}


@router.delete("/api/staff/presence")
def remove_staff_presence(authorization: str | None = Header(default=None)) -> dict:
    """坐席主动离开工作台时立即清理在线标记。"""
    staff_user = helpers._require_staff_user(authorization)
    deps.staff_presence.remove(str(staff_user.get("user_id")))
    return {"status": "success"}


@router.get("/api/staff/handoff/sessions")
def list_staff_handoff_sessions(
    limit: int = 50,
    authorization: str | None = Header(default=None),
) -> list[dict]:
    """查询人工接管会话队列，包含待接入会话和当前坐席已接入会话。"""
    staff_user = helpers._require_staff_user(authorization)
    sessions = deps.chat_sessions.list_handoff_sessions(str(staff_user.get("user_id")), limit)
    return [helpers._handoff_session_payload(session) for session in sessions]


@router.get("/api/staff/handoff/sessions/{session_id}")
def get_staff_handoff_session(
    session_id: str,
    after_message_id: int = 0,
    authorization: str | None = Header(default=None),
) -> dict:
    """坐席查看人工会话详情和完整消息历史。"""
    staff_user = helpers._require_staff_user(authorization)
    session = helpers._get_staff_visible_handoff_session(session_id, staff_user)
    is_owner = (
        session.get("handoff_status") == "ACTIVE"
        and str(session.get("human_assigned_staff_id")) == str(staff_user.get("user_id"))
    )
    recent_limit = max(1, int(os.getenv("STAFF_HANDOFF_RECENT_MESSAGE_LIMIT", "12")))
    # 先多取少量原始记录再过滤内部事件，保证座席实际看到的是最近的客户可见对话窗口。
    recent_messages = helpers._staff_safe_handoff_messages(
        deps.chat_messages.list_recent_by_session(session_id, limit=recent_limit * 4)
    )[-recent_limit:]
    earliest_window_id = min((int(message["id"]) for message in recent_messages), default=0)
    if not is_owner:
        # 待领取会话只提供摘要，领取前不展示客户与 AI 的具体对话。
        messages: list[dict[str, Any]] = []
    elif after_message_id > 0 and earliest_window_id and after_message_id >= earliest_window_id:
        # 增量接口只允许轮询最近窗口之后的新消息，不能借 after_message_id 绕过历史展开审计。
        messages = helpers._staff_safe_handoff_messages(deps.chat_messages.list_by_session(session_id, after_message_id=max(0, after_message_id)))
    else:
        messages = recent_messages
    oldest_message_id = min((int(message["id"]) for message in messages), default=0)
    return {
        "session": helpers._handoff_session_payload(session),
        "messages": messages,
        "latest_message_id": max((int(message["id"]) for message in messages), default=after_message_id),
        "handoff_summary": helpers._staff_handoff_summary(session),
        "history_available": bool(is_owner and oldest_message_id and deps.chat_messages.has_message_before(session_id, oldest_message_id)),
        "history_access_allowed": is_owner,
    }


@router.get("/api/staff/handoff/sessions/{session_id}/history")
def get_staff_handoff_history(
    session_id: str,
    before_message_id: int,
    limit: int = 30,
    authorization: str | None = Header(default=None),
) -> dict:
    """按需展开更早历史；仅当前接入座席可访问且每次读取都会持久化审计。"""
    staff_user = helpers._require_staff_user(authorization)
    helpers._get_staff_owned_handoff_session(session_id, staff_user)
    messages = helpers._staff_safe_handoff_messages(
        deps.chat_messages.list_before_message_id(session_id, before_message_id, limit=min(max(limit, 1), 50))
    )
    deps.staff_handoff_audit.record_history_access(
        session_no=session_id,
        staff_id=str(staff_user.get("user_id")),
        before_message_id=before_message_id,
        returned_count=len(messages),
    )
    oldest_message_id = min((int(message["id"]) for message in messages), default=before_message_id)
    return {
        "messages": messages,
        "history_available": bool(oldest_message_id and deps.chat_messages.has_message_before(session_id, oldest_message_id)),
        "next_before_message_id": oldest_message_id or None,
    }


@router.post("/api/staff/handoff/sessions/{session_id}/accept")
def accept_staff_handoff_session(session_id: str, authorization: str | None = Header(default=None)) -> dict:
    """坐席接入待处理人工会话，接入后客户消息不再由 Agent 自动回复。"""
    staff_user = helpers._require_staff_user(authorization)
    if not deps.staff_presence.is_online(str(staff_user.get("user_id"))):
        raise HTTPException(status_code=409, detail="坐席工作台心跳已失效，请刷新页面后重试")
    accepted = deps.chat_sessions.accept_handoff(
        session_id,
        str(staff_user.get("user_id")),
        str(staff_user.get("display_name") or "客服坐席"),
    )
    if not accepted:
        raise HTTPException(status_code=409, detail="该会话已被其他坐席接入或不在待接入状态")
    deps.chat_messages.save(
        session_no=session_id,
        sender_type="system",
        sender_id="handoff",
        content=f"{staff_user.get('display_name') or '客服坐席'} 已接入人工服务。",
        extra_data={"route_target": "human", "message_source": "handoff_accepted", "customer_visible": True},
    )
    return {"status": "success", "session": helpers._handoff_session_payload(accepted)}


@router.post("/api/staff/handoff/sessions/{session_id}/reply")
def send_staff_handoff_reply(
    session_id: str,
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
) -> dict:
    """坐席在人工会话中直接回复客户，不依赖业务工单。"""
    staff_user = helpers._require_staff_user(authorization)
    session = helpers._get_staff_owned_handoff_session(session_id, staff_user)
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="发送内容不能为空")
    saved_message = deps.chat_messages.save(
        session_no=session["session_id"],
        sender_type="staff",
        sender_id=str(staff_user.get("user_id")),
        content=message,
        extra_data={
            "route_target": "human",
            "customer_visible": True,
            "message_source": "manual_handoff_reply",
            "staff_user": {
                "user_id": staff_user.get("user_id"),
                "display_name": staff_user.get("display_name"),
            },
        },
    )
    return {"status": "success", "session_id": session_id, "message": saved_message}


@router.post("/api/staff/handoff/sessions/{session_id}/close")
def close_staff_handoff_session(
    session_id: str,
    payload: dict[str, Any] | None = None,
    authorization: str | None = Header(default=None),
) -> dict:
    """坐席结束人工接管，可选择回到 AI 协助或直接关闭会话。"""
    staff_user = helpers._require_staff_user(authorization)
    closed = deps.chat_sessions.close_handoff(session_id, str(staff_user.get("user_id")), "CLOSED")
    if not closed:
        raise HTTPException(status_code=403, detail="只能结束自己已接入的人工会话")
    reason = str((payload or {}).get("message") or "").strip()
    content = reason or "人工服务已结束，后续可继续由智能助手协助。"
    deps.chat_messages.save(
        session_no=session_id,
        sender_type="system",
        sender_id="handoff",
        content=content,
        extra_data={"route_target": "human", "message_source": "handoff_closed", "customer_visible": True, "target_status": "AI_ONLY"},
    )
    return {"status": "success", "session": helpers._handoff_session_payload(closed)}


@router.post("/api/staff/handoff/sessions/{session_id}/ticket")
def create_staff_handoff_ticket(session_id: str, authorization: str | None = Header(default=None)) -> dict:
    """由当前接入坐席按需创建异步跟进工单，客户身份与会话号只从后端会话读取。"""
    staff_user = helpers._require_staff_user(authorization)
    session = helpers._get_staff_owned_handoff_session(session_id, staff_user)
    customer_messages = [
        message["content"]
        for message in deps.chat_messages.list_by_session(session_id)
        if message.get("sender_type") == "customer" and message.get("content")
    ]
    content = "\n".join(customer_messages[-5:])[-2000:] or "客户请求人工客服异步跟进"
    try:
        response = deps.business_client.request_sync(
            "POST",
            f"{config.BUSINESS_SERVICE_URL}/api/internal/tickets/handoff",
            headers={"X-Agent-Internal-Secret": config.AGENT_INTERNAL_SECRET},
            json={
                "customerId": session["customer_id"],
                "externalSessionNo": session_id,
                "title": session.get("title") or "人工客服异步跟进",
                "content": content,
                "priority": session.get("priority") or "medium",
            },
        )
        ticket = response.json()
        if ticket.get("ticketNo"):
            deps.chat_sessions.set_handoff_ticket(session_id, str(ticket["ticketNo"]))
    except (ResilienceError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="业务工单服务暂时不可用，请稍后重试") from exc
    return {"status": "success", "ticket": ticket}
