"""PostgreSQL 连接工厂：集中 psycopg 延迟导入，避免 memory 后端被迫安装数据库驱动。

改造前 `_connect` 在 pg_ingest / pg_schema / pg_vector_store 各写了一遍，
唯一差异是 ImportError 时抛出的异常类型与文案，这里通过参数保留各自原有行为。
"""

from __future__ import annotations

from typing import Any

from rag.pg_config import RagConfigError


def connect_pg(
    database_url: str,
    *,
    error: type[Exception] = RagConfigError,
    message: str = "psycopg is required for pgvector backend",
) -> Any:
    """建立 psycopg 连接；驱动缺失时抛出调用方约定的异常类型。"""
    try:
        import psycopg
    except ImportError as exc:
        raise error(message) from exc
    return psycopg.connect(database_url)
