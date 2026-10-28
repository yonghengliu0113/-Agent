"""验证多轮对话上下文指代识别：裸“那/这/这样”开头的追问应注入历史上下文。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.customer_service_agent import CustomerServiceAgent


def _agent() -> CustomerServiceAgent:
    """绕过 LLM 初始化直接构造实例，_has_context_reference 不依赖模型。"""
    return CustomerServiceAgent.__new__(CustomerServiceAgent)


def test_explicit_reference_words_are_detected() -> None:
    """显式指代词必须命中。"""
    agent = _agent()
    for message in ["我刚才说的那批货", "上面提到的那个", "还是走专线吧", "它多少钱"]:
        assert agent._has_context_reference(message), message


def test_bare_followup_prefixes_are_detected() -> None:
    """“那/这/这样”开头的承接追问必须命中，避免 AI 说一句忘一句。"""
    agent = _agent()
    for message in ["那走哪个产品比较合适?", "那大概要多少钱呢", "这个怎么收费?", "这样的话能便宜点吗"]:
        assert agent._has_context_reference(message), message


def test_unrelated_questions_are_not_forced_into_context() -> None:
    """与历史无关的完整提问不应强行注入上下文。"""
    agent = _agent()
    for message in ["今天天气怎么样", "我想咨询会员权益有哪些"]:
        assert not agent._has_context_reference(message), message

def test_dialogue_digest_is_always_injected_for_normal_chat() -> None:
    """正常聊天(无显式指代)也应携带最近对话摘要，保证话题连续性。"""
    agent = _agent()
    payload = agent._message_for_intent_analysis(
        "大概要多少钱?",
        {
            "safe_context_summary": "",
            "structured_memory": {},
            "session_memory": {
                "recent_user_messages": [
                    {"message_id": 1, "content": "我有一批 2 吨的货要从杭州发到上海"},
                    {"message_id": 3, "content": "大概要多少钱?"},
                ],
                "recent_ai_messages": [
                    {"message_id": 2, "content": "杭州到上海约 180 公里，2 吨货通常走整车公路运输。"},
                ],
            },
        },
    )
    assert "最近对话" in payload
    assert "杭州到上海" in payload
    assert "2 吨" in payload
    assert payload.endswith("本轮用户消息：大概要多少钱?")

def test_dialogue_digest_interleaves_by_message_order() -> None:
    """对话摘要按消息主键排序，客户与客服消息交错呈现。"""
    agent = _agent()
    digest = agent._compact_dialogue_digest({
        "recent_user_messages": [{"message_id": 10, "content": "客户后句"}],
        "recent_ai_messages": [{"message_id": 9, "content": "客服前句"}],
    })
    assert digest == "客服：客服前句 / 客户：客户后句"

