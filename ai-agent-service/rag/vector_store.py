import math
import re
import hashlib
from datetime import datetime
from typing import Any

from rag.knowledge_taxonomy import collections_for_intent, infer_business_scope
from rag.text_processing import KnowledgeChunk
from schemas.intent_schema import Citation


# query rewrite 补充词的计分权重：只用于补充召回，不能压过客户原话里的实词。
EXPANSION_WEIGHT = 0.25


class InMemoryVectorStore:
    """内存知识库基线，实现 metadata filter、BM25 检索和规则 rerank。"""

    def __init__(self, chunks: list[KnowledgeChunk] | None = None) -> None:
        """初始化内存知识库，默认加载 data/kb_sources 下的真实知识文档。

        传入 chunks 时用于评测或测试注入；未传入时优先读知识库目录，
        目录为空才回退到内置示例知识，保证本地无知识文档时链路仍可验证。
        """
        self.chunks = chunks if chunks is not None else _load_default_chunks()
        self._doc_freq = self._build_doc_frequency(self.chunks)
        self._avg_doc_len = sum(len(_tokenize(_chunk_scoring_text(chunk))) for chunk in self.chunks) / max(len(self.chunks), 1)

    def similarity_search(
        self,
        query: str,
        *,
        intent: str = "other",
        user_goal: str = "other",
        business_scope: str | None = None,
        collection: str | None = None,
        top_k: int = 5,
        rewrite_mode: str = "rule_fallback",
    ) -> list[Citation]:
        """执行带业务过滤的 BM25 基线检索，并返回可引用片段。"""
        rewritten_query = rewrite_query(query, business_scope=business_scope, intent=intent)
        # 调用方未显式指定业务域时，先尝试按货运术语细分，再退回意图映射。
        resolved_scope = business_scope or infer_business_scope(intent, user_goal, query=query)
        allowed_collections = [collection] if collection else collections_for_intent(intent, resolved_scope)
        candidates = [
            chunk
            for chunk in self.chunks
            if _is_published_now(chunk)
            and is_customer_visible_chunk(chunk.paragraph, chunk.heading_path)
            and chunk.collection in allowed_collections
            and (resolved_scope == "general" or chunk.business_scope == resolved_scope or resolved_scope in chunk.metadata.get("aliases", []))
            and (not chunk.answerable_intents or intent in chunk.answerable_intents or "consult" in chunk.answerable_intents)
        ]

        scored: list[tuple[KnowledgeChunk, float, float]] = []
        # 改写词只做补充召回，权重远低于客户原话；否则业务域通用词会淹没问题里的实词。
        expansion = rewritten_query[len(query):].strip()
        for chunk in candidates:
            # 标题路径参与 BM25 计分，让「版本状态」这类只出现在小节标题里的关键词能命中对应片段。
            heading = " ".join(chunk.heading_path)
            bm25_score = self._bm25(query, chunk.paragraph, heading=heading)
            if expansion:
                bm25_score += EXPANSION_WEIGHT * self._bm25(expansion, chunk.paragraph, heading=heading)
            rerank_score = _rerank_score(query, chunk, bm25_score, resolved_scope)
            if rerank_score > 0:
                scored.append((chunk, bm25_score, rerank_score))

        scored.sort(key=lambda item: item[2], reverse=True)
        return [
            _to_citation(chunk, score=_normalize_score(score), bm25_score=bm25_score, query=rewritten_query, rewrite_mode=rewrite_mode)
            for chunk, bm25_score, score in scored[:top_k]
        ]

    def _bm25(self, query: str, text: str, *, heading: str = "") -> float:
        """用简化 BM25 形成可解释的全文检索基线。

        标题路径参与计分：知识片段正文常常不重复小节标题里的关键词
        （例如正文写「GB 1589-2016 为现行…」而标题是「车辆外廓尺寸标准的版本状态」），
        只用正文检索会让最相关的片段被泛泛而谈的片段压到后面。
        """
        query_terms = _tokenize(query)
        doc_terms = _tokenize(text)
        heading_terms = _tokenize(heading)
        # 标题词按两倍权重计入词频，保持 BM25 可解释性，不引入额外模型。
        doc_terms = doc_terms + heading_terms * 2
        if not query_terms or not doc_terms:
            return 0.0
        term_counts = {term: doc_terms.count(term) for term in set(doc_terms)}
        score = 0.0
        k1 = 1.5
        b = 0.75
        doc_len = len(doc_terms)
        total_docs = max(len(self.chunks), 1)
        for term in query_terms:
            tf = term_counts.get(term, 0)
            if tf == 0:
                continue
            df = self._doc_freq.get(term, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            denominator = tf + k1 * (1 - b + b * doc_len / max(self._avg_doc_len, 1))
            score += idf * (tf * (k1 + 1)) / denominator
        return score

    @staticmethod
    def _build_doc_frequency(chunks: list[KnowledgeChunk]) -> dict[str, int]:
        """统计每个 token 出现在多少 chunk 中，标题词与正文词同样计入文档频率。"""
        doc_freq: dict[str, int] = {}
        for chunk in chunks:
            for term in set(_tokenize(_chunk_scoring_text(chunk))):
                doc_freq[term] = doc_freq.get(term, 0) + 1
        return doc_freq


def rewrite_query(query: str, *, business_scope: str | None, intent: str) -> str:
    """规则化 query rewrite，补充业务范围词但保留客户当前诉求。"""
    scope_terms = {
        "logistics": "物流 配送 发货 签收",
        "refund": "退款 退货 到账 售后",
        "return_goods": "退货 售后 七天无理由",
        "exchange": "换货 更换 售后",
        "repair": "维修 报修 故障",
        "invoice": "发票 开票 抬头 税号",
        "member": "会员 权益 等级",
        "complaint": "投诉 举报 维权 人工处理",
        "compensation_dispute": "赔付 赔偿 争议 人工审核",
        "general": "",
    }
    # 货运专业知识域各自补充领域词，保证业务域过滤后域内 BM25 仍能区分具体规则。
    scope_terms.update(
        {
            "customs": "报关 清关 海关 单证 关税 HS编码 查验",
            "dangerous_goods": "危险品 危险货物 UN编号 包装等级 申报 锂电池 运输规则",
            "cold_chain": "冷链 冷藏 冷冻 温控 温度 断链 温区 记录",
            "vehicle_capacity": "零担 整车 计费重量 体积重量 载重 限重 车型 超限",
            "cargo_claims": "货损 理赔 索赔 保价 赔偿 限额 举证",
            "booking_documents": "订舱 提单 电放 舱单 截关 VGM 改单",
        }
    )
    # 退货规则咨询必须只补充退货相关词，避免把保修、维修、质保词带入召回。
    scope_terms.update(
        {
            "refund": "退款 到账 原路退回 审核通过",
            "return_goods": "退货规则 退货条件 七天无理由 签收后 不影响二次销售 退货申请",
        }
    )
    scope = business_scope or infer_business_scope(intent)
    extra = scope_terms.get(scope, "")
    return f"{query} {extra}".strip()


def _rerank_score(query: str, chunk: KnowledgeChunk, bm25_score: float, business_scope: str) -> float:
    """规则 rerank：综合 BM25、业务范围、标题命中、风险和来源权威性。"""
    score = bm25_score
    if chunk.business_scope == business_scope:
        score += 1.2
    # 标题命中按命中词数累计，避免只有一个泛化词命中就压过多个实词命中的片段。
    heading_text = " ".join(chunk.heading_path)
    heading_hits = sum(1 for term in set(_tokenize(query)) if len(term) >= 2 and term in heading_text)
    if heading_hits:
        score += 0.35 * min(heading_hits, 4)
    if chunk.risk_level in {"high", "critical"}:
        score -= 0.2
    if chunk.source_type == "official_policy":
        score += 0.3
    return score


def _chunk_scoring_text(chunk: KnowledgeChunk) -> str:
    """构造参与检索计分的文本：正文加标题路径，保证标题关键词可被命中。"""
    return f"{' '.join(chunk.heading_path)} {chunk.paragraph}".strip()


def is_customer_visible_chunk(paragraph: str, heading_path: list[str] | tuple[str, ...] | None = None) -> bool:
    """判断知识片段是否适合进入客户回复，过滤检索说明、示例表达和内部话术约束。"""
    text = f"{' '.join(heading_path or [])} {paragraph or ''}"
    blocked_terms = [
        "适用范围",
        "适合回答",
        "典型表达",
        "检索提示",
        "禁止话术",
        "可用标准话术",
        "标准回复要点",
        "本文档适用于",
        "本文档只说明",
        "AI 应",
        "AI 不得",
        "不得直接承诺",
    ]
    if any(term in text for term in blocked_terms):
        return False
    return bool((paragraph or "").strip())


def _to_citation(chunk: KnowledgeChunk, *, score: float, bm25_score: float, query: str, rewrite_mode: str = "rule_fallback") -> Citation:
    """把内部 chunk 转换为 Agent 使用的引用对象。"""
    return Citation(
        # 使用内容哈希生成稳定片段标识，模型和评测均只能引用本次实际召回的 ID。
        citation_id=_citation_id(chunk),
        doc_name=chunk.doc_name,
        version=chunk.version,
        paragraph=chunk.paragraph,
        score=score,
        collection=chunk.collection,
        business_scope=chunk.business_scope,
        heading_path=chunk.heading_path,
        risk_level=chunk.risk_level,
        answerable_intents=chunk.answerable_intents,
        retrieval_source="bm25_rerank",
        metadata={
            **chunk.metadata,
            "bm25_score": bm25_score,
            "rewritten_query": query,
            "query_rewrite_mode": rewrite_mode,
            "source_type": chunk.source_type,
            "chunk_index": chunk.chunk_index,
            "embedding_provider": chunk.embedding_provider,
            "embedding_model": chunk.embedding_model,
            "embedding_dimension": chunk.embedding_dimension,
            "embedding_distance": chunk.embedding_distance,
            "embedding_version": chunk.embedding_version,
        },
    )


def _citation_id(chunk: KnowledgeChunk) -> str:
    """生成跨请求稳定的知识片段标识，供回答引用和后置校验使用。"""
    source = "|".join([chunk.doc_name, chunk.version, str(chunk.chunk_index), chunk.paragraph])
    return f"kb-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:12]}"


def _load_default_chunks() -> list[KnowledgeChunk]:
    """加载知识库目录；目录缺失或为空时回退到内置示例知识。"""
    # 延迟导入避免 kb_loader 与本模块形成 import 环。
    from rag.kb_loader import load_kb_chunks

    chunks = load_kb_chunks()
    return chunks if chunks else _default_chunks()


def _default_chunks() -> list[KnowledgeChunk]:
    """构造带业务范围的示例知识，用于知识库目录不可用时的离线检索兜底。"""
    data: list[dict[str, Any]] = [
        {
            "doc_name": "Refund Arrival Policy",
            "collection": "refund_policy",
            "business_scope": "refund",
            "heading_path": ["售后政策", "退款到账"],
            "paragraph": "退款审核通过后通常 1-7 个工作日原路退回，具体到账时间以支付渠道处理为准。",
            "answerable_intents": ["refund", "consult", "other"],
            "risk_level": "medium",
        },
        {
            "doc_name": "Return Exchange Policy",
            "collection": "refund_policy",
            "business_scope": "return_goods",
            "metadata": {"category": "return_policy", "aliases": ["refund"]},
            "heading_path": ["售后政策", "退货条件"],
            "paragraph": "签收后 7 天内且商品不影响二次销售时，可申请退货；是否通过以售后审核结果为准。",
            "answerable_intents": ["refund", "consult", "other"],
            "risk_level": "medium",
        },
        {
            "doc_name": "Exchange Policy",
            "collection": "exchange_policy",
            "business_scope": "exchange",
            "heading_path": ["售后政策", "换货条件"],
            "paragraph": "商品存在质量问题、型号不符或配件缺失时，可提交换货申请，客服会结合订单状态和售后记录核实。",
            "answerable_intents": ["exchange", "consult", "other"],
            "risk_level": "medium",
        },
        {
            "doc_name": "Repair Policy",
            "collection": "repair_policy",
            "business_scope": "repair",
            "heading_path": ["维修政策", "处理周期"],
            "paragraph": "维修问题通常需要先建单核实故障现象，常规处理周期为 3-7 个工作日。",
            "answerable_intents": ["repair", "consult", "other"],
            "risk_level": "medium",
        },
        {
            "doc_name": "Logistics FAQ",
            "collection": "logistics_policy",
            "business_scope": "logistics",
            "heading_path": ["物流政策", "物流查询"],
            "paragraph": "订单发货后可通过订单号查询物流状态；未签收订单可优先核对配送进度。",
            "answerable_intents": ["logistics", "consult", "other"],
            "risk_level": "low",
        },
        {
            "doc_name": "Complaint Handling Script",
            "collection": "complaint_policy",
            "business_scope": "complaint",
            "heading_path": ["投诉处理", "人工审核"],
            "paragraph": "投诉、举报、赔付和强烈不满场景必须转人工处理，并保留完整会话记录。赔偿金额、处罚商家或法律结论需由人工专员在权限范围内确认。",
            "answerable_intents": ["complaint", "consult", "other"],
            "risk_level": "high",
        },
        {
            "doc_name": "Invoice FAQ",
            "collection": "invoice_policy",
            "business_scope": "invoice",
            "heading_path": ["发票政策", "开票信息"],
            "paragraph": "发票可在订单完成后申请开具；如需企业抬头，请提供准确抬头和税号。发票申请、修改或补开需要进入受控流程处理。",
            "answerable_intents": ["invoice", "consult", "other"],
            "risk_level": "low",
        },
        {
            "doc_name": "Member FAQ",
            "collection": "member_policy",
            "business_scope": "member",
            "heading_path": ["会员政策", "会员权益"],
            "paragraph": "会员权益包含专属客服、部分活动优先参与和售后进度提醒；具体权益以当前账号等级和活动规则为准。",
            "answerable_intents": ["member", "consult", "other"],
            "risk_level": "low",
        },
    ]
    return [
        KnowledgeChunk(
            version="V1.0",
            status="PUBLISHED",
            source_type="official_policy",
            chunk_index=index,
            **item,
        )
        for index, item in enumerate(data)
    ]


def _is_published_now(chunk: KnowledgeChunk) -> bool:
    """只允许已发布且未过期的 chunk 进入检索。"""
    now = datetime.utcnow()
    if chunk.status != "PUBLISHED":
        return False
    if chunk.effective_time and chunk.effective_time > now:
        return False
    if chunk.expire_time and chunk.expire_time <= now:
        return False
    return True


def _tokenize(text: str) -> list[str]:
    """中英文混合的轻量 token 化，作为 BM25 baseline。"""
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fa5]{2,}", lowered)
    chinese_chars = re.findall(r"[\u4e00-\u9fa5]", lowered)
    return words + chinese_chars


def _normalize_score(score: float) -> float:
    """把 rerank 分数归一化为 0-1 相关性分，避免暴露原始 BM25 含义。"""
    return round(score / (score + 3.0), 4) if score > 0 else 0.0
