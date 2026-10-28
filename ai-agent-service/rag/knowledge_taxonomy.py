from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeCollection:
    """客服知识集合定义，用于约束检索范围和知识来源。"""

    name: str
    business_scopes: tuple[str, ...]
    answerable_intents: tuple[str, ...]
    source_priority: tuple[str, ...]


SOURCE_PRIORITY = (
    "official_policy",
    "operation_rule",
    "staff_script",
    "historical_ticket_summary",
)


KNOWLEDGE_COLLECTIONS: dict[str, KnowledgeCollection] = {
    "logistics_policy": KnowledgeCollection(
        name="logistics_policy",
        business_scopes=("logistics",),
        answerable_intents=("logistics", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "refund_policy": KnowledgeCollection(
        name="refund_policy",
        business_scopes=("refund", "return_goods", "compensation_dispute"),
        answerable_intents=("refund", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "exchange_policy": KnowledgeCollection(
        name="exchange_policy",
        business_scopes=("exchange",),
        answerable_intents=("exchange", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "repair_policy": KnowledgeCollection(
        name="repair_policy",
        business_scopes=("repair",),
        answerable_intents=("repair", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "invoice_policy": KnowledgeCollection(
        name="invoice_policy",
        business_scopes=("invoice",),
        answerable_intents=("invoice", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "member_policy": KnowledgeCollection(
        name="member_policy",
        business_scopes=("member",),
        answerable_intents=("member", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "complaint_policy": KnowledgeCollection(
        name="complaint_policy",
        business_scopes=("complaint", "compensation_dispute"),
        answerable_intents=("complaint", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "general_faq": KnowledgeCollection(
        name="general_faq",
        business_scopes=("general",),
        answerable_intents=("consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    # 货运行业知识集合：与业务域同名，保证检索过滤和 rerank 加分口径一致。
    "customs_policy": KnowledgeCollection(
        name="customs_policy",
        business_scopes=("customs",),
        answerable_intents=("logistics", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "dangerous_goods_policy": KnowledgeCollection(
        name="dangerous_goods_policy",
        business_scopes=("dangerous_goods",),
        answerable_intents=("logistics", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "cold_chain_policy": KnowledgeCollection(
        name="cold_chain_policy",
        business_scopes=("cold_chain",),
        answerable_intents=("logistics", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "vehicle_capacity_policy": KnowledgeCollection(
        name="vehicle_capacity_policy",
        business_scopes=("vehicle_capacity",),
        answerable_intents=("logistics", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "cargo_claims_policy": KnowledgeCollection(
        name="cargo_claims_policy",
        business_scopes=("cargo_claims",),
        answerable_intents=("logistics", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
    "booking_documents_policy": KnowledgeCollection(
        name="booking_documents_policy",
        business_scopes=("booking_documents",),
        answerable_intents=("logistics", "consult", "other"),
        source_priority=SOURCE_PRIORITY,
    ),
}


# 货运行业的业务域关键词：用于把笼统的 logistics 意图细分到专业知识域。
# 顺序即优先级，命中越靠前的域越具体（如「危险品报关」优先归危险品）。
FREIGHT_SCOPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dangerous_goods", ("危险品", "危化品", "锂电池", "un编号", "msds", "化工品", "危险货物", "dgr", "iata", "危险品运输", "包装等级", "包装类别", "充电宝", "瓦时", "荷电状态", "un3480", "un3090", "隐含危险品", "申报单")),
    ("cold_chain", ("冷链", "冷藏", "冷冻", "恒温", "温控", "干冰", "冷库", "温度记录", "断链", "温区", "疫苗", "药品", "医药", "保温箱", "蓄冷", "冷藏车", "液氮")),
    (
        "booking_documents",
        (
            "订舱", "提单", "电放", "舱单", "截关", "截单", "截港", "vgm", "改单", "so单", "海运单",
            "awb", "运单号", "航空运单", "提货单", "滞箱", "滞港", "免箱期", "免费期", "ams", "ics2", "ens", "提箱", "还箱",
        ),
    ),
    (
        "customs",
        (
            "报关", "清关", "通关", "海关", "查验", "关税", "报关单", "hs编码", "商品编码", "归类",
            "原产地证", "出口退税", "退税", "跨境电商", "滞报", "滞纳", "申报", "缴税",
            "完税", "许可证件", "两用物项", "出口管制", "报关委托", "提前申报", "两步申报", "外汇核销", "核销单", "随附单证",
        ),
    ),
    ("cargo_claims", ("货损", "货差", "保价", "理赔", "货运险", "索赔", "免赔", "灭失", "破损", "赔偿责任", "赔偿标准", "赔偿限额", "延误赔偿", "足额保", "基础保", "免赔额", "承运人不赔", "承运人免责", "免责情形", "部分损失", "部分损毁")),
    ("vehicle_capacity", ("零担", "整车", "计费重量", "体积重量", "重量系数", "抛货", "轻抛", "抛比", "载重", "限重", "超限", "轴荷", "车型", "方数", "容积", "附加费", "起步价", "运费怎么算", "大票货", "大票", "公斤段", "gb1589", "gb 1589", "六轴", "轴数")),
)

# 冷媒类问题常同时出现「干冰」与「危险品」，此时应归危险品域判断类别与申报要求。
DRY_ICE_AS_DANGEROUS_GOODS_TERMS = ("属于危险品", "是危险品吗", "算危险品", "危险品吗", "是不是危险品")


def infer_freight_scope(message: str) -> str | None:
    """按专业关键词把货运问题细分到具体知识域，无法判断时返回 None。

    只有命中行业术语才细分，普通快递配送问题仍走通用物流域，
    避免把「包裹没收到」这类问题路由到报关或危险品知识库。
    """
    text = (message or "").lower()
    for scope, keywords in FREIGHT_SCOPE_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return scope
    return None


INTENT_TO_COLLECTIONS: dict[str, tuple[str, ...]] = {
    "logistics": ("logistics_policy",),
    "refund": ("refund_policy",),
    "exchange": ("exchange_policy",),
    "repair": ("repair_policy",),
    "complaint": ("complaint_policy",),
    "invoice": ("invoice_policy",),
    "member": ("member_policy",),
    "consult": ("general_faq",),
    "other": ("general_faq",),
}


def collections_for_intent(intent: str, business_scope: str | None = None) -> list[str]:
    """根据意图和业务范围推导可检索知识集合，避免全库混搜。"""
    if business_scope:
        matched = [
            collection.name
            for collection in KNOWLEDGE_COLLECTIONS.values()
            if business_scope in collection.business_scopes
        ]
        if matched:
            return matched
    return list(INTENT_TO_COLLECTIONS.get(intent, ("general_faq",)))


def infer_business_scope(intent: str, user_goal: str | None = None, query: str | None = None) -> str:
    """把 Agent 意图转换为知识库业务范围。

    物流意图下先尝试按货运专业术语细分到危险品、报关、冷链等专业域，
    只有识别不出专业域时才落到通用物流域。
    """
    if intent == "logistics" and query:
        # 冷媒类问题同时命中冷链与危险品，询问归类时应落到危险品域。
        if any(term in query for term in DRY_ICE_AS_DANGEROUS_GOODS_TERMS) and any(
            term in query for term in ("干冰", "液氮")
        ):
            return "dangerous_goods"
        freight_scope = infer_freight_scope(query)
        if freight_scope:
            return freight_scope
    if intent in {"logistics", "refund", "exchange", "repair", "invoice", "member", "complaint"}:
        return intent
    if user_goal in {"complaint", "dispute"}:
        return "complaint"
    return "general"
