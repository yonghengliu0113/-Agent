"""动作请求的槽位抽取与消息判定：从客户原话中识别动作类型、售后原因、取件时间窗、发票要素等。

这些函数都是纯函数（不修改 self、不发起 IO），从 action_request 中抽出，
让编排逻辑（enrich_action_analysis）与文本抽取逻辑可以分别演进。"""

import re
from datetime import datetime
from typing import Any

from agents.intent_normalizer import is_logistics_message as normalize_is_logistics_message
from schemas.intent_schema import ActionTurnExtraction, IntentResult

PENDING_DIRECT_CONTINUE_SECONDS = 5 * 60


PENDING_EXPIRE_SECONDS = 30 * 60


def _resolve_pending_reason(message: str, turn: ActionTurnExtraction) -> str | None:
    """在多槽位消息中保留纯原因片段，单独补原因时保留客户完整原话。"""
    extracted = turn.slots.get("after_sale_reason")
    has_other_slots = bool(
        {"return_method", "pickup_time_window"}.intersection(turn.slots)
    )
    if extracted and has_other_slots:
        return str(extracted)
    return _extract_pending_reason(message) or (str(extracted) if extracted else None)


def _should_use_context_order(message: str, context_order_no: str | None) -> bool:
    """判断本轮是否允许继承历史订单上下文，避免普通动作请求误绑定旧订单。"""
    if not context_order_no:
        return False
    return _contains_any(
        message,
        [
            "这单",
            "那单",
            "这个订单",
            "那个订单",
            "这笔订单",
            "那笔订单",
            "当前订单",
            "刚才那个",
            "刚刚那个",
            "上面那个",
            "继续",
        ],
    )


def _usable_pending(pending: dict[str, Any] | None) -> dict[str, Any] | None:
    """读取 30 分钟内仍可继续或需要确认的 pending 动作。"""
    if not pending or pending.get("completed") or pending.get("status") in {"cancelled", "completed"}:
        return None
    return None if _pending_time_state(pending) == "expired" else pending


def _pending_time_state(pending: dict[str, Any] | None) -> str:
    """按最后更新时间把动作划分为可直续、需确认和已过期三档。"""
    if not pending or pending.get("completed") or pending.get("status") in {"cancelled", "completed"}:
        return "none"
    now = datetime.utcnow()
    expires_at = pending.get("expires_at") or pending.get("expire_at")
    if expires_at:
        try:
            if datetime.fromisoformat(str(expires_at)) <= now:
                return "expired"
        except ValueError:
            pass
    updated_at = pending.get("updated_at") or pending.get("created_at")
    if not updated_at:
        # 兼容旧数据：没有时间字段的未完成动作按当前活跃流程处理。
        return "fresh"
    try:
        age_seconds = max(0.0, (now - datetime.fromisoformat(str(updated_at))).total_seconds())
    except ValueError:
        return "fresh"
    if age_seconds <= PENDING_DIRECT_CONTINUE_SECONDS:
        return "fresh"
    if age_seconds <= PENDING_EXPIRE_SECONDS:
        return "needs_confirmation"
    return "expired"


def _looks_like_action_request(text: str) -> bool:
    """区分“帮我做某事”和“怎么做/规则是什么”。"""
    if _contains_any(text, ["怎么", "如何", "规则", "政策", "流程", "多久", "能不能", "可以吗"]):
        return False
    return _contains_any(
        text,
        [
            "我要",
            "帮我",
            "申请",
            "提交",
            "开一开",
            "开发票",
            "开票",
            "开个人发票",
            "开企业发票",
            "取消",
            "处理一下",
            "给我",
            "想退",
            "想换",
            "要退",
            "要换",
        ],
    )


def _is_cancel_message(message: str) -> bool:
    """识别用户取消当前业务动作的表达。"""
    return _contains_any(message, ["不用", "不用了", "取消", "算了", "先不", "不退了", "不换了", "不修了"])


