"""跨路由共享的请求辅助函数：鉴权、字段裁剪、入队编排与指标采样。"""
from datetime import datetime, timedelta, timezone
from typing import Any
import asyncio
import os
import uuid

from fastapi import HTTPException, Request
from prometheus_client import REGISTRY

from app import deps
from app.core import config
from schemas.intent_schema import AgentExecutionJob, AgentReplyRequest
from services.observability import current_context
from services.resilient_client import ResilienceError
from services.runtime_protection import metrics


def _overload_response() -> dict[str, Any]:
    """在并发槽位耗尽时返回客户安全话术，不等待模型排队造成请求雪崩。"""
    metrics.mark_degraded()
    return {
        "answer": "当前咨询量较大，您的问题已进入人工客服处理队列，请稍后查看处理进度。",
        "customer_message": "当前咨询量较大，您的问题已进入人工客服处理队列，请稍后查看处理进度。",
        "decision_type": "human_takeover",
        "service_status": "排队等待人工处理",
        "auto_send": False,
        "need_human": True,
        "degraded": True,
        "retry_after": int(os.getenv("AGENT_OVERLOAD_RETRY_AFTER_SECONDS", "10")),
    }


def _worker_unavailable_response() -> dict[str, Any]:
    """后台 Worker 未就绪时返回明确终态，避免客户侧长时间停留在排队中。"""
    metrics.mark_degraded()
    return {
        "answer": "当前智能客服服务暂时不可用，请稍后重试，或转人工客服处理。",
        "customer_message": "当前智能客服服务暂时不可用，请稍后重试，或转人工客服处理。",
        "decision_type": "human_takeover",
        "service_status": "智能客服暂不可用",
        "auto_send": False,
        "need_human": True,
        "degraded": True,
        "retry_after": int(os.getenv("AGENT_WORKER_RETRY_AFTER_SECONDS", "10")),
        "error_code": "AGENT_WORKER_UNAVAILABLE",
    }


def _attachment_extra(filename: str, size: int, content_type: str | None, stored_name: str) -> dict[str, Any]:
    """构造客户与坐席均可展示的附件元数据，不暴露服务器绝对路径。"""
    return {
        "attachment": {
            "name": filename,
            "size": size,
            "content_type": content_type or "application/octet-stream",
            "stored_name": stored_name,
        }
    }


def _find_attachment_message(session_no: str, message_id: int) -> dict[str, Any] | None:
    """按消息主键定位会话内附件消息，避免通过文件名越权访问。"""
    for message in deps.chat_messages.list_by_session(session_no):
        if int(message.get("id") or 0) == message_id:
            extra = message.get("extra_data") or {}
            if extra.get("attachment"):
                return message
    return None


