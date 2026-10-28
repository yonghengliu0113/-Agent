"""货运智能体 Agent 服务包。

对外暴露 FastAPI 实例，使 ``uvicorn app:app`` 与测试中的 ``app.app`` 保持可用，
内部实现已按 app/api、app/core、app/deps 分层。
"""
from app.main import app as app

__all__ = ["app"]