def _is_confirm_message(message: str) -> bool:
    """识别纯确认或“确认 + 补充槽位”的复合肯定表达。"""
    text = message.strip().lower()
    confirm_terms = {"是", "是的", "对", "对的", "确认", "没错", "就是", "就是这个", "yes", "y"}
    if text in confirm_terms:
        return True
    # 只接受“确认词 + 分隔符 + 后续内容”，避免把“确认不了”等否定表达误判成确认。
    return bool(re.match(r"^(?:是的|确认|没错|对的|对|就是这个|就是|yes|y)[\s，,。；;：:]+.+$", text))


def _extract_confirmed_reason(message: str) -> str | None:
    """从“确认，原因……”中提取售后原因，支持一次回复同时完成确认与补槽。"""
    if not _is_confirm_message(message):
        return None
    remainder = re.sub(
        r"^(?:是的|确认|没错|对的|对|就是这个|就是|yes|y)[\s，,。；;：:]*",
        "",
        message.strip(),
        count=1,
        flags=re.IGNORECASE,
    ).strip()
    if not remainder:
        return None

    reason_marker = re.match(r"^(?:退货原因|换货原因|原因|理由)(?:是|为|：|:)?[\s，,]*", remainder)
    if reason_marker:
        reason_text = remainder[reason_marker.end():].strip()
        return _extract_pending_reason(reason_text) if reason_text else None

    # 没有“原因”标记时只接收已知原因词，防止把“订单是 XXX”误存为退货原因。
    extracted = _extract_after_sale_reason(remainder)
    return remainder if extracted and len(remainder) <= 80 else extracted


def _is_reject_confirmation_message(message: str) -> bool:
    """识别用户否认候选订单的表达。"""
    text = message.strip().lower()
    return text in {"不是", "不对", "不是这个", "不是这单", "否", "no", "n"}


def _is_pending_order_confirmation(pending: dict[str, Any]) -> bool:
    """判断上一轮 pending 是否正在等待订单上下文确认。"""
    slots = pending.get("action_slots") or {}
    missing_slots = pending.get("missing_slots") or []
    return bool(slots.get("candidate_order_no") and "order_confirmation" in missing_slots)


def _is_pending_resume_confirmation(pending: dict[str, Any]) -> bool:
    """判断 pending 是否正在等待继续旧流程或重新发起动作的明确确认。"""
    missing_slots = set(pending.get("missing_slots") or [])
    return pending.get("status") == "awaiting_confirmation" and bool(
        missing_slots.intersection({"pending_confirmation", "action_confirmation"})
    )


def _has_explicit_action_phrase(message: str, selected_order_no: str | None = None) -> bool:
    """识别客户明确要求执行动作的表达，避免把原因陈述误当成执行授权。"""
    if _selected_order_short_action_type(message, selected_order_no):
        return True
    if not _looks_like_action_request(message):
        return False
    return _contains_any(
        message,
        [
            "我要退货", "想退货", "申请退货", "帮我退货", "办理退货",
            "我要退款", "想退款", "申请退款", "帮我退款",
            "我要换货", "想换货", "申请换货", "帮我换货",
            "我要维修", "申请维修", "帮我报修", "我要开票", "帮我开票",
        ],
    )


def _is_standalone_unwanted_message(message: str) -> bool:
    """识别只有“不想要/用不上”等原因、但没有明确动作授权的模糊表达。"""
    text = re.sub(r"[，。！？!?\s]", "", message)
    return text in {"我不想要了", "不想要了", "不想要", "用不上了", "我用不上了"}


def _is_pending_after_sale_reason(pending: dict[str, Any]) -> bool:
    """判断上一轮 pending 是否正在等待售后原因。"""
    action_type = pending.get("action_type")
    missing_slots = pending.get("missing_slots") or []
    return action_type in {"return_goods", "refund_request", "exchange_goods"} and bool(
        {"after_sale_reason", "return_reason"}.intersection(missing_slots)
    )


def _is_pending_return_fulfillment(pending: dict[str, Any]) -> bool:
    """判断退货流程是否正在等待退回方式或上门取件时间。"""
    return pending.get("action_type") == "return_goods" and bool(
        {"return_method", "pickup_time_window"}.intersection(pending.get("missing_slots") or [])
    )


