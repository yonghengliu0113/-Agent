"""知识库文档加载器：把 data/kb_sources 下的 Markdown 文档转换成可检索 chunk。

在线 Agent（内存 BM25 后端）、离线评测和 pgvector 入库都需要读同一份知识库目录，
因此这里集中维护目录到业务范围、集合和风险等级的映射，避免三处各写一套配置后产生召回漂移。
"""

from pathlib import Path
from typing import Any

from rag.document_loader import DocumentLoader
from rag.text_processing import KnowledgeChunk, split_into_chunks

# 知识库目录名到检索元数据的映射；目录名即业务范围（business_scope）。
SCOPE_CONFIG: dict[str, dict[str, Any]] = {
    "refund": {
        "collection": "refund_policy",
        "business_scope": "refund",
        "risk_level": "medium",
        "answerable_intents": ["refund", "consult", "other"],
    },
    "exchange": {
        "collection": "exchange_policy",
        "business_scope": "exchange",
        "risk_level": "medium",
        "answerable_intents": ["exchange", "consult", "other"],
    },
    "logistics": {
        "collection": "logistics_policy",
        "business_scope": "logistics",
        "risk_level": "low",
        "answerable_intents": ["logistics", "consult", "other"],
    },
    "invoice": {
        "collection": "invoice_policy",
        "business_scope": "invoice",
        "risk_level": "low",
        "answerable_intents": ["invoice", "consult", "other"],
    },
    "repair": {
        "collection": "repair_policy",
        "business_scope": "repair",
        "risk_level": "medium",
        "answerable_intents": ["repair", "consult", "other"],
    },
    "member": {
        "collection": "member_policy",
        "business_scope": "member",
        "risk_level": "low",
        "answerable_intents": ["member", "consult", "other"],
    },
    "complaint": {
        "collection": "complaint_policy",
        "business_scope": "complaint",
        "risk_level": "high",
        "answerable_intents": ["complaint", "consult", "other"],
    },
    "general": {
        "collection": "general_faq",
        "business_scope": "general",
        "risk_level": "low",
        "answerable_intents": ["consult", "other"],
    },
    # 货运行业知识域：各域独立成 scope，避免通用物流文档与专业规则互相抢占召回排名。
    # 报关清关合规涉及关税与单证责任，风险等级高于普通时效咨询。
    "customs": {
        "collection": "customs_policy",
        "business_scope": "customs",
        "risk_level": "medium",
        "answerable_intents": ["logistics", "consult", "other"],
    },
    # 危险品运输涉及法规责任与航空安全，风险等级设为 high。
    "dangerous_goods": {
        "collection": "dangerous_goods_policy",
        "business_scope": "dangerous_goods",
        "risk_level": "high",
        "answerable_intents": ["logistics", "consult", "other"],
    },
    "cold_chain": {
        "collection": "cold_chain_policy",
        "business_scope": "cold_chain",
        "risk_level": "medium",
        "answerable_intents": ["logistics", "consult", "other"],
    },
    "vehicle_capacity": {
        "collection": "vehicle_capacity_policy",
        "business_scope": "vehicle_capacity",
        "risk_level": "low",
        "answerable_intents": ["logistics", "consult", "other"],
    },
    # 货损理赔涉及赔偿金额认定，属于高风险场景，客户侧不得直接承诺赔付结论。
    "cargo_claims": {
        "collection": "cargo_claims_policy",
        "business_scope": "cargo_claims",
        "risk_level": "high",
        "answerable_intents": ["logistics", "consult", "other"],
    },
    "booking_documents": {
        "collection": "booking_documents_policy",
        "business_scope": "booking_documents",
        "risk_level": "medium",
        "answerable_intents": ["logistics", "consult", "other"],
    },
}

# 同一目录下可能包含多个细分业务文档，不能只按目录名赋予 metadata。
# 退货条件与退款到账同属 refund_policy 集合，但分别服务退货规则和退款进度检索。
DOCUMENT_CONFIG_OVERRIDES: dict[str, dict[str, Any]] = {
    "return_goods_policy": {
        "collection": "refund_policy",
        "business_scope": "return_goods",
        "risk_level": "medium",
        "answerable_intents": ["refund", "consult", "other"],
        # 保留与退款大类的关联，供“售后/退款”这类宽泛问法兜底召回。
        "metadata": {"aliases": ["refund"]},
    },
    # 零担整车计价文档虽然放在 logistics 目录，但业务域是「车辆与载重」，
    # 独立成域后不会与通用物流查询文档互相抢占召回排名。
    "ltl_ftl_policy": {
        "collection": "vehicle_capacity_policy",
        "business_scope": "vehicle_capacity",
        "risk_level": "low",
        "answerable_intents": ["logistics", "consult", "other"],
    },
}

# 默认知识库目录：ai-agent-service/data/kb_sources
DEFAULT_KB_DIR = Path(__file__).resolve().parent.parent / "data" / "kb_sources"


def load_kb_chunks(kb_dir: str | Path | None = None) -> list[KnowledgeChunk]:
    """从知识库目录加载 Markdown 文档并生成带 metadata 的检索 chunk。

    目录不存在或没有可加载文档时返回空列表，由调用方决定回退策略，
    避免把「知识库为空」静默伪装成「加载成功但检索不到」。
    """
    root = Path(kb_dir) if kb_dir is not None else DEFAULT_KB_DIR
    if not root.is_dir():
        return []
    loader = DocumentLoader()
    chunks: list[KnowledgeChunk] = []
    for scope_dir in sorted(item for item in root.iterdir() if item.is_dir()):
        config = SCOPE_CONFIG.get(scope_dir.name)
        if not config:
            # 未登记的目录不参与检索，避免无 metadata 的文档绕过业务范围过滤。
            continue
        for file_path in sorted(scope_dir.rglob("*")):
            if file_path.suffix.lower() not in {".md", ".txt"}:
                continue
            # 目录配置提供默认值，文档级覆盖解决同一集合内的细分业务范围。
            document_config = {**config, **DOCUMENT_CONFIG_OVERRIDES.get(file_path.stem, {})}
            text = loader.load_text(str(file_path))
            document_chunks = split_into_chunks(
                text,
                doc_name=file_path.stem,
                version="V1.0",
                collection=document_config["collection"],
                business_scope=document_config["business_scope"],
                risk_level=document_config["risk_level"],
                answerable_intents=document_config["answerable_intents"],
                source_type="official_policy",
            )
            # aliases 等非结构化 metadata 也要随 chunk 写入，保证 memory/pgvector 行为一致。
            for chunk in document_chunks:
                chunk.metadata = dict(document_config.get("metadata", {}))
            chunks.extend(document_chunks)
    return chunks
