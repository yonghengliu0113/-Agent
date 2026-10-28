"""验证客户侧安全引用转换:剔除内部字段、保留客户可读文献字段与序号。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repositories.chat_repository import customer_reference_payloads


def test_customer_reference_payloads_keep_safe_fields_only():
    """转换后的文献条目只包含客户可读字段，不含检索评分与内部元数据。"""
    payloads = customer_reference_payloads([
        {
            "citation_id": "kb-abc123",
            "doc_name": "Refund Arrival Policy",
            "paragraph": "退款审核通过后通常 1-7 个工作日原路退回。",
            "score": 0.92,
            "collection": "refund_policy",
            "risk_level": "medium",
            "heading_path": ["售后政策", "退款到账"],
            "metadata": {"authors": ["客服制度组"], "year": "2026", "bm25_score": 12.3},
        },
        {"citation_id": "kb-def456", "doc_name": "Complaint Policy", "paragraph": "投诉场景必须转人工。", "score": 0.8, "risk_level": "high", "heading_path": []},
    ])
    assert len(payloads) == 2
    first = payloads[0]
    assert first["id"] == "kb-abc123"
    assert first["index"] == 1
    assert first["title"] == "售后政策 / 退款到账"
    assert first["source"] == "Refund Arrival Policy"
    assert first["snippet"] == "退款审核通过后通常 1-7 个工作日原路退回。"
    assert first["content"] == first["snippet"]
    assert first["authors"] == ["客服制度组"]
    assert first["year"] == "2026"
    assert "score" not in first
    assert "metadata" not in first
    assert "bm25_score" not in first
    second = payloads[1]
    assert second["index"] == 2
    assert second["title"] == "Complaint Policy"
    assert second["risk_level"] == "high"


def test_customer_reference_payloads_tolerate_missing_and_garbage():
    """空值与非字典项不应导致转换失败。"""
    assert customer_reference_payloads(None) == []
    assert customer_reference_payloads([]) == []
    assert customer_reference_payloads([None, "bad", {"doc_name": "X", "paragraph": "p"}])[0]["title"] == "X"