def _is_short_pending_reply(message: str, analysis: IntentResult) -> bool:
    """识别槽位追问后的短上下文回复，避免“算了”等被误走越界兜底。"""
    text = message.strip()
    if analysis.user_goal != "out_of_scope":
        return False
    return 0 < len(text) <= 8


def _is_reset_pending_message(message: str) -> bool:
    """识别仅用于结束当前流程的重新开始或换题表达。"""
    return _contains_any(message, ["换个问题", "换一个问题", "重新开始", "换个话题", "先说别的"])


def _is_explicit_topic_switch(message: str, pending: dict[str, Any] | None) -> bool:
    """识别客户明确切换业务目标，显式新意图优先于旧 pending 槽位填充。"""
    if pending and _is_pending_return_fulfillment(pending) and _extract_return_fulfillment_slots(message, pending):
        # “不用上门、我自己寄回”是在回答退回方式，不能因为包含“不用”就误判为取消退货。
        return False
    if _is_cancel_message(message) or _is_reset_pending_message(message):
        return True
    action_type = str((pending or {}).get("action_type") or "")
    if _is_logistics_query_message(message) or _contains_any(message, ["查订单", "订单状态", "开票", "发票", "投诉", "举报", "维权"]):
        return True
    action_switch_terms = {
        "return_goods": ["换货", "维修", "报修"],
        "refund_request": ["退货", "换货", "维修", "报修"],
        "exchange_goods": ["退货", "退款", "维修", "报修"],
        "repair_request": ["退货", "退款", "换货"],
    }
    return _contains_any(message, action_switch_terms.get(action_type, []))


def _is_explicit_same_action_request(message: str, pending: dict[str, Any] | None) -> bool:
    """识别客户在旧流程过期后明确重新表达同一业务动作。"""
    action_type = str((pending or {}).get("action_type") or "")
    terms = {
        "return_goods": ["我要退货", "想退货", "申请退货", "帮我退货"],
        "refund_request": ["我要退款", "想退款", "申请退款", "帮我退款"],
        "exchange_goods": ["我要换货", "想换货", "申请换货", "帮我换货"],
        "repair_request": ["我要维修", "申请维修", "帮我报修"],
    }
    return _contains_any(message, terms.get(action_type, []))


def _extract_order_no(message: str) -> str | None:
    match = re.search(r"(?<![A-Za-z])(?:EC)?\d{10,18}", message, flags=re.IGNORECASE)
    return match.group(0) if match else None


def _extract_after_sale_reason(message: str) -> str | None:
    """抽取退换货原因。"""
    explicit = re.search(r"(?:因为|原因是|理由是|退货原因是|换货原因是)([^，,。；;！？!?]+)", message)
    if explicit:
        return explicit.group(1).strip(" ，。?.")
    reason_words = [
        "质量不好",
        "商品质量问题",
        "质量问题",
        "买错",
        "拍错",
        "拍错了",
        "不想要",
        "七天无理由",
        "配件缺失",
        "尺码不合适",
        "尺寸不合适",
        "颜色不喜欢",
        "与描述不符",
        "少件",
        "漏发",
        "错发",
        "破损",
        "有瑕疵",
        "不能用",
        "坏了",
    ]
    for word in reason_words:
        if word in message:
            return word
    # 使用通用语义形态覆盖“商品有问题、产品不能正常使用”等表达，避免为单句话打补丁。
    generic_patterns = [
        r"(?:商品|产品|货物|东西).{0,8}(?:有问题|有故障|有瑕疵|损坏|坏了|不能用|无法使用)",
        r"(?:不需要|用不上|不合适|不喜欢|不满意)(?:了)?",
        r"(?:收到|到货|拆开).{0,8}(?:破损|少件|漏发|错发|有问题)",
    ]
    for pattern in generic_patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(0).strip(" ，。?.")
    return None


def _selected_order_short_action_type(message: str, selected_order_no: str | None) -> str | None:
    """识别已选订单上的单词式售后动作，规则、条件和流程咨询不在此范围内。"""
    if not selected_order_no:
        return None
    text = re.sub(r"[，。！？!?.\s]", "", message).lower()
    action_map = {
        "退货": "return_goods",
        "退款": "refund_request",
        "换货": "exchange_goods",
        "维修": "repair_request",
        "报修": "repair_request",
    }
    return action_map.get(text)


