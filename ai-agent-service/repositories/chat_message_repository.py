"""会话消息仓储：消息落库、历史查询与会话内消息拼装。

从 chat_repository 中拆出，使会话与消息两个聚合各自独立成文件。
"""

import json
from datetime import datetime
from typing import Any

from repositories.base import BaseRepository
from repositories.chat_repository import ChatSessionRepository, customer_reference_payloads


class ChatMessageRepository(BaseRepository):
    """消息仓储，负责保存用户消息、AI 回复以及按会话查询历史。"""

    def __init__(self, session_repository: ChatSessionRepository) -> None:
        """复用会话仓储的数据库路径，保证会话和消息写入同一个 SQLite 文件。"""
        self.session_repository = session_repository
        self.db_path = session_repository.db_path
        self.database = session_repository.database

    def save(
        self,
        session_no: str,
        sender_type: str,
        content: str,
        message_type: str = "text",
        sender_id: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """保存会话消息，支持用户原文、AI 回复和后续系统消息。"""
        session = self.session_repository.get_by_session_no(session_no)
        if not session:
            raise ValueError(f"会话不存在: {session_no}")

        now = datetime.utcnow().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chat_message (
                    session_id, sender_type, sender_id, content,
                    message_type, extra_data, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["id"],
                    sender_type,
                    sender_id,
                    content,
                    message_type,
                    json.dumps(extra_data or {}, ensure_ascii=False, default=str),
                    now,
                ),
            )
            conn.execute(
                "UPDATE chat_session SET updated_at = ? WHERE id = ?",
                (now, session["id"]),
            )
            message_id = cursor.lastrowid
        return {
            "id": message_id,
            "session_id": session_no,
            "sender_type": sender_type,
            "sender_id": sender_id,
            "content": content,
            "message_type": message_type,
            "extra_data": extra_data or {},
            "created_at": now,
        }

    def list_by_session(self, session_no: str, after_message_id: int = 0) -> list[dict[str, Any]]:
        """按会话编号查询消息历史，内部流程使用；对外接口应先校验会话归属。"""
        session = self.session_repository.get_by_session_no(session_no)
        if not session:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, sender_type, sender_id, content, message_type, extra_data, created_at
                FROM chat_message
                WHERE session_id = ? AND id > ?
                ORDER BY id ASC
                """,
                (session["id"], max(0, after_message_id)),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": session_no,
                "sender_type": row["sender_type"],
                "sender_id": row["sender_id"],
                "content": row["content"],
                "message_type": row["message_type"],
                "extra_data": self._load_extra(row["extra_data"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_recent_by_session(self, session_no: str, limit: int = 12) -> list[dict[str, Any]]:
        """读取会话最近消息窗口，供人工接管默认交接使用，避免默认暴露完整历史。"""
        session = self.session_repository.get_by_session_no(session_no)
        if not session:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, sender_type, sender_id, content, message_type, extra_data, created_at
                FROM chat_message
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session["id"], max(1, limit)),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": session_no,
                "sender_type": row["sender_type"],
                "sender_id": row["sender_id"],
                "content": row["content"],
                "message_type": row["message_type"],
                "extra_data": self._load_extra(row["extra_data"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def list_before_message_id(self, session_no: str, before_message_id: int, limit: int = 30) -> list[dict[str, Any]]:
        """按游标读取更早历史；仅由已授权的人工历史展开接口调用。"""
        session = self.session_repository.get_by_session_no(session_no)
        if not session or before_message_id <= 0:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, sender_type, sender_id, content, message_type, extra_data, created_at
                FROM chat_message
                WHERE session_id = ? AND id < ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session["id"], before_message_id, max(1, limit)),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "session_id": session_no,
                "sender_type": row["sender_type"],
                "sender_id": row["sender_id"],
                "content": row["content"],
                "message_type": row["message_type"],
                "extra_data": self._load_extra(row["extra_data"]),
                "created_at": row["created_at"],
            }
            for row in reversed(rows)
        ]

    def has_message_before(self, session_no: str, message_id: int) -> bool:
        """判断当前消息窗口之前是否仍有历史，用于控制座席端“展开历史”入口。"""
        session = self.session_repository.get_by_session_no(session_no)
        if not session or message_id <= 0:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM chat_message WHERE session_id = ? AND id < ? LIMIT 1",
                (session["id"], message_id),
            ).fetchone()
        return row is not None

    def latest_message_id(self, session_no: str) -> int:
        """返回会话最新消息主键，用于坐席判断是否存在未同步的新消息。"""
        session = self.session_repository.get_by_session_no(session_no)
        if not session:
            return 0
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(id) AS latest_id FROM chat_message WHERE session_id = ?", (session["id"],)).fetchone()
        return int(row["latest_id"] or 0) if row else 0

    def latest_message_meta(self, session_no: str) -> dict[str, Any] | None:
        """返回会话最新消息的发送方与时间，供坐席工作台按活跃度排序和未读提示。"""
        session = self.session_repository.get_by_session_no(session_no)
        if not session:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, sender_type, created_at FROM chat_message WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (session["id"],),
            ).fetchone()
        if not row:
            return None
        return {"id": int(row["id"]), "sender_type": str(row["sender_type"]), "created_at": str(row["created_at"])}

    def list_by_session_for_customer(self, session_no: str, customer_id: int, after_message_id: int = 0) -> list[dict[str, Any]]:
        """按客户身份查询安全消息，剔除内部分析、工具结果和不可见系统事件。"""
        session = self.session_repository.get_by_session_no_for_customer(session_no, customer_id)
        if not session:
            return []
        safe_messages = []
        for message in self.list_by_session(session_no, after_message_id):
            extra = message.get("extra_data") or {}
            if message.get("sender_type") == "system" and not extra.get("customer_visible"):
                continue
            message["extra_data"] = {
                key: extra[key]
                for key in ("route_target", "message_source", "customer_visible", "attachment")
                if key in extra
            }
            # 客户可见消息附带安全文献列表，供前端渲染 [n] 索引与参考文献面板。
            if "citations" in extra:
                message["extra_data"]["citations"] = customer_reference_payloads(extra["citations"])
            # 客户侧不需要坐席内部标识，仅保留可见角色和正文。
            if message.get("sender_type") in {"staff", "system"}:
                message["sender_id"] = None
            safe_messages.append(message)
        return safe_messages

    def find_ticket_context(self, ticket_no: str) -> dict[str, Any] | None:
        """兼容旧工单：根据 AI 消息扩展字段中的工单号定位客户会话。"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    m.id AS message_id,
                    m.sender_type,
                    m.sender_id,
                    m.content,
                    m.message_type,
                    m.extra_data,
                    m.created_at AS message_created_at,
                    s.id AS session_db_id,
                    s.session_no,
                    s.customer_id,
                    s.status,
                    s.title,
                    s.intent,
                    s.emotion,
                    s.priority,
                    s.ai_summary,
                    s.created_at AS session_created_at,
                    s.updated_at AS session_updated_at
                FROM chat_message m
                JOIN chat_session s ON s.id = m.session_id
                WHERE m.extra_data IS NOT NULL
                ORDER BY m.id DESC
                """
            ).fetchall()

        for row in rows:
            extra_data = self._load_extra(row["extra_data"])
            ticket_result = extra_data.get("ticket_result") or {}
            ticket_data = ticket_result.get("data") or {}
            if ticket_data.get("ticketNo") != ticket_no:
                continue
            # 旧数据没有 externalSessionNo，仍可通过 AI 回复扩展字段定位会话。
            return {
                "session": {
                    "id": row["session_db_id"],
                    "session_id": row["session_no"],
                    "customer_id": row["customer_id"],
                    "status": row["status"],
                    "title": row["title"],
                    "intent": row["intent"],
                    "emotion": row["emotion"],
                    "priority": row["priority"],
                    "ai_summary": row["ai_summary"],
                    "created_at": row["session_created_at"],
                    "updated_at": row["session_updated_at"],
                },
                "message": {
                    "id": row["message_id"],
                    "session_id": row["session_no"],
                    "sender_type": row["sender_type"],
                    "sender_id": row["sender_id"],
                    "content": row["content"],
                    "message_type": row["message_type"],
                    "extra_data": extra_data,
                    "created_at": row["message_created_at"],
                },
                "ticket_result": ticket_result,
            }
        return None

    def _load_extra(self, value: str | None) -> dict[str, Any]:
        """还原消息扩展 JSON，解析失败时返回空对象避免接口异常。"""
        if not value:
            return {}
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {"value": data}
        except json.JSONDecodeError:
            return {}
