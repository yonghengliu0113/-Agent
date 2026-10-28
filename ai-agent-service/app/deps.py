"""进程级单例装配：仓储、服务、工具与韧性客户端集中在此构建一次。

所有使用方都按模块属性访问（deps.chat_messages），不要按值 import，
否则测试中的 monkeypatch 无法生效。
"""
from agents.customer_service_agent import CustomerServiceAgent
from repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
from repositories.evaluation_repository import EvaluationRepository
from repositories.staff_handoff_audit_repository import StaffHandoffAuditRepository
from services.agent_execution_queue import AgentExecutionQueue
from services.agent_execution_service import AgentExecutionService
from services.auth_identity_cache import AuthIdentityCache
from services.resilient_client import ResilientClient
from services.staff_presence_service import StaffPresenceService
from services.staff_reply_draft_service import StaffReplyDraftService
from services.stream_event_service import StreamEventService
from tools.order_tools import OrderTools
from tools.ticket_tools import TicketTools

agent = CustomerServiceAgent()

order_tools = OrderTools()

ticket_tools = TicketTools()

chat_sessions = ChatSessionRepository()

chat_messages = ChatMessageRepository(chat_sessions)

evaluation_repository = EvaluationRepository()

staff_presence = StaffPresenceService()

staff_handoff_audit = StaffHandoffAuditRepository(chat_sessions)

staff_reply_draft_service = StaffReplyDraftService()

agent_execution_service = AgentExecutionService(
    agent=agent,
    chat_sessions=chat_sessions,
    chat_messages=chat_messages,
    evaluation_repository=evaluation_repository,
    staff_presence_checker=staff_presence.is_online,
)

agent_execution_queue = AgentExecutionQueue()

stream_event_service = StreamEventService()

business_client = ResilientClient(downstream="java_business")

identity_cache = AuthIdentityCache()

followup_notifications = agent_execution_service.followup_notifications