def _extract_pending_reason(message: str) -> str | None:
    """在等待退货原因时优先解释安全短句，避免依赖本轮 LLM 新意图结果。"""
    extracted = _extract_after_sale_reason(message)
    if extracted:
        return message.strip() if len(message.strip()) <= 80 else extracted
    text = message.strip(" ，。?？.!！")
    if not 2 <= len(text) <= 80:
        return None
    if _is_explicit_topic_switch(text, None) or _is_confirm_message(text) or _is_reject_confirmation_message(text):
        return None
    if _contains_any(text, ["我要退货", "想退货", "申请退货", "帮我退货", "我要退款", "申请退款", "我要换货", "申请换货"]):
        return None
    if _contains_any(text, ["怎么", "如何", "为什么", "规则", "政策", "流程", "多久", "能不能", "可以吗", "我是谁", "你是谁"]):
        return None
    return text


def _extract_return_fulfillment_slots(
    message: str,
    pending: dict[str, Any] | None = None,
    *,
    allow_unbound_time: bool = False,
) -> dict[str, Any]:
    """抽取退回方式和取件时间偏好；时间仅表示客户偏好，不代表承运方已确认预约。"""
    text = message.strip(" ，。?？.!！")
    slots: dict[str, Any] = {}
    if _contains_any(text, ["不上门", "不需要上门", "不用上门", "自行寄回", "自己寄回", "我自己寄", "快递寄回"]):
        slots["return_method"] = "self_ship"
        slots["pickup_status"] = "NOT_REQUIRED"
        return slots
    if _contains_any(text, ["上门取件", "上门取", "安排取件", "需要取件", "来取"]):
        slots["return_method"] = "pickup"
        slots["pickup_status"] = "PREFERENCE_RECORDED"

    pending_slots = (pending or {}).get("action_slots") or {}
    expects_pickup_time = slots.get("return_method") == "pickup" or (
        pending_slots.get("return_method") == "pickup"
        and "pickup_time_window" in ((pending or {}).get("missing_slots") or [])
    )
    if expects_pickup_time or allow_unbound_time:
        time_window = _extract_pickup_time_window(text)
        if time_window:
            slots["pickup_time_window"] = time_window
            if slots.get("return_method") == "pickup" or pending_slots.get("return_method") == "pickup":
                slots.setdefault("pickup_status", "PREFERENCE_RECORDED")
    return slots


def _extract_pickup_time_window(message: str) -> str | None:
    """保守提取客户提供的取件时间段，避免把普通说明误存为预约时间。"""
    text = message.strip(" ，。?？.!！")
    if not text or len(text) > 80:
        return None
    time_terms = [
        "今天", "明天", "后天", "周一", "周二", "周三", "周四", "周五", "周六", "周日",
        "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
        "上午", "中午", "下午", "晚上", "工作日", "周末", "点", ":", "：",
    ]
    if not _contains_any(text, time_terms):
        return None
    # 优先抽取最小时间短语，避免“把上门取件改成明天下午三点”被完整保存为取件时间。
    precise_time = re.search(
        r"(?:(?:今天|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])"
        r"(?:上午|中午|下午|晚上)?[0-9零一二三四五六七八九十两]{1,3}点(?:[0-9零一二三四五六七八九十两]{1,3}分|半)?"
        r"|(?:今天|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])(?:上午|中午|下午|晚上)"
        r"|(?:今天|明天|后天|周[一二三四五六日天]|星期[一二三四五六日天])"
        r"|(?:上午|中午|下午|晚上)[0-9零一二三四五六七八九十两]{1,3}点(?:[0-9零一二三四五六七八九十两]{1,3}分|半)?"
        r"|[0-9零一二三四五六七八九十两]{1,3}点(?:[0-9零一二三四五六七八九十两]{1,3}分|半)?)",
        text,
    )
    if precise_time:
        return precise_time.group(0)
    # 优先定位包含时间的最小分句，避免把退货动作和原因一并保存到 pickup_time_window。
    clauses = [item.strip() for item in re.split(r"[，,。；;！？!?]", text) if item.strip()]
    time_clause = next((item for item in clauses if _contains_any(item, time_terms)), text)
    cleaned = re.sub(
        r"(?:我要退货|申请退货|帮我退货|商品有问题|商品质量问题|质量问题|"
        r"需要|请|可以|麻烦|帮我|安排|上门取件|上门取|取件|来取件|来取|时间|方便|的话|我想)",
        "",
        time_clause,
    ).strip(" ，。来")
    return cleaned or text