def _staff_citation_payloads(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """把知识引用整理为坐席可读依据：文档、片段、风险等级与业务范围，不包含内部检索细节。"""
    payloads: list[dict[str, Any]] = []
    for item in citations or []:
        payloads.append({
            "citation_id": item.get("citation_id"),
            "doc_name": item.get("doc_name"),
            "paragraph": item.get("paragraph"),
            "risk_level": item.get("risk_level"),
            "collection": item.get("collection"),
            "business_scope": item.get("business_scope"),
        })
    return payloads


def _staff_tool_result_payloads(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """整理工具调用结果供坐席查看；保留业务数据但限制单条长度，避免整段订单详情淹没面板。"""
    payloads: list[dict[str, Any]] = []
    for item in tool_results or []:
        data = item.get("data")
        payloads.append({
            "tool_name": item.get("tool_name"),
            "query_type": item.get("query_type"),
            "status": item.get("status"),
            "error": item.get("error"),
            "retryable": item.get("retryable"),
            "data": data if len(str(data)) <= 2000 else str(data)[:2000],
        })
    return payloads


async def _recover_stale_handoffs() -> None:
    """每十五秒回收失联超过宽限期的坐席会话，并写入客户可见提示。"""
    while True:
        await asyncio.sleep(15)
        for staff_id in deps.chat_sessions.list_active_handoff_staff_ids():
            if deps.staff_presence.is_within_grace(staff_id):
                continue
            for session in deps.chat_sessions.requeue_handoffs_for_staff(staff_id):
                deps.chat_messages.save(
                    session_no=session["session_id"],
                    sender_type="system",
                    sender_id="handoff",
                    content="当前人工客服已离线，您的会话已重新进入排队，我们会尽快安排其他客服接入。",
                    extra_data={"route_target": "human", "message_source": "handoff_requeued", "customer_visible": True},
                )


def _customer_session_payload(session: dict[str, Any]) -> dict[str, Any]:
    """仅返回客户页面需要的会话字段，剔除 AI 摘要与内部判断信息。"""
    allowed = {
        "id", "session_id", "customer_id", "status", "handoff_status", "title",
        "human_requested_at", "human_assigned_staff_name", "human_accepted_at",
        "human_closed_at", "created_at", "updated_at", "pinned_at", "ticket_no",
    }
    return {key: value for key, value in session.items() if key in allowed}


def _handoff_waiting_seconds(session: dict[str, Any]) -> int:
    """计算人工排队等待秒数；时间格式异常时安全返回零。"""
    value = session.get("human_requested_at")
    if not value:
        return 0
    try:
        requested_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        now = datetime.now(requested_at.tzinfo) if requested_at.tzinfo else datetime.utcnow()
        return max(0, int((now - requested_at).total_seconds()))
    except (TypeError, ValueError):
        return 0


def _handoff_session_payload(session: dict[str, Any]) -> dict[str, Any]:
    """整理人工会话返回字段，避免坐席端依赖数据库内部列名。"""
    latest_meta = deps.chat_messages.latest_message_meta(session["session_id"]) or {}
    return {
        "session_id": session["session_id"],
        "customer_id": session["customer_id"],
        "status": session["status"],
        "session_status": session["status"],
        "handoff_status": session.get("handoff_status") or "NONE",
        "title": session.get("title"),
        "intent": session.get("intent"),
        "emotion": session.get("emotion"),
        "priority": session.get("priority"),
        "ai_summary": session.get("ai_summary"),
        "handoff_reason": session.get("handoff_reason"),
        "human_requested_at": session.get("human_requested_at"),
        "human_assigned_staff_id": session.get("human_assigned_staff_id"),
        "human_assigned_staff_name": session.get("human_assigned_staff_name"),
        "human_accepted_at": session.get("human_accepted_at"),
        "human_closed_at": session.get("human_closed_at"),
        "updated_at": session.get("updated_at"),
        "waiting_seconds": _handoff_waiting_seconds(session),
        "linked_ticket_no": deps.chat_sessions.get_handoff_ticket(session["session_id"]),
        "latest_message_id": deps.chat_messages.latest_message_id(session["session_id"]),
        "latest_message_at": latest_meta.get("created_at"),
        "last_sender_type": latest_meta.get("sender_type"),
    }


def _staff_safe_handoff_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤人工会话消息的内部扩展字段，座席仅获取客户可见正文与必要路由标记。"""
    safe_messages: list[dict[str, Any]] = []
    for message in messages:
        extra = dict(message.get("extra_data") or {})
        # 非客户可见系统事件可能包含流程控制信息，不能作为人工对话历史返回。
        if message.get("sender_type") == "system" and not extra.get("customer_visible"):
            continue
        safe_messages.append(
            {
                **message,
                "extra_data": {
                    key: extra[key]
                    for key in ("route_target", "message_source", "customer_visible", "attachment")
                    if key in extra
                },
            }
        )
    return safe_messages


def _staff_handoff_summary(session: dict[str, Any]) -> dict[str, Any]:
    """构造座席交接摘要，优先提供处理所需事实而非暴露完整 AI 对话。"""
    return {
        "title": str(session.get("title") or "待处理人工会话")[:160],
        "intent": session.get("intent"),
        "priority": session.get("priority") or "medium",
        "handoff_reason": session.get("handoff_reason"),
        "ai_summary": str(session.get("ai_summary") or "暂无自动摘要，请通过最近对话了解当前诉求。")[:600],
        "linked_ticket_no": deps.chat_sessions.get_handoff_ticket(session["session_id"]),
    }


def _get_staff_visible_handoff_session(session_id: str, staff_user: dict[str, Any]) -> dict[str, Any]:
    """校验坐席只能查看待接入或自己已接入的人工会话。"""
    session = deps.chat_sessions.get_by_session_no(session_id)
    staff_id = str(staff_user.get("user_id"))
    if not session or session.get("deleted_at"):
        raise HTTPException(status_code=404, detail="人工会话不存在")
    if session.get("handoff_status") == "PENDING":
        return session
    if session.get("handoff_status") == "ACTIVE" and session.get("human_assigned_staff_id") == staff_id:
        return session
    raise HTTPException(status_code=403, detail="无权访问该人工会话")


def _get_staff_owned_handoff_session(session_id: str, staff_user: dict[str, Any]) -> dict[str, Any]:
    """校验人工回复必须由当前接入坐席发送。"""
    session = deps.chat_sessions.get_by_session_no(session_id)
    staff_id = str(staff_user.get("user_id"))
    if (
        not session
        or session.get("handoff_status") != "ACTIVE"
        or session.get("human_assigned_staff_id") != staff_id
        or session.get("deleted_at")
    ):
        raise HTTPException(status_code=403, detail="请先接入该人工会话")
    return session


def _current_login_user(authorization: str | None) -> dict:
    """优先使用短期身份缓存，未命中时仍交给 Java 业务系统做权威 Token 校验。"""
    if not authorization:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        def load_identity() -> dict[str, Any]:
            """缓存缺失时请求 Java；Authorization 仅用于本次下游校验，不写入 Redis。"""
            response = deps.business_client.request_sync(
                "GET",
                f"{config.BUSINESS_SERVICE_URL}/api/auth/current-user",
                headers={"Authorization": authorization},
            )
            return response.json()

        token = _bearer_token(authorization)
        if not token:
            # 非 Bearer 格式仍交给 Java 校验并保持既有 401 行为，不可共享空 Token 缓存键。
            return load_identity()
        return deps.identity_cache.get_or_load(token, load_identity)
    except ResilienceError as exc:
        raise HTTPException(status_code=exc.status_code or 503, detail=exc.safe_message) from exc
    except ValueError as exc:
        # 身份格式不完整时不信任缓存值，避免发生客户或角色越权。
        raise HTTPException(status_code=502, detail="身份服务返回异常") from exc


def _require_staff_user(authorization: str | None) -> dict:
    """校验当前用户是否为客服坐席，保护坐席回复草稿和发送接口。"""
    user = _current_login_user(authorization)
    if user.get("role") != "staff":
        raise HTTPException(status_code=403, detail="仅客服坐席可操作")
    return user


def _get_staff_ticket(ticket_no: str, authorization: str | None) -> dict:
    """代理读取坐席视角工单详情，用于生成客户回复草稿时带入最新状态。"""
    try:
        response = deps.business_client.request_sync(
            "GET",
            f"{config.BUSINESS_SERVICE_URL}/api/staff/tickets/{ticket_no}",
            headers={"Authorization": authorization},
        )
        return response.json()
    except ResilienceError as exc:
        raise HTTPException(status_code=exc.status_code or 503, detail=exc.safe_message) from exc


def _require_staff_ticket_owner(ticket: dict, staff_user: dict) -> None:
    """校验坐席是工单当前处理人，防止“可查看”权限被误用于客户沟通和处理动作。

    Java 工单详情允许坐席查看未分派工单以便领取；但草稿生成、客户回复等写操作
    必须由实际处理人完成。这里使用 Java 返回的 handlerId 作为唯一归属依据。
    """
    handler_id = ticket.get("handlerId")
    staff_id = staff_user.get("user_id")
    if handler_id is None:
        raise HTTPException(status_code=403, detail="请先领取工单后再生成或发送客户回复")
    if str(handler_id) != str(staff_id):
        raise HTTPException(status_code=403, detail="只能处理自己名下的工单")


def _find_ticket_chat_context(ticket_no: str, ticket: dict | None = None) -> dict:
    """优先按工单 externalSessionNo 定位会话，旧数据再按消息扩展字段兼容查找。"""
    external_session_no = (ticket or {}).get("externalSessionNo")
    if external_session_no:
        session = deps.chat_sessions.get_by_session_no(external_session_no)
        if session:
            _ensure_ticket_session_customer_match(ticket_no, ticket or {}, session)
            # 新工单已强关联 Python 会话编号，坐席回复无需再扫描历史消息扩展字段。
            return {
                "session": session,
                "message": None,
                "ticket_result": {"status": "success", "data": ticket or {}},
            }

    context = deps.chat_messages.find_ticket_context(ticket_no)
    if not context:
        raise HTTPException(status_code=404, detail="未找到该工单关联的客户会话")
    _ensure_ticket_session_customer_match(ticket_no, ticket or {}, context["session"])
    return context


def _ensure_ticket_session_customer_match(ticket_no: str, ticket: dict[str, Any], session: dict[str, Any]) -> None:
    """校验 Java 工单与 Python 会话属于同一客户，阻断错误关联和跨客户消息写入。"""
    ticket_customer_id = ticket.get("customerId", ticket.get("customer_id"))
    session_customer_id = session.get("customer_id")
    # 兼容旧工单缺少 customerId 的历史数据；新数据一旦携带归属就必须严格一致。
    if ticket_customer_id is None or session_customer_id is None:
        return
    try:
        matched = int(ticket_customer_id) == int(session_customer_id)
    except (TypeError, ValueError):
        matched = False
    if not matched:
        raise HTTPException(status_code=409, detail=f"工单 {ticket_no} 与关联会话的客户归属不一致")


def _bearer_token(authorization: str | None) -> str | None:
    """从 Authorization 请求头中提取 Bearer Token，供工具转发给 Java 业务接口。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip()


def _request_subject(request: Request, authorization: str | None) -> str:
    """生成限流主体；优先使用已认证 Token，匿名请求回退到来源 IP。"""
    token = _bearer_token(authorization)
    if token:
        return f"token:{token[:24]}"
    client = request.client.host if request.client else "unknown"
    return f"ip:{client}"


def _queue_owner(authorization: str | None) -> str:
    """保存不可逆的 Token 摘要作为短期队列结果归属校验，不在结果中暴露完整凭证。"""
    import hashlib

    token = _bearer_token(authorization) or "anonymous"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]


def _enqueue_execution_job(payload: AgentReplyRequest, authorization: str | None, idempotency_key: str | None, route_source: str) -> str:
    """统一创建安全队列任务，使同步接口和 SSE 复用同一幂等与状态协议。"""
    request_id = f"agent-job-{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    job = AgentExecutionJob(
        request_id=request_id,
        customer_id=int(payload.customer_id or 0),
        message=payload.message,
        session_id=payload.session_id,
        selected_order_no=payload.selected_order_no,
        selected_ticket_no=payload.selected_ticket_no,
        route_target=payload.route_target,
        idempotency_key=idempotency_key or f"{route_source}:{request_id}",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(seconds=int(os.getenv("AGENT_JOB_TTL_SECONDS", "600")))).isoformat(),
        route_source=route_source,
        risk_level="high" if payload.route_target in {"human", "both"} else "normal",
        trace_id=current_context()["trace_id"],
        execution_credential=_queue_execution_credential(int(payload.customer_id or 0), request_id),
        login_user_context=payload.login_user_context,
    )
    return deps.agent_execution_queue.enqueue(job, _queue_owner(authorization))


