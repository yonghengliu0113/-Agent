"""会话与附件路由：会话增删查、置顶、取消转人工，以及附件上传下载。"""
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import deps
from app.api import helpers
from app.core import config

router = APIRouter()


@router.get("/api/chat/session/list")
def list_chat_sessions(limit: int = 50, authorization: str | None = Header(default=None)) -> list[dict]:
    """查询最近客服会话列表，供前端左侧会话队列展示。"""
    current_user_data = helpers._current_login_user(authorization)
    return [helpers._customer_session_payload(session) for session in deps.chat_sessions.list_recent_for_customer(current_user_data["customer_id"], limit)]


@router.post("/api/chat/session")
def create_chat_session(payload: dict[str, Any] | None = None, authorization: str | None = Header(default=None)) -> dict:
    """显式创建一个新的客户会话，便于客户从空白上下文开始咨询。"""
    current_user_data = helpers._current_login_user(authorization)
    title = str((payload or {}).get("title") or "新会话").strip() or "新会话"
    return helpers._customer_session_payload(deps.chat_sessions.create(current_user_data["customer_id"], title))


@router.get("/api/chat/session/{session_id}")
def get_chat_session(
    session_id: str,
    after_message_id: int = 0,
    authorization: str | None = Header(default=None),
) -> dict:
    """查询会话详情和消息历史，供客服工作台展示完整上下文。"""
    current_user_data = helpers._current_login_user(authorization)
    session = deps.chat_sessions.get_by_session_no_for_customer(session_id, current_user_data["customer_id"])
    if not session:
        raise HTTPException(status_code=403, detail="无权访问该会话")
    messages = deps.chat_messages.list_by_session_for_customer(
        session_id,
        current_user_data["customer_id"],
        after_message_id=max(0, after_message_id),
    )
    return {
        "session": helpers._customer_session_payload(session),
        "messages": messages,
        "latest_message_id": max((int(message["id"]) for message in messages), default=after_message_id),
    }


@router.delete("/api/chat/session/{session_id}")
def delete_chat_session(session_id: str, authorization: str | None = Header(default=None)) -> dict:
    """软删除当前客户自己的会话，客户侧列表隐藏但保留工单审计上下文。"""
    current_user_data = helpers._current_login_user(authorization)
    session = deps.chat_sessions.get_by_session_no_for_customer(session_id, current_user_data["customer_id"])
    if session and session.get("handoff_status") in {"PENDING", "ACTIVE"}:
        raise HTTPException(status_code=409, detail="请先取消待接入请求；已接入会话需由坐席结束后才能删除")
    deleted = deps.chat_sessions.soft_delete_for_customer(session_id, current_user_data["customer_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return {"status": "success", "session_id": session_id}


@router.post("/api/chat/session/{session_id}/handoff/cancel")
def cancel_customer_handoff(session_id: str, authorization: str | None = Header(default=None)) -> dict:
    """允许客户取消尚未接入的人工排队请求，已接入会话只能由当前坐席结束。"""
    current_user_data = helpers._current_login_user(authorization)
    session = deps.chat_sessions.cancel_pending_handoff(session_id, current_user_data["customer_id"])
    if not session:
        raise HTTPException(status_code=409, detail="当前会话不在待接入状态，无法取消")
    deps.chat_messages.save(
        session_no=session_id,
        sender_type="system",
        sender_id="handoff",
        content="您已取消人工客服排队，可继续使用智能助手。",
        extra_data={"route_target": "human", "message_source": "handoff_cancelled", "customer_visible": True},
    )
    return {"status": "success", "session": helpers._customer_session_payload(session)}


@router.patch("/api/chat/session/{session_id}/pin")
def pin_chat_session(session_id: str, payload: dict[str, Any] | None = None,
                     authorization: str | None = Header(default=None)) -> dict:
    """置顶或取消置顶当前客户自己的会话，不允许通过会话编号操作其他客户数据。"""
    current_user_data = helpers._current_login_user(authorization)
    pinned = bool((payload or {}).get("pinned"))
    session = deps.chat_sessions.set_pinned_for_customer(session_id, current_user_data["customer_id"], pinned)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return helpers._customer_session_payload(session)


@router.post("/api/chat/session/{session_id}/attachment")
async def upload_session_attachment(
    session_id: str,
    authorization: str | None = Header(default=None),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """客户向自己的会话上传附件：文件落盘并生成客户可见附件消息。"""
    current_user = helpers._current_login_user(authorization)
    session = deps.chat_sessions.get_by_session_no_for_customer(session_id, int(current_user["customer_id"]))
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    raw = await file.read()
    if len(raw) > config.MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail=f"附件不能超过 {config.MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB")
    original_name = Path(file.filename or "attachment").name
    stored_name = f"{uuid.uuid4().hex[:8]}_{original_name}"
    store_dir = config.UPLOAD_ROOT / session_id
    store_dir.mkdir(parents=True, exist_ok=True)
    (store_dir / stored_name).write_bytes(raw)
    # 人工接管期间附件直达坐席通道，其余进入 AI 会话记录。
    route = "human" if session.get("handoff_status") in {"PENDING", "ACTIVE"} else "ai"
    saved = deps.chat_messages.save(
        session_no=session_id,
        sender_type="customer",
        sender_id=str(current_user["customer_id"]),
        content=f"[附件] {original_name}",
        message_type="attachment",
        extra_data={
            **helpers._attachment_extra(original_name, len(raw), file.content_type, stored_name),
            "route_target": route,
            "message_source": "customer_attachment",
            "customer_visible": True,
        },
    )
    return {"status": "success", "session_id": session_id, "message": saved}


@router.get("/api/chat/session/{session_id}/attachment/{message_id}")
def download_session_attachment(session_id: str, message_id: int, authorization: str | None = Header(default=None)):
    """下载当前客户自己会话中的附件；仅允许会话所有者访问。"""
    current_user = helpers._current_login_user(authorization)
    session = deps.chat_sessions.get_by_session_no_for_customer(session_id, int(current_user["customer_id"]))
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    message = helpers._find_attachment_message(session_id, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="附件不存在")
    attachment = (message.get("extra_data") or {}).get("attachment") or {}
    file_path = config.UPLOAD_ROOT / session_id / str(attachment.get("stored_name") or "")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="附件文件已丢失")
    return FileResponse(str(file_path), filename=str(attachment.get("name") or file_path.name))