def _extract_fault_description(message: str) -> str | None:
    fault_words = ["连不上", "无法使用", "坏了", "故障", "报错", "不能开机", "没反应", "断网", "发热"]
    return message.strip() if _contains_any(message, fault_words) else None


def _extract_complaint_description(message: str) -> str | None:
    return message.strip() if _contains_any(message, ["投诉", "举报", "维权", "不处理", "拒绝", "太慢"]) else None


def _extract_invoice_type(message: str) -> str | None:
    if _contains_any(message, ["企业", "公司", "专票", "增值税专用"]):
        return "company_invoice"
    if _contains_any(message, ["个人", "普票", "普通发票"]):
        return "personal_invoice"
    return None


def _extract_invoice_title(message: str) -> str | None:
    match = re.search(r"(?:抬头|发票抬头)(?:是|为|：|:)?([\u4e00-\u9fa5A-Za-z0-9（）()·.\-_\s]{2,40})", message)
    return match.group(1).strip() if match else None


def _extract_tax_no(message: str) -> str | None:
    match = re.search(r"(?:税号|纳税人识别号)(?:是|为|：|:)?([A-Z0-9]{10,30})", message, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None


def _clean_slots(slots: dict[str, Any]) -> dict[str, Any]:
    """清理空槽位，避免空字符串被误判为已收集。"""
    return {key: value for key, value in slots.items() if value is not None and str(value).strip() != ""}


def _contains_any(text: str, words: list[str]) -> bool:
    return any(word in text for word in words)


def _context_value(conversation_context: dict[str, Any] | None, key: str) -> str | None:
    """读取结构化上下文实体。"""
    item = (conversation_context or {}).get(key) or {}
    value = item.get("value")
    return str(value) if value else None


def _detect_context_conflict(
    message: str,
    explicit_order_no: str | None,
    selected_order_no: str | None,
    pending: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """识别本轮是否明确切换目标。"""
    if not pending:
        return None
    pending_order_no = str((pending.get("action_slots") or {}).get("order_no") or "").strip()
    current_order_no = explicit_order_no or selected_order_no
    if current_order_no and pending_order_no and current_order_no.lower() != pending_order_no.lower():
        return {
            "type": "order_changed",
            "pending_order_no": pending_order_no,
            "current_order_no": current_order_no,
        }
    if _is_cancel_message(message) and _has_new_status_query(message, explicit_order_no, None):
        return {
            "type": "cancel_pending_with_new_query",
            "pending_order_no": pending_order_no or None,
            "current_order_no": explicit_order_no,
        }
    return None


def _record_context_conflict(conversation_context: dict[str, Any] | None, conflict: dict[str, Any]) -> None:
    """把上下文冲突写入 debug_context，便于后续排查。"""
    if conversation_context is None:
        return
    debug_context = conversation_context.setdefault("debug_context", {})
    debug_context["context_conflict"] = conflict


def _has_new_status_query(message: str, explicit_order_no: str | None, context_ticket_no: str | None) -> bool:
    """判断取消旧动作后，本轮是否还有新的查询诉求。"""
    return bool(
        explicit_order_no
        or context_ticket_no
        or _is_logistics_query_message(message)
        or _contains_any(message, ["查", "查询", "物流", "进度", "状态", "到哪", "催一下", "加急"])
    )


def _is_logistics_query_message(message: str) -> bool:
    """统一复用业务意图层的物流识别，避免 pending 状态机维护另一套不完整关键词。"""
    return normalize_is_logistics_message(message)