def _safe_login_user_context(current_user: dict[str, Any]) -> dict[str, Any]:
    """把 Java 登录态转换为可进入队列和 Agent 上下文的安全身份摘要。"""
    return {
        "display_name": str(current_user.get("display_name") or "").strip()[:40],
        "role": str(current_user.get("role") or "customer").strip()[:30],
        "verified": True,
        "source": "java_auth",
    }


def _queue_execution_credential(customer_id: int, request_id: str) -> str:
    """签发短期内部执行凭证；队列不保存客户 Authorization 原始 Token。"""
    from services.downstream_identity import issue_execution_credential

    return issue_execution_credential(customer_id, request_id)


def _system_metric_snapshot() -> dict[str, Any]:
    """聚合当前进程 Prometheus 指标，供内部监控页以 JSON 方式展示关键异常与缓存命中率。"""
    try:
        llm_errors = {
            outcome: int(_sum_metric("agent_downstream_requests_total", {"outcome": outcome}, downstream_contains="llm"))
            for outcome in ("timeout", "rate_limit_429", "circuit_open")
        }
        return {
            "llm": llm_errors,
            "cache": {
                "rag": _cache_metric("rag_cache_hit"),
                "order": _cache_metric("order_cache_hit"),
                "ticket": _cache_metric("ticket_cache_hit"),
                "identity": _cache_metric("identity_cache_hit"),
                "session": _cache_metric("session_cache_hit"),
            },
            # 兼容早期 RuntimeMetrics 的降级计数；新 Prometheus Counter 有 reason 标签。
            "degraded": {
                "total": int(metrics.degraded + _sum_metric("agent_degraded_total")),
                "by_reason": _labeled_counter("agent_degraded_total", "reason"),
            },
        }
    except Exception:
        return {
            "llm": {"timeout": None, "rate_limit_429": None, "circuit_open": None},
            "cache": {},
            "degraded": {"total": None, "by_reason": {}},
        }


