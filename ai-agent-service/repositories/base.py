"""仓储基类：把每个 Repository 各写一遍的连接、建表时机与字段补齐收敛到一处。

改造前实测：`def _connect` 出现 7 次、`def _init_tables` 出现 4 次、
`def _ensure_column` 出现 2 次，且各自的建库路径/环境变量写法几乎完全相同。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from repositories.database import DatabaseAdapter, DatabaseConfig


class BaseRepository:
    """所有仓储的公共基类。

    子类通过类属性声明自己的库文件与环境变量，只需实现 `_init_tables`（建表 DDL）。
    统一保证：数据目录存在、非 PostgreSQL 时自动建表、每次操作使用独立连接。
    """

    #: 数据库文件路径环境变量名；为空则只使用默认路径
    env_var: str = ""
    #: 默认数据库文件名（位于 ai-agent-service/data/ 下）
    default_db_name: str = "customer_agent.db"

    def __init__(self, db_path: str | None = None, database: DatabaseAdapter | None = None) -> None:
        """解析数据库路径并确保表结构就绪。"""
        default_path = Path(__file__).resolve().parents[1] / "data" / self.default_db_name
        if db_path is not None:
            resolved: str | Path = db_path
        elif self.env_var:
            resolved = os.getenv(self.env_var, str(default_path))
        else:
            resolved = default_path
        self.db_path = Path(resolved)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.database = database or DatabaseAdapter(DatabaseConfig.from_env(self.db_path))
        # PostgreSQL 由迁移脚本负责建表，SQLite 才会在启动时补齐 DDL
        if not self.database.is_postgres:
            self._init_tables()

    def _connect(self) -> Any:
        """每次数据库操作使用独立连接，避免多请求共享连接带来的线程与锁问题。"""
        return self.database.connection()

    def _init_tables(self) -> None:
        """建表入口，由子类实现具体 DDL。"""
        raise NotImplementedError(f"{type(self).__name__} 必须实现 _init_tables()")

    def _ensure_column(self, conn: Any, table_name: str, column_name: str, column_type: str) -> None:
        """为历史 SQLite 库补齐新增字段，避免旧数据导致启动失败。"""
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        if any(row["name"] == column_name for row in rows):
            return
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
