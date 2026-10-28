"""意图与消息类型判定：从客户原话与会话上下文中识别意图、身份、售后、工单等信号。

这些方法只做只读判断，不修改对象状态，从 CustomerServiceAgent 中拆出以降低上帝类体积。
"""

import re
from typing import Any

from agents.intent_normalizer import is_action_request_message as normalize_is_action_request_message
from agents.intent_normalizer import is_delivery_not_received_message, is_how_to_message
from agents.intent_normalizer import is_identity_message as normalize_is_identity_message
from agents.intent_normalizer import is_logistics_message as normalize_is_logistics_message
from agents.intent_normalizer import is_order_query_message as normalize_is_order_query_message
from graphs.ticket_process_graph import TicketProcessState
from schemas.intent_schema import Citation


class MessageClassifierMixin:
    """意图与消息类型判定：从客户原话与会话上下文中识别意图、身份、售后、工单等信号。"""

    @staticmethod
    def _has_natural_out_of_scope_boundary(answer: str) -> bool:
        """判断模型是否已经生成自然的服务边界，避免每次都套固定收尾。"""
        scope_words = ["订单", "物流", "售后", "工单", "发票"]
        scope_hits = sum(1 for word in scope_words if word in answer)
        if scope_hits < 2:
            return False
        stiff_markers = ["我是", "作为", "客服助手", "客户服务助手", "企业客服助手", "自助客服助手", "主要处理", "主要负责", "主要帮助处理"]
        if any(marker in answer for marker in stiff_markers):
            return False
        friendly_markers = ["如果", "可以", "也能", "也可以", "继续", "帮您", "帮你", "这方面", "相关"]
        return any(marker in answer for marker in friendly_markers)


    @staticmethod
    def _is_return_goods_citation(citation: Citation) -> bool:
        """判断召回片段是否真正属于退货规则，过滤退款到账、维修、保修等相邻政策。"""
        text = f"{citation.doc_name} {' '.join(citation.heading_path)} {citation.paragraph}"
        metadata = citation.metadata or {}
        if MessageClassifierMixin._is_policy_metadata_text(text):
            return False
        if citation.business_scope == "return_goods" or metadata.get("category") == "return_policy":
            return True
        return any(term in text for term in ["退货", "七天无理由", "二次销售", "签收后"]) and not any(
            term in text for term in ["保修", "维修", "质保", "报修", "故障维修"]
        )


    @staticmethod
    def _is_return_goods_policy_text_specific(policy_text: str) -> bool:
        """判断退货规则片段是否包含可直接回答客户的具体规则事实。"""
        if not policy_text or not policy_text.strip():
            return False
        weak_terms = [
            "AI 应",
            "不得直接承诺",
            "无法直接承诺",
            "需要结合具体商品规则",
            "需要结合商品规则",
            "订单状态来判断",
            "系统无法确认",
            "建议联系人工",
        ]
        if any(term in policy_text for term in weak_terms):
            return False
        concrete_terms = ["7 天", "七天", "签收", "二次销售", "商品完好", "售后页面", "提交退货申请", "售后时效"]
        return any(term in policy_text for term in concrete_terms)


    @staticmethod
    def _is_policy_metadata_text(text: str) -> bool:
        """识别知识库管理说明类片段，防止直接作为客户回复内容。"""
        metadata_terms = [
            "适用范围",
            "适合回答",
            "典型表达",
            "本文档适用于",
            "检索提示",
            "禁止话术",
            "可用标准话术",
            "标准回复要点",
        ]
        return any(term in text for term in metadata_terms)


    @staticmethod
    def _is_return_goods_policy_answer_usable(answer: str) -> bool:
        """校验模型生成的退货规则话术是否适合直接展示给客户。"""
        if not answer or not answer.strip():
            return False
        # 调用方已经确认存在可用 policy_text；模型若仍声称知识库无规则，属于与检索证据冲突的生成结果。
        no_policy_phrases = [
            "当前知识库未找到明确退货规则",
            "知识库未找到退货规则",
            "没有找到明确的退货规则",
            "未检索到退货规则",
        ]
        if any(phrase in answer for phrase in no_policy_phrases):
            return False
        metadata_terms = [
            "适用范围",
            "适合回答",
            "典型表达",
            "本文档适用于",
            "检索提示",
            "禁止话术",
            "可用标准话术",
            "标准回复要点",
            "我想退货",
            "这个商品能退吗",
            "提供订单号",
            "订单号",
            "联系人工",
            "人工客服",
            "进一步核实后操作",
            "进一步核实后",
            "系统中暂未找到具体的时效",
            "暂未找到具体的时效",
            "暂未找到具体时效",
            "具体商品规则和订单状态",
            "结合商品规则和订单状态",
            "结合具体商品规则",
            "无法直接承诺一定可以退货",
        ]
        return not any(term in answer for term in metadata_terms)


    @staticmethod
    def _is_safe_customer_reply(answer: str) -> bool:
        """过滤明显泄露内部字段或调试信息的模型回复，失败时回退安全模板。"""
        if not answer or not answer.strip():
            return False
        internal_markers = ["risk_reasons", "tool_results", "internal_suggestion", "decision_type", "```json", "{", "}"]
        return not any(marker in answer for marker in internal_markers)


    def _has_customer_order_result(self, state: TicketProcessState) -> bool:
        """判断是否已经通过客户 ID 查询过订单列表，避免继续要求用户补充订单号。"""
        return any(
            item.get("query_type") == "customer_orders" and item.get("status") in {"success", "empty"}
            for item in state.get("tool_results", [])
        )


    def _has_customer_order_attempt(self, state: TicketProcessState) -> bool:
        """判断是否已经尝试按客户查询订单，即使失败也不再要求用户重复提供订单号。"""
        return any(item.get("query_type") == "customer_orders" for item in state.get("tool_results", []))


    @staticmethod
    def _has_failed_selected_order_query(state: TicketProcessState) -> bool:
        """判断当前前端已选订单是否在查询阶段失败，防止失败时退化为索要订单号。"""
        selected_order_no = str(state.get("selected_order_no") or "").strip()
        if not selected_order_no:
            return False
        return any(
            item.get("query_type") in {"order_detail", "order_logistics"}
            and str(item.get("order_no") or "") == selected_order_no
            and item.get("status") == "failed"
            for item in state.get("tool_results", [])
        )


    @staticmethod
    def _is_delivery_contingency_message(message: str) -> bool:
        """识别“未来未送达时再售后”的条件表达，不把普通退货或物流查询误拦截。"""
        text = message.strip()
        # “收不到”与“未收到”语义相同，但前者不一定命中通用未收货识别器，需在此覆盖自然表达。
        has_delivery_absence = is_delivery_not_received_message(text) or any(
            word in text
            for word in ["收不到", "没收到", "未收到", "还没收到", "包裹没到", "快递没到", "货没到"]
        )
        if not text or not has_delivery_absence:
            return False
        has_after_sale_request = any(word in text for word in ["退货", "退款", "售后", "处理"]) or bool(
            # 单独的“退了/退吧”只有处在动作语境时才视为售后请求，避免把普通“退回”误判。
            re.search(r"(?:帮我|给我|就|要|想|申请).{0,4}退(?:了|吧)?", text)
        )
        has_future_condition = any(
            word in text
            for word in ["如果", "要是", "若", "到时候", "明天", "后天", "届时", "再"]
        )
        return has_after_sale_request and has_future_condition


    def _wants_full_logistics(self, message: str) -> bool:
        """识别客户是否要求物流时间线、节点明细或完整运输路线。"""
        return self._contains_any(
            message,
            [
                "物流轨迹",
                "运输轨迹",
                "快递轨迹",
                "物流节点",
                "运输节点",
                "物流详情",
                "物流明细",
                "全流程",
                "完整轨迹",
                "经过哪里",
                "运输路线",
                "转运站",
                "到过哪里",
            ],
        )


    def _is_return_goods_order_status_message(self, message: str) -> bool:
        """识别用户是否在问具体订单能否退货，只有此类问题才需要查订单。"""
        order_reference = bool(re.search(r"(?<![A-Za-z])(?:EC)?\d{10,18}", message, flags=re.IGNORECASE)) or self._contains_any(
            message,
            ["我的订单", "这个订单", "这笔订单", "该订单", "当前订单", "订单号"],
        )
        return order_reference and self._contains_any(
            message,
            ["能退吗", "能不能退", "可以退吗", "可不可以退", "是否能退", "支持退货吗", "能退货吗"],
        )


    def _is_return_goods_policy_message(self, message: str) -> bool:
        """识别退货规则咨询，和“我要退货”等真实操作申请区分开。"""
        if self._is_action_request_message(message):
            return False
        if self._is_return_goods_order_status_message(message):
            return False
        return self._contains_any(
            message,
            [
                "查看退货规则",
                "退货规则是什么",
                "退货规则",
                "退货条件",
                "退货政策",
                "七天无理由",
                "商品能不能退",
                "能不能退货",
                "可以退货吗",
                "怎么申请退货",
                "如何申请退货",
                "退货流程",
            ],
        )


    def _is_after_sale_policy_message(self, message: str) -> bool:
        """识别退货、换货、售后规则类低风险政策咨询。"""
        return self._contains_any(
            message,
            ["退货规则", "退货政策", "退款规则", "退款政策", "多久到账", "多久退", "退款流程", "怎么退款", "退货", "换货规则", "换货政策", "售后规则", "售后政策"],
        )


    @staticmethod
    def _is_deduplicated_ticket(ticket_result: dict[str, Any] | None) -> bool:
        """判断本次是否复用了已有未完成工单，用于客户侧展示专用提醒。"""
        return bool(ticket_result and ticket_result.get("status") == "success" and ticket_result.get("deduplicated"))


    @staticmethod
    def _contains_any(text: str, words: list[str]) -> bool:
        """判断文本是否命中任一业务关键词，用于规则兜底识别。"""
        return any(word in text for word in words)


    def _is_agent_identity_message(self, message: str) -> bool:
        """识别客户询问智能客服身份或能力的闲聊式问题，避免误建工单。"""
        return normalize_is_identity_message(message)


    def _is_action_request_message(self, message: str) -> bool:
        """识别真实业务动作请求，避免被“退货”等关键词误判成政策咨询。"""
        return normalize_is_action_request_message(message)


    def _is_logistics_message(self, message: str) -> bool:
        """识别物流配送类表达，用于修正模型对短物流问题的保守分类。"""
        return normalize_is_logistics_message(message)


    def _is_order_query_message(self, message: str) -> bool:
        """识别泛订单查询表达，用于支持没有订单号但有客户上下文的查单场景。"""
        return normalize_is_order_query_message(message)


    def _is_ticket_progress_message(self, message: str) -> bool:
        """识别客户查询工单进度的表达。"""
        return (bool(re.search(r"T\d{12,24}", message, flags=re.IGNORECASE)) or "工单" in message) and self._contains_any(
            message,
            ["工单", "进度", "处理", "状态", "到哪"],
        )


    def _is_ticket_urge_message(self, message: str) -> bool:
        """识别客户催办已有工单的表达，走催办 Tool 而不是新建工单。"""
        return ("工单" in message or re.search(r"T\d{12,24}", message, flags=re.IGNORECASE)) and self._contains_any(
            message,
            ["催", "催一下", "催催", "加急", "尽快", "太慢", "怎么还没", "帮我催", "推进"],
        )


    def _is_after_sale_dispute_message(self, message: str) -> bool:
        """识别商品质量、换货被拒等售后争议场景，避免只返回订单列表。"""
        dispute_words = [
            "质量不好",
            "质量问题",
            "有瑕疵",
            "破损",
            "坏了",
            "不能用",
            "不给更换",
            "不给换",
            "拒绝更换",
            "商家不给",
            "商家拒绝",
            "售后不处理",
        ]
        return self._contains_any(message, dispute_words)


    def _has_context_reference(self, message: str) -> bool:
        """识别需要依赖历史上下文解析的指代表达。

        除显式指代词外，以“那/这/这样”开头的追问(如“那走哪个产品合适?”)
        通常是对上一轮话题的承接，同样需要注入历史上下文供模型解析。
        """
        compact = re.sub(r"[\s，。！？!?]", "", message or "")
        if compact.startswith(("那", "这", "这样", "那这")):
            return True
        return self._contains_any(message, ["刚才", "刚刚", "上面", "之前", "上一句", "前面", "那个", "这个", "这款", "此款", "这件", "该商品", "这单", "那单", "还是", "继续", "重新", "再查", "刷新", "接着", "它", "那就"])


    @staticmethod
    def _is_task_control_message(message: str) -> bool:
        """识别需要结合任务记忆理解的短控制语句。"""
        compact = re.sub(r"[\s，。！？!?]", "", message or "")
        return compact in {"重新查询", "再查一下", "再查询一下", "重新查一下", "刷新一下", "继续", "接着处理", "继续处理"}


    def _has_current_selected_order(self, conversation_context: dict[str, Any] | None) -> bool:
        """判断当前请求是否携带前端明确选中订单，用于安全地补充意图模型上下文。"""
        return bool(self._current_selected_order_no(conversation_context))


    def _is_current_order_product_inquiry(self, state: TicketProcessState) -> bool:
        """依据结构化语义对象选择商品回复，不再反向解析用户表面措辞。"""
        return state["analysis"].query_subject == "product"


    def _is_user_identity_message(self, message: str) -> bool:
        """识别客户询问自身登录身份的问题，必须用登录态确定性回答。"""
        text = message.strip()
        return bool(re.search(r"(我是谁|你知道我是谁吗|知道我是谁吗|我叫什么|我的身份|当前账号是谁)", text))


    def _is_session_memory_question(self, message: str) -> bool:
        """识别客户询问当前会话历史的问题，避免模型谎称无法看到上下文。"""
        text = message.strip()
        return bool(
            self._contains_any(text, ["我刚刚问", "我刚才问", "上一句我说", "前一句我说", "我问了什么", "刚才聊", "之前聊", "前面聊", "我们刚才"])
            and self._contains_any(text, ["什么", "内容", "问题", "说"])
        )


    def _is_other_identity_order_request(self, message: str, conversation_context: dict[str, Any] | None) -> bool:
        """识别按姓名查询订单的请求；姓名不是授权凭据，不能触发订单工具。"""
        if "订单" not in message or not self._contains_any(message, ["查", "查询", "看", "看看", "帮我"]):
            return False
        login_user = (conversation_context or {}).get("login_user_context") or {}
        display_name = self._normalize_identity_name(login_user.get("display_name"))
        explicit_names = [self._normalize_identity_name(name) for name in re.findall(r"([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{1,11})的订单", message)]
        current_claim = self._extract_self_claimed_name_from_message(message)
        if current_claim:
            explicit_names.append(self._normalize_identity_name(current_claim))
        return any(name and name != display_name for name in explicit_names)


    @staticmethod
    def _normalize_identity_name(value: Any) -> str:
        """归一化姓名用于安全比较。"""
        return re.sub(r"\s+", "", str(value or "").strip()).lower()


    @staticmethod
    def _extract_self_claimed_name_from_message(message: str) -> str | None:
        """从本轮消息提取自称姓名，避免本轮自称直接触发查单。"""
        for pattern in [
            r"(?:我叫|我是|本人叫|我的名字叫)\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{1,11})",
            r"(?:以后|之后)?(?:请)?(?:叫我|称呼我为|喊我)\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z·]{1,11})",
        ]:
            match = re.search(pattern, message)
            if match:
                return match.group(1).strip(" ，,。！？!；;：:")
        return None


    def _is_context_ticket_message(self, message: str, conversation_context: dict[str, Any]) -> bool:
        """识别省略工单号的工单查询或催办。"""
        return bool(
            self._conversation_context_value(conversation_context, "last_ticket")
            and not is_how_to_message(message)
            and not self._is_logistics_message(message)
            and self._contains_any(message, ["催", "催一下", "加急", "进度", "处理", "状态", "怎么还没"])
        )


    @staticmethod
    def _conversation_context_value(conversation_context: dict[str, Any], key: str) -> str | None:
        """读取上下文实体值。"""
        item = (conversation_context or {}).get(key) or {}
        value = item.get("value")
        return str(value) if value else None