def _metric_samples(metric_name: str) -> list[Any]:
    """从默认 Registry 读取指定样本；只读指标名与标签，不接触请求体或鉴权信息。"""
    samples: list[Any] = []
    for family in REGISTRY.collect():
        for sample in family.samples:
            if sample.name == metric_name:
                samples.append(sample)
    return samples


def _sum_metric(metric_name: str, labels: dict[str, str] | None = None, downstream_contains: str | None = None) -> float:
    """按标签聚合 Prometheus Counter/Gauge，用于把文本指标转换为页面需要的数字。"""
    total = 0.0
    labels = labels or {}
    for sample in _metric_samples(metric_name):
        sample_labels = sample.labels or {}
        if any(sample_labels.get(key) != value for key, value in labels.items()):
            continue
        if downstream_contains and downstream_contains not in sample_labels.get("downstream", "").lower():
            continue
        total += float(sample.value)
    return total


def _labeled_counter(metric_name: str, label_name: str) -> dict[str, int]:
    """按单个标签拆分 Counter，便于页面显示降级原因分布。"""
    values: dict[str, int] = {}
    for sample in _metric_samples(metric_name):
        label = (sample.labels or {}).get(label_name, "unknown")
        values[label] = values.get(label, 0) + int(sample.value)
    return values


def _cache_metric(cache_name: str) -> dict[str, Any]:
    """计算缓存命中率；没有 hit/miss 分母时返回 null，避免展示伪精确百分比。"""
    hit = int(_sum_metric("agent_cache_operations_total", {"cache": cache_name, "outcome": "hit"}))
    miss = int(_sum_metric("agent_cache_operations_total", {"cache": cache_name, "outcome": "miss"}))
    error = int(_sum_metric("agent_cache_operations_total", {"cache": cache_name, "outcome": "error"}))
    denominator = hit + miss
    return {
        "hit": hit,
        "miss": miss,
        "error": error,
        "hit_rate": round(hit / denominator, 4) if denominator else None,
    }
