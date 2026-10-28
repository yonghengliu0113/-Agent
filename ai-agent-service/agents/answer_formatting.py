"""客户可见文案格式化：把工具结果、引用、订单与物流数据转成客户可读文本。

这些方法不发起 IO、不修改对象状态，从 CustomerServiceAgent 中拆出以降低上帝类复杂度。
"""

import json
import re
from datetime import datetime
from typing import Any

from graphs.ticket_process_graph import TicketProcessState
from schemas.intent_schema import Citation


class AnswerFormattingMixin:
    """客户可见文案格式化：把工具结果、引用、订单与物流数据转成客户可读文本。"""

    def _safe_citation_payloads(self, citations: list[Citation], limit: int = 3) -> list[dict[str, Any]]:
        """把知识库引用转换为客户可见事实，避免把检索说明、示例表达或内部话术送入 LLM。"""
        payloads: list[dict[str, Any]] = []
        for citation in citations:
            text = self._customer_visible_citation_text(citation)
            if not text:
                continue
            item = citation.model_dump()
            item["paragraph"] = text
            payloads.append(item)
            if len(payloads) >= limit:
                break
        return payloads


    @staticmethod
    def _customer_visible_citation_text(citation: Citation) -> str:
        """清洗单条 citation 正文，只保留能直接回答客户的规则事实。"""
        blocked_terms = [
            "适用范围",
            "适合回答",
            "典型表达",
            "本文档适用于",
            "本文档只说明",
            "检索提示",
            "禁止话术",
            "可用标准话术",
            "标准回复要点",
            "AI 应",
            "AI 不得",
            "不得直接承诺",
        ]
        text = f"{' '.join(citation.heading_path)} {citation.paragraph}"
        if any(term in text for term in blocked_terms):
            return ""
        sentences = [item.strip() for item in re.split(r"(?<=[。！？；;])\s*", citation.paragraph) if item.strip()]
        kept = [
            sentence
            for sentence in sentences
            if not any(term in sentence for term in blocked_terms)
            and not sentence.lstrip().startswith(("-", "“", "\""))
        ]
        return " ".join(kept).strip()


    def _format_action_slot_question(self, state: TicketProcessState) -> str:
        """根据缺失槽位生成客户侧追问，引导用户补齐业务动作所需信息。"""
        analysis = state["analysis"]
        slots = analysis.action_slots or {}
        missing = set(analysis.missing_slots or [])
        order = self._first_success_order(state.get("tool_results", []))
        order_no = slots.get("order_no") or (order or {}).get("orderNo")
        action_name = self._action_display_name(analysis.action_type)
        order_options = self._format_recent_order_options(state.get("tool_results", []))

        if "pending_confirmation" in missing:
            pending = state.get("pending_action_request") or {}
            pending_order_no = (pending.get("action_slots") or {}).get("order_no")
            order_hint = f"订单 {pending_order_no} 的" if pending_order_no else "之前的"
            return f"您之前正在办理{order_hint}{action_name}申请，已间隔一段时间。请确认是否继续该申请？"
        if "action_confirmation" in missing:
            pending = state.get("pending_action_request") or {}
            if pending.get("confirmation_reason") == "ambiguous_unwanted_item":
                order_no = (pending.get("action_slots") or {}).get("order_no")
                order_hint = f"订单 {order_no}" if order_no else "一笔订单"
                return f"请确认您是想为{order_hint}发起退货申请吗？确认后我会继续核对尚缺的信息。"
            return f"之前的{action_name}流程已超时，我不会继续关联原订单。请确认是否重新发起一笔{action_name}申请？"
        if "order_confirmation" in missing:
            pending = state.get("pending_action_request") or {}
            summary = pending.get("candidate_order_summary") or {}
            candidate_order_no = (pending.get("action_slots") or {}).get("candidate_order_no") or summary.get("order_no")
            product_name = summary.get("product_name")
            product_hint = f"（{product_name}）" if product_name else ""
            return f"请确认您要办理的是订单 {candidate_order_no}{product_hint} 吗？回复“是”后我会继续收集{action_name}所需信息。"
        if analysis.action_type == "return_goods" and missing.intersection(
            {"order_no", "after_sale_reason", "return_method", "pickup_time_window"}
        ):
            # 退货流程根据当前真实缺口组合问题，允许客户一轮补充多个槽位，不再固定逐项询问。
            questions: list[str] = []
            if "order_no" in missing:
                questions.append("请选择要退货的订单，或直接回复订单号")
            if "after_sale_reason" in missing:
                questions.append("说明退货原因")
            if "return_method" in missing:
                questions.append("选择上门取件或自行寄回；如需上门取件，也可以同时告诉我方便的时间")
            elif "pickup_time_window" in missing:
                questions.append("告诉我方便上门取件的时间段")
            suffix = f"\n\n您也可以从这些订单中选择：\n{order_options}" if "order_no" in missing and order_options else ""
            prefix = f"已关联订单 {order_no}，" if order_no and "order_no" not in missing else ""
            return prefix + "；".join(questions) + "。" + suffix
        if "order_no" in missing and "after_sale_reason" in missing:
            suffix = f"\n\n您也可以从这些订单中选择：\n{order_options}" if order_options else ""
            return f"请问您要处理哪一笔订单？可以选择订单或直接回复订单号，并说明{action_name}原因。{suffix}"
        if "order_no" in missing:
            suffix = f"\n\n您也可以从这些订单中选择：\n{order_options}" if order_options else ""
            return f"请问您要处理哪一笔订单？可以选择订单或直接回复订单号。{suffix}"
        if "after_sale_reason" in missing:
            prefix = f"已关联订单 {order_no}，" if order_no else ""
            return f"{prefix}请补充{action_name}原因，例如商品质量问题、拍错、不想要、配件缺失等。"
        if "return_method" in missing:
            reason = slots.get("after_sale_reason")
            reason_hint = f"已记录您的退货原因：{reason}。" if reason else ""
            return f"{reason_hint}您希望选择上门取件，还是自行寄回商品？"
        if "pickup_time_window" in missing:
            return (
                "好的，已选择上门取件。请告诉我方便取件的时间段，例如明天下午、工作日 18:00 后或周六上午。"
                "该时间会作为取件偏好登记，最终安排以工作人员或承运方确认为准。"
            )
        if "fault_description" in missing:
            prefix = f"已关联订单 {order_no}，" if order_no else ""
            return f"{prefix}请描述需要维修的具体故障现象，例如无法联网、无法开机、报错或配件异常。"
        if "invoice_title" in missing:
            return "请补充发票抬头；如果是企业发票，也请一并提供税号。"
        if "invoice_type" in missing:
            return "请说明要开个人发票还是企业发票。"
        if "tax_no" in missing:
            return "企业发票需要补充纳税人识别号，请您提供税号。"
        if "description" in missing:
            return "请再补充一下具体诉求或问题描述，我会继续为您记录处理。"
        return "还需要您补充一点信息后才能继续处理，请说明具体订单和诉求。"


    def _format_order_tool_text(self, tool_results: list[dict[str, Any]]) -> str:
        """把订单工具结果转换为客服可读回复，避免用户只能看到右侧调试 JSON。"""
        for item in tool_results:
            if item.get("query_type") == "order_logistics":
                if item.get("status") == "failed":
                    return "已收到物流查询请求，但物流服务暂时不可用。请稍后重试，或由人工客服继续帮您核实。"
                if item.get("status") == "empty":
                    return f"已查询到订单 {item.get('order_no')}，但当前暂无物流轨迹，可能是尚未发货或物流信息还在同步中。"

            if item.get("query_type") == "customer_orders":
                if item.get("status") == "failed":
                    return f"已收到查询请求，但客户订单接口暂时调用失败：{item.get('error')}。请稍后重试或转人工处理。"
                if item.get("status") == "empty":
                    return "我已查询您的账号，当前没有找到关联订单。"
                if item.get("status") == "success":
                    orders = item.get("data") or []
                    lines = ["我已查询到您的订单："]
                    for order in orders[:5]:
                        lines.append(
                            f"- 订单 {order.get('orderNo')}，商品 {order.get('productName') or '未记录'}，"
                            f"状态 {self._order_status(order)}，金额 {order.get('amount')}，"
                            f"售后状态 {order.get('afterSaleStatus') or 'NONE'}"
                        )
                    return "\n".join(lines)

            if item.get("query_type") == "order_detail":
                if item.get("status") == "failed":
                    return (
                        f"已关联您当前选中的订单 {item.get('order_no')}，"
                        "但订单服务暂时无法获取最新信息。请稍后重试，或联系人工客服继续核实。"
                    )
                if item.get("status") == "empty":
                    return f"没有查询到订单 {item.get('order_no')}，请核对订单号是否正确。"
                if item.get("status") == "success":
                    order = item.get("data") or {}
                    return (
                        f"已查询到订单 {order.get('orderNo')}：商品 {order.get('productName') or '未记录'}，"
                        f"当前状态 {self._order_status(order)}，金额 {order.get('amount')}，"
                        f"售后状态 {order.get('afterSaleStatus') or 'NONE'}。"
                    )
        return ""


    def _format_ticket_progress_answer(self, state: TicketProcessState) -> str:
        """根据工单查询或催办工具结果生成客户侧兜底回复。"""
        result = self._first_ticket_tool_result(state, "ticket_urge") or self._first_ticket_tool_result(state, "ticket_status")
        if not result:
            return ""
        if result.get("status") == "empty":
            return "我暂时没有找到可查询或催办的在途工单，请您核对工单号，或从历史记录中选择对应工单后再试。"
        if result.get("status") != "success":
            return "暂时无法同步该工单的最新进度，请稍后重试，或联系人工客服继续核实。"

        ticket = result.get("data") or {}
        ticket_no = ticket.get("ticketNo") or result.get("ticket_no") or "该工单"
        status = ticket.get("status") or "未知"
        urge_count = ticket.get("urgeCount") or 0
        last_urged_at = self._format_time(ticket.get("lastUrgedAt"))
        if result.get("query_type") == "ticket_urge":
            return (
                f"已帮您催办工单 {ticket_no}，当前状态为 {status}。"
                f"这是第 {urge_count} 次催办，最近催办时间为 {last_urged_at}。"
                "工作人员会在原工单中继续跟进处理。"
            )
        return (
            f"工单 {ticket_no} 当前状态为 {status}。"
            f"累计催办 {urge_count} 次，最近催办时间：{last_urged_at}。"
            "如果需要加急，可以回复“帮我催一下”并带上工单号。"
        )


    @staticmethod
    def _first_ticket_tool_result(state: TicketProcessState, query_type: str | None = None) -> dict[str, Any] | None:
        """提取第一条工单查询或催办结果，供回复生成使用。"""
        for item in state.get("tool_results", []):
            if item.get("query_type") in {"ticket_status", "ticket_urge"}:
                if query_type is None or item.get("query_type") == query_type:
                    return item
        return None


    def _ticket_payload_from_tool_results(self, state: TicketProcessState) -> dict[str, Any] | None:
        """把工单工具结果压缩成客户侧安全事实，交给 LLM 生成自然回复。"""
        result = self._first_ticket_tool_result(state)
        if not result or result.get("status") != "success":
            return None
        ticket = result.get("data") or {}
        return {
            "ticketNo": ticket.get("ticketNo"),
            "status": ticket.get("status"),
            "orderNo": ticket.get("orderNo"),
            "urgeCount": ticket.get("urgeCount") or 0,
            "lastUrgedAt": ticket.get("lastUrgedAt"),
            "lastUrgeReason": ticket.get("lastUrgeReason"),
            "queryType": result.get("query_type"),
        }


    def _format_order_intent_answer(self, state: TicketProcessState, citations: list[Citation]) -> str:
        """根据用户意图组织订单回复，避免所有订单相关问题都退化成订单状态复述。"""
        analysis = state["analysis"]
        message = state["message"]
        order = self._first_success_order(state.get("tool_results", []))
        if not order:
            return self._format_order_tool_text(state.get("tool_results", []))

        order_summary = self._format_order_summary(order)
        if self._is_current_order_product_inquiry(state):
            # 订单商品介绍只展示 Java 已核验的业务字段，不能凭商品名编造功能、参数或营销卖点。
            return self._format_selected_order_product_answer(order)
        if self._is_logistics_message(message) or analysis.intent == "logistics":
            logistics_answer = self._format_logistics_answer(state, order)
            if logistics_answer:
                return logistics_answer
            logistics_tip = self._first_citation_text(citations, "Logistics FAQ")
            if not logistics_tip:
                logistics_tip = "订单发货后可通过订单号在订单详情页查询物流状态。"
            return (
                f"{logistics_tip}\n\n"
                f"我已帮您查询当前订单：{order_summary}"
            )

        if analysis.user_goal == "policy_consult" or self._is_after_sale_policy_message(message) or analysis.intent in {"consult", "refund", "exchange"}:
            policy_text = self._policy_citation_text(analysis.intent, citations)
            if not policy_text:
                policy_text = "签收后 7 天内且商品不影响二次销售时，可申请退货；审核通过后通常 1-7 个工作日原路退回，具体以支付渠道为准。"
            return (
                f"关于您咨询的规则：{policy_text}\n\n"
                f"结合当前订单信息：{order_summary}"
            )

        return self._format_order_tool_text(state.get("tool_results", []))


    def _format_selected_order_product_answer(self, order: dict[str, Any]) -> str:
        """基于订单详情中的可信字段介绍商品，信息不足时明确边界而不是返回无依据兜底。"""
        lines = [
            f"您当前选中的是订单 {order.get('orderNo')}，其中的商品是 {order.get('productName') or '商品名称暂未记录'}。",
        ]
        details: list[str] = []
        if order.get("productCategory"):
            details.append(f"分类：{order.get('productCategory')}")
        if order.get("quantity") is not None:
            details.append(f"数量：{order.get('quantity')} 件")
        if order.get("amount") is not None:
            details.append(f"订单实付：¥{order.get('amount')}")
        if order.get("warrantyDays") is not None:
            details.append(f"质保期：{order.get('warrantyDays')} 天")
        if order.get("returnable") is not None:
            details.append(f"支持退货：{'是' if order.get('returnable') else '否'}（最终以售后规则和审核结果为准）")
        if details:
            lines.append("；".join(details) + "。")
        lines.append(f"当前订单状态：{self._order_status(order)}，售后状态：{order.get('afterSaleStatus') or 'NONE'}。")
        lines.append("以上是业务系统中已核验的商品与订单信息；更详细的功能参数需要以商品详情页为准。")
        return "\n".join(lines)


    def _format_logistics_answer(self, state: TicketProcessState, order: dict[str, Any]) -> str:
        """把物流工具结果整理成先结论、后事实的客户可读回复。"""
        logistics_result = self._first_logistics_result(state.get("tool_results", []))
        if not logistics_result:
            return ""
        if logistics_result.get("status") == "failed":
            return "暂时无法获取物流信息，我不会编造物流轨迹。请您稍后重试，或转人工客服继续核实。"
        if logistics_result.get("status") == "empty":
            return (
                f"我已查询到订单 {logistics_result.get('order_no')}，但当前暂无物流轨迹。"
                f"结合订单状态 {self._order_status(order)}，可能是尚未发货或物流节点还在同步中。"
            )

        logistics = logistics_result.get("data") or {}
        traces = logistics.get("traces") or []
        show_all = self._wants_full_logistics(state["message"])
        latest_trace = traces[-1] if traces else {}
        logistics_status = self._logistics_status(logistics.get("logisticsStatus"))
        latest_location = logistics.get("latestLocation") or latest_trace.get("stationName") or latest_trace.get("location") or "暂未更新"
        latest_description = latest_trace.get("description") or f"当前物流状态为{logistics_status}。"

        lines = [
            self._logistics_overview(logistics.get("logisticsStatus"), latest_location),
            "",
            "订单信息",
            f"订单号：{logistics.get('orderNo') or order.get('orderNo')}",
            f"商品：{self._customer_visible_product_name(order)}",
            f"承运商：{logistics.get('carrierName') or '暂未更新'}",
            f"运单号：{logistics.get('trackingNo') or '暂未更新'}",
            "",
            "当前物流",
            f"状态：{logistics_status}",
            f"最新位置：{latest_location}",
            f"最新动态：{latest_description}",
            "",
            self._estimated_delivery_statement(
                logistics.get("estimatedDeliveryTime"),
                logistics.get("logisticsStatus"),
            ),
        ]
        if show_all and traces:
            lines.append("\n完整物流轨迹：")
            for trace in reversed(traces):
                occurred_at = self._format_time(trace.get("occurredAt"))
                station = trace.get("stationName") or trace.get("location") or "未知站点"
                desc = trace.get("description") or self._logistics_status(trace.get("status"))
                lines.append(f"- {occurred_at}｜{station}｜{desc}")
        return "\n".join(lines)


    @staticmethod
    def _logistics_overview(status: Any, latest_location: str) -> str:
        """根据权威物流状态生成一句话结论，不推测承运商尚未返回的信息。"""
        normalized = str(status or "")
        if normalized == "IN_TRANSIT":
            return f"您的订单已经发货，目前正在{latest_location}处理中，等待发往下一站。"
        if normalized == "OUT_FOR_DELIVERY":
            return f"您的订单正在派送中，快件当前位于{latest_location}，请留意配送通知。"
        if normalized == "SIGNED":
            return f"您的订单已签收，最新签收位置为{latest_location}。"
        if normalized == "SHIPPED":
            return f"您的订单已经发货，当前位于{latest_location}，正在等待后续物流更新。"
        if normalized == "EXCEPTION":
            return f"您的订单物流出现异常，最新位置为{latest_location}，建议联系人工客服进一步核实。"
        return f"您的订单物流信息已更新，当前位于{latest_location}。"


    @staticmethod
    def _customer_visible_product_name(order: dict[str, Any]) -> str:
        """优先展示业务系统提供的本地化商品名，并兼容当前演示商品目录。"""
        localized_name = order.get("productDisplayName") or order.get("productNameZh")
        if localized_name:
            return str(localized_name)
        product_name = str(order.get("productName") or "未记录")
        demo_catalog_names = {
            "Noise Cancelling Headset": "降噪耳机",
            "Smart Router AX3000": "AX3000 智能路由器",
        }
        return demo_catalog_names.get(product_name, product_name)


    @classmethod
    def _estimated_delivery_statement(cls, value: Any, status: Any) -> str:
        """区分正常预计时间和已经过期的历史预计时间，避免继续承诺失效时效。"""
        if not value:
            return "承运商暂未更新预计送达时间，请以最新物流动态为准。"
        display_time, expired = cls._format_customer_delivery_time(value)
        if expired and str(status or "") not in {"SIGNED"}:
            return (
                f"原预计送达时间为 {display_time}，目前物流存在延迟，暂未更新新的预计送达时间，"
                "请以最新物流动态为准。"
            )
        return f"预计送达时间为 {display_time}，请以承运商最新物流动态为准。"


    @staticmethod
    def _format_customer_delivery_time(value: Any) -> tuple[str, bool]:
        """将 ISO 时间转换为自然中文日期，并返回该时间是否已经过去。"""
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            prefix = "" if parsed.year == datetime.now().year else f"{parsed.year} 年 "
            formatted = f"{prefix}{parsed.month} 月 {parsed.day} 日 {parsed:%H:%M}"
            return formatted, parsed < datetime.now()
        except (TypeError, ValueError):
            # 上游时间格式异常时保留安全文本，不因展示问题丢弃整条物流结果。
            return AnswerFormattingMixin._format_time(value), False


    def _format_order_context_text(self, tool_results: list[dict[str, Any]]) -> str:
        """为人工处理场景补充简短订单上下文，避免订单信息喧宾夺主。"""
        for item in tool_results:
            if item.get("query_type") == "customer_orders" and item.get("status") == "success":
                orders = item.get("data") or []
                if orders:
                    order = orders[0]
                    return f"已关联订单 {order.get('orderNo')}，当前订单状态 {self._order_status(order)}。"
            if item.get("query_type") == "order_detail" and item.get("status") == "success":
                order = item.get("data") or {}
                return f"已关联订单 {order.get('orderNo')}，当前订单状态 {self._order_status(order)}。"
        return ""


    def _format_recent_order_options(self, tool_results: list[dict[str, Any]]) -> str:
        """把客户最近订单压缩成可选择列表，供动作槽位追问时展示。"""
        for item in tool_results:
            if item.get("query_type") == "customer_orders" and item.get("status") == "success":
                orders = item.get("data") or []
                lines = []
                for order in orders[:3]:
                    lines.append(
                        f"- {order.get('orderNo')} / {order.get('productName') or '商品信息待补充'} / "
                        f"状态 {self._order_status(order)}"
                    )
                return "\n".join(lines)
        return ""


    @staticmethod
    def _action_display_name(action_type: str | None) -> str:
        """将 action_type 转成客户可理解的动作名称。"""
        mapping = {
            "return_goods": "退货",
            "refund_request": "退款",
            "exchange_goods": "换货",
            "repair_request": "维修",
            "invoice_issue": "开票",
            "cancel_order": "取消订单",
            "complaint_submit": "投诉",
        }
        return mapping.get(str(action_type), "处理")


    @staticmethod
    def _order_status(order: dict[str, Any]) -> str:
        """兼容 Java 订单字段命名，优先读取当前 DTO 的 orderStatus。"""
        return str(order.get("orderStatus") or order.get("status") or "未知")


    def _first_success_order(self, tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        """从工具结果中提取第一条成功订单，供意图化回复使用。"""
        for item in tool_results:
            if item.get("query_type") == "order_detail" and item.get("status") == "success":
                return item.get("data") or {}
            if item.get("query_type") == "customer_orders" and item.get("status") == "success":
                orders = item.get("data") or []
                if orders:
                    return orders[0]
        return None


    @staticmethod
    def _first_logistics_result(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        """提取第一条物流工具结果，供物流回复优先使用真实轨迹。"""
        for item in tool_results:
            if item.get("query_type") == "order_logistics":
                return item
        return None


    @staticmethod
    def _first_logistics_data(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        """提取成功物流数据，供 LLM 回复生成时使用真实轨迹而不是猜测。"""
        for item in tool_results:
            if item.get("query_type") == "order_logistics" and item.get("status") == "success":
                return item.get("data") or {}
        return None


    def _format_order_summary(self, order: dict[str, Any]) -> str:
        """格式化订单摘要，复用在物流、政策和普通查单回复中。"""
        return (
            f"订单 {order.get('orderNo')}，商品 {order.get('productName') or '未记录'}，"
            f"当前状态 {self._order_status(order)}，金额 {order.get('amount')}，"
            f"售后状态 {order.get('afterSaleStatus') or 'NONE'}。"
        )


    @staticmethod
    def _format_time(value: Any) -> str:
        """格式化 Java 返回的 ISO 时间，避免客户侧看到空值或过长时间串。"""
        if not value:
            return "暂无"
        text = str(value)
        return text.replace("T", " ")[:16]


    @classmethod
    def _format_estimated_delivery_time(cls, value: Any) -> str:
        """保留预计送达绝对时间；如果预计时间已过，明确说明其仅为历史预估。"""
        formatted = cls._format_time(value)
        if not value:
            return formatted
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            # 过期的预计时间不能再被描述为“今天送达”，应提醒客户以最新节点为准。
            if parsed < datetime.now():
                return f"{formatted}（该预计时间已过，请以最新物流节点为准）"
        except (TypeError, ValueError):
            # 格式异常时保留原始可见时间，避免因展示层异常丢弃可用业务信息。
            pass
        return formatted


    @staticmethod
    def _logistics_status(status: Any) -> str:
        """将物流状态枚举转换为客户可读中文，未知状态保留原值便于追踪。"""
        mapping = {
            "PENDING_SHIPMENT": "待发货",
            "SHIPPED": "已发货",
            "IN_TRANSIT": "运输中",
            "OUT_FOR_DELIVERY": "派送中",
            "SIGNED": "已签收",
            "EXCEPTION": "物流异常",
        }
        return mapping.get(str(status), str(status or "未知"))


    @staticmethod
    def _first_citation_text(citations: list[Citation], doc_name: str) -> str:
        """按文档名取知识库片段，避免物流问题误用退货政策。"""
        for citation in citations:
            if citation.doc_name == doc_name:
                text = AnswerFormattingMixin._customer_visible_citation_text(citation)
                if text:
                    return text
        for citation in citations:
            text = AnswerFormattingMixin._customer_visible_citation_text(citation)
            if text:
                return text
        return ""


    def _policy_citation_text(self, intent: str, citations: list[Citation]) -> str:
        """按业务域选择最贴合的政策片段，避免退款问题混入退货、维修等无关内容。"""
        preferred_docs = {
            "refund": ["Refund Arrival Policy", "Return Exchange Policy"],
            "exchange": ["Return Exchange Policy"],
            "repair": ["Repair Policy"],
            "invoice": ["Invoice FAQ"],
            "member": ["Member FAQ"],
            "logistics": ["Logistics FAQ"],
        }
        for doc_name in preferred_docs.get(intent, []):
            for citation in citations:
                if citation.doc_name == doc_name:
                    text = self._customer_visible_citation_text(citation)
                    if text:
                        return text
        for citation in citations:
            text = self._customer_visible_citation_text(citation)
            if text:
                return text
        return ""


    def _format_customer_ticket_text(self, ticket_result: dict[str, Any] | None) -> str:
        """将工单接口结果整理为客户可追踪的信息，只展示工单号和当前状态。"""
        if not ticket_result or ticket_result.get("status") != "success":
            return ""

        data = ticket_result.get("data") or {}
        ticket_no = data.get("ticketNo")
        status = data.get("status")
        if not ticket_no:
            return ""
        if ticket_result.get("deduplicated"):
            if status == "PENDING_ASSIGN":
                return f"您之前已提交过相关申请，工单号为 {ticket_no}，目前正在等待工作人员分派处理，请勿重复提交。"
            if status in {"PENDING_PROCESS", "PROCESSING"}:
                return f"您之前已提交过相关申请，工单号为 {ticket_no}，目前已分派给客服继续处理，请勿重复提交。"
            return f"您之前已提交过相关申请，工单号为 {ticket_no}，当前状态：{status or '待分派'}，请勿重复提交。"
        if status == "PENDING_ASSIGN":
            return f"您的问题已提交成功，工单号为 {ticket_no}，目前已进入受理流程，后续将由工作人员分派处理。"
        if status in {"PENDING_PROCESS", "PROCESSING"}:
            return f"您的问题已提交成功，工单号为 {ticket_no}，已分派给客服处理。"
        return f"您的问题已提交成功，工单号为 {ticket_no}，当前状态：{status or '待分派'}。"


    @staticmethod
    def _customer_safe_ticket_payload(ticket_result: dict[str, Any] | None) -> dict[str, Any] | None:
        """提取客户侧可使用的工单事实，避免把内部派单原因或风险字段交给回复模型。"""
        if not ticket_result or ticket_result.get("status") != "success":
            return None
        data = ticket_result.get("data") or {}
        return {
            "ticketNo": data.get("ticketNo"),
            "status": data.get("status"),
            "orderNo": data.get("orderNo"),
            "deduplicated": bool(ticket_result.get("deduplicated")),
        }


    def _format_ticket_text(self, ticket_result: dict[str, Any] | None) -> str:
        """把 Java 工单接口返回结果转换为用户可读提示，不暴露内部异常细节。"""
        if not ticket_result:
            return ""
        if ticket_result.get("status") != "success":
            return "工单创建暂未成功，客服会继续人工跟进。"

        data = ticket_result.get("data") or {}
        ticket_no = data.get("ticketNo")
        status = data.get("status")
        if not ticket_no:
            return "工单已提交。"
        if ticket_result.get("deduplicated"):
            return f"您已提交过相关申请，工单 {ticket_no} 当前状态：{status}。"
        if status == "PENDING_ASSIGN":
            return f"已创建工单 {ticket_no}，目前待工作人员分派处理。"
        if status in {"PENDING_PROCESS", "PROCESSING"}:
            return f"已创建工单 {ticket_no}，已分派给客服处理。"
        return f"已创建工单 {ticket_no}，当前状态：{status}。"


    @staticmethod
    def _compact_memory_json(memory: dict[str, Any], limit: int = 10000) -> str:
        """稳定序列化安全记忆，并设置整体上限避免 Prompt 无界增长。"""
        text = json.dumps(memory or {}, ensure_ascii=False, separators=(",", ":"), default=str)
        return text[:limit]
