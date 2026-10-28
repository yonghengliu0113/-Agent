"""Agent 对话路由：同步回复、SSE 流式回复、队列结果查询与工具调用。"""
import os
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app import deps
from app.api import helpers
from repositories.chat_repository import customer_reference_payloads
from schemas.intent_schema import AgentReplyRequest, AnalyzeRequest, ToolCallRequest
from services.agent_execution_service import AgentExecutionAccessDenied
from services.runtime_protection import admission_controller, metrics

router = APIRouter()


@router.post("/api/agent/analyze")
def analyze(payload: AnalyzeRequest) -> dict:
    """对用户输入做结构化意图识别，供客服工作台展示 AI 分析结果。"""
    return deps.agent.analyze(payload.message).model_dump()


@router.post("/api/agent/reply", response_model=None)
def reply(payload: AgentReplyRequest, request: Request, authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict | JSONResponse:
    """同步兼容入口只创建/复用可靠任务并短等待，绝不在 API 进程直接执行 Agent。"""
    current_user = helpers._current_login_user(authorization)
    if not deps.agent_execution_queue.enabled:
        return JSONResponse(status_code=503, content=helpers._overload_response() | {"status": "degraded", "queued": False, "error_code": "QUEUE_UNAVAILABLE"})
    if not deps.agent_execution_queue.has_active_worker():
        return JSONResponse(status_code=503, content=helpers._worker_unavailable_response() | {"status": "degraded", "queued": False})
    execution_payload = payload.model_copy(update={"customer_id": current_user["customer_id"], "auth_token": helpers._bearer_token(authorization), "login_user_context": helpers._safe_login_user_context(current_user)})
    request_id = helpers._enqueue_execution_job(execution_payload, authorization, idempotency_key, "sync")
    deadline = time.monotonic() + float(os.getenv("AGENT_SYNC_WAIT_SECONDS", "3"))
    while time.monotonic() < deadline:
        state = deps.agent_execution_queue.get(request_id) or {}
        if state.get("status") == "SUCCESS":
            result = dict(state.get("result") or {})
            result.setdefault("request_id", request_id)
            result.setdefault("execution_status", "success")
            return result
        if state.get("status") in {"DEGRADED", "FAILED", "DEAD_LETTER"}:
            return JSONResponse(status_code=202, content=helpers._overload_response() | {"request_id": request_id, "status": "degraded", "queued": False, "error_code": state.get("error_code", "AGENT_UPSTREAM_UNAVAILABLE")})
        time.sleep(0.05)
    return JSONResponse(status_code=202, content={"request_id": request_id, "status": "queued", "queued": True, "degraded": False, "retry_after": int(os.getenv("AGENT_QUEUE_RETRY_AFTER_SECONDS", "3")), "customer_message": "您的问题正在为您处理，请稍后查询处理进度。", "service_status": "排队处理中"})


@router.post("/api/agent/handoff/messages")
def send_handoff_message(payload: AgentReplyRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """保存客户补充给人工客服的消息，不进入 Agent 队列、LLM 或 SSE 结果轮询。

    这条路径只负责鉴权、会话归属校验和人工消息持久化，不会绕过队列执行
    Agent。人工消息不再拥有 request_id，因此也不会读取到其他异步请求的结果。
    """
    current_user = helpers._current_login_user(authorization)
    execution_payload = payload.model_copy(
        update={
            "customer_id": current_user["customer_id"],
            "auth_token": helpers._bearer_token(authorization),
            "login_user_context": helpers._safe_login_user_context(current_user),
            "route_target": "human",
        }
    )
    try:
        # 人工通道使用专用持久化入口，避免未来 execute() 新增节点时误进入 AI 链路。
        return deps.agent_execution_service.save_handoff_message(execution_payload)
    except AgentExecutionAccessDenied as exc:
        # 不能通过人工通道跨会话写入客户消息。
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/agent/reply/stream/legacy", include_in_schema=False)
async def reply_stream(payload: AgentReplyRequest, request: Request, authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> StreamingResponse:
    """SSE 回复接口：立即建立连接，在线 Agent 在受控执行槽位中运行。"""
    import asyncio
    import json

    subject = helpers._request_subject(request, authorization)
    # 在进入队列前固定可信身份，Worker 无需也不应依赖 FastAPI 的鉴权函数。
    current_user_data = helpers._current_login_user(authorization)
    execution_payload = payload.model_copy(
        update={
            "customer_id": current_user_data["customer_id"],
            "auth_token": helpers._bearer_token(authorization),
            "login_user_context": helpers._safe_login_user_context(current_user_data),
        }
    )

    async def event_stream():
        """分阶段推送状态；当前模型不支持 token stream 时仍可避免 HTTP 长时间无响应。"""
        yield "event: accepted\ndata: {\"status\": \"accepted\"}\n\n"
        if deps.agent_execution_queue.enabled:
            # 生产模式由独立 Agent Worker 执行模型和工具调用，API Pod 只保持 SSE 连接。
            request_id = helpers._enqueue_execution_job(execution_payload, authorization, idempotency_key, "sse")
            yield f"event: queued\ndata: {json.dumps({'request_id': request_id}, ensure_ascii=False)}\n\n"
            deadline = time.monotonic() + float(os.getenv("AGENT_QUEUE_MAX_WAIT_SECONDS", "30"))
            while time.monotonic() < deadline:
                state = deps.agent_execution_queue.get(request_id) or {}
                if state.get("status") == "SUCCESS":
                    yield f"event: completed\ndata: {json.dumps(state['result'], ensure_ascii=False)}\n\n"
                    return
                if state.get("status") in {"DEGRADED", "FAILED", "DEAD_LETTER"}:
                    yield f"event: degraded\ndata: {json.dumps(helpers._overload_response() | {'request_id': request_id}, ensure_ascii=False)}\n\n"
                    return
                await asyncio.sleep(0.25)
            yield f"event: degraded\ndata: {json.dumps(helpers._overload_response() | {'request_id': request_id}, ensure_ascii=False)}\n\n"
            return
        if not admission_controller.try_acquire(subject):
            yield f"event: degraded\ndata: {json.dumps(helpers._overload_response(), ensure_ascii=False)}\n\n"
            return
        try:
            yield "event: generating\ndata: {\"status\": \"generating\"}\n\n"
            result = await asyncio.to_thread(deps.agent_execution_service.execute, execution_payload)
            yield f"event: completed\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
        except Exception:
            # 外部模型或业务工具异常不向客户暴露内部堆栈。
            metrics.mark_degraded()
            payload_data = helpers._overload_response() | {"error_code": "AGENT_UPSTREAM_UNAVAILABLE"}
            yield f"event: degraded\ndata: {json.dumps(payload_data, ensure_ascii=False)}\n\n"
        finally:
            admission_controller.release(subject)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/agent/reply/stream")
async def reply_stream_v2(payload: AgentReplyRequest, request: Request, authorization: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> StreamingResponse:
    """建立可重放的 SSE 订阅；API 只转发事件，不在本进程执行模型。"""
    import asyncio

    current_user = helpers._current_login_user(authorization)
    if not deps.agent_execution_queue.enabled:
        async def unavailable():
            event = deps.stream_event_service.publish("unavailable", "degraded", helpers._overload_response())
            yield deps.stream_event_service.to_sse(event)
        return StreamingResponse(unavailable(), media_type="text/event-stream")
    if not deps.agent_execution_queue.has_active_worker():
        async def worker_unavailable():
            event = deps.stream_event_service.publish("unavailable", "degraded", helpers._worker_unavailable_response())
            yield deps.stream_event_service.to_sse(event)
        return StreamingResponse(worker_unavailable(), media_type="text/event-stream")

    execution_payload = payload.model_copy(update={"customer_id": current_user["customer_id"], "auth_token": helpers._bearer_token(authorization), "login_user_context": helpers._safe_login_user_context(current_user)})
    request_id = helpers._enqueue_execution_job(execution_payload, authorization, idempotency_key, "sse")
    last_event_id = request.headers.get("Last-Event-ID")

    async def event_stream():
        """先补发 Last-Event-ID 之后的事件，再持续读取 Worker 产生的 token。"""
        if not last_event_id:
            accepted = deps.stream_event_service.publish(request_id, "accepted", {"status": "accepted"})
            queued = deps.stream_event_service.publish(request_id, "queued", {"status": "queued"})
            yield deps.stream_event_service.to_sse(accepted)
            yield deps.stream_event_service.to_sse(queued)
            cursor = queued["event_id"]
        else:
            cursor = last_event_id
        deadline = time.monotonic() + float(os.getenv("AGENT_QUEUE_MAX_WAIT_SECONDS", "30"))
        next_keepalive = time.monotonic() + float(os.getenv("AGENT_SSE_KEEPALIVE_SECONDS", "5"))
        while time.monotonic() < deadline:
            for event in deps.stream_event_service.replay(request_id, cursor):
                cursor = event["event_id"]
                yield deps.stream_event_service.to_sse(event)
                if event["event_type"] in {"completed", "degraded", "cancelled", "error"}:
                    return
            state = deps.agent_execution_queue.get(request_id) or {}
            if state.get("status") in {"SUCCESS", "DEGRADED", "FAILED", "DEAD_LETTER", "CANCELLED"}:
                result = state.get("result") or {}
                event_type = "completed" if state.get("status") == "SUCCESS" else ("cancelled" if state.get("status") == "CANCELLED" else "degraded")
                event = deps.stream_event_service.publish(request_id, event_type, {
                    "answer": result.get("customer_message") or result.get("answer", ""),
                    "status": state.get("status"),
                    "citations": customer_reference_payloads(result.get("citations") or []),
                })
                yield deps.stream_event_service.to_sse(event)
                return
            # 定期发送 SSE 注释帧，避免浏览器、开发代理或网关把无 token 的检索阶段判为闲置连接。
            if time.monotonic() >= next_keepalive:
                yield ": keepalive\n\n"
                next_keepalive = time.monotonic() + float(os.getenv("AGENT_SSE_KEEPALIVE_SECONDS", "5"))
            await asyncio.sleep(0.15)
        # 单次订阅到期只发布非终态 queued；客户端携带相同幂等键和 Last-Event-ID 自动续传。
        waiting = deps.stream_event_service.publish(request_id, "queued", {
            "status": (deps.agent_execution_queue.get(request_id) or {}).get("status", "PENDING"),
            "retry_after": int(os.getenv("AGENT_QUEUE_RETRY_AFTER_SECONDS", "3")),
            "customer_message": "请求仍在后台处理中，正在继续等待结果。",
        })
        yield deps.stream_event_service.to_sse(waiting)

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/agent/replies/{request_id}")
def get_queued_reply(request_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """查询 SSE 断线后的排队结果；仅暴露短 TTL 内的客户可见响应。"""
    result = deps.agent_execution_queue.get(request_id)
    if not result:
        raise HTTPException(status_code=404, detail="请求不存在或已过期")
    if result.get("owner") != helpers._queue_owner(authorization):
        raise HTTPException(status_code=403, detail="无权读取该请求结果")
    return result


@router.post("/api/agent/replies/{request_id}/cancel")
def cancel_queued_reply(request_id: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """停止当前 request_id 的生成；不影响同一会话中的其他请求或已提交工单。"""
    cancelled = deps.agent_execution_queue.cancel(request_id, helpers._queue_owner(authorization))
    if not cancelled:
        # 不区分不存在与非归属任务，避免通过接口枚举其他客户请求。
        raise HTTPException(status_code=404, detail="请求不存在或无权取消")
    status = str(cancelled.get("status") or "CANCEL_REQUESTED")
    result = cancelled.get("result") or {}
    deps.stream_event_service.publish(request_id, "cancelled" if status == "CANCELLED" else "cancelling", {
        "answer": result.get("partial_answer") or result.get("customer_message") or "",
        "partial": True,
        "ticket_no": result.get("ticket_no"),
        "service_status": result.get("service_status") or ("已停止处理" if status == "CANCELLED" else "正在停止生成"),
    })
    return {
        "request_id": request_id,
        "status": status,
        "partial_answer": result.get("partial_answer") or result.get("customer_message") or "",
        "ticket_no": result.get("ticket_no"),
        "service_status": result.get("service_status") or ("已停止处理" if status == "CANCELLED" else "正在停止生成"),
    }


@router.post("/api/agent/tool/call")
def tool_call(payload: ToolCallRequest, authorization: str | None = Header(default=None)) -> dict:
    """提供受控工具调用入口，避免 Agent 绕过白名单访问业务系统。"""
    # 工具名称采用白名单判断，防止外部请求调用未授权工具。
    if payload.tool_name == "query_order":
        helpers._current_login_user(authorization)
        return deps.order_tools.query_order(payload.arguments.get("order_no", ""), helpers._bearer_token(authorization))
    if payload.tool_name == "query_customer_orders":
        current_user_data = helpers._current_login_user(authorization)
        return deps.order_tools.query_customer_orders(current_user_data["customer_id"], helpers._bearer_token(authorization))
    if payload.tool_name == "query_order_logistics":
        helpers._current_login_user(authorization)
        return deps.order_tools.query_order_logistics(payload.arguments.get("order_no", ""), helpers._bearer_token(authorization))
    if payload.tool_name == "create_ticket":
        current_user_data = helpers._current_login_user(authorization)
        arguments = dict(payload.arguments)
        # 工具入口也必须以 Token 中客户 ID 为准，防止外部伪造 customerId 建单。
        arguments["customerId"] = current_user_data["customer_id"]
        return deps.ticket_tools.create_ticket(arguments, helpers._bearer_token(authorization))
    if payload.tool_name == "query_ticket_status":
        helpers._current_login_user(authorization)
        return deps.ticket_tools.query_ticket_status(payload.arguments.get("ticket_no", ""), helpers._bearer_token(authorization))
    if payload.tool_name == "urge_ticket":
        helpers._current_login_user(authorization)
        return deps.ticket_tools.urge_ticket(
            payload.arguments.get("ticket_no", ""),
            payload.arguments.get("reason"),
            helpers._bearer_token(authorization),
        )
    return {"status": "failed", "error": f"Unsupported tool: {payload.tool_name}"}


@router.get("/api/agent/logs")
def logs(limit: int = 100) -> list[dict]:
    """返回 Agent 工具调用日志，用于客服主管追溯 AI 决策依据。"""
    return deps.agent.list_call_logs(limit)
