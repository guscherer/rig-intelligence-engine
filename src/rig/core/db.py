"""Acesso ao banco Postgres (asyncpg), sem ORM."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]


def database_url() -> str:
    """URL de conexão, normalizando o sufixo ``+asyncpg`` do SQLAlchemy."""
    url = os.environ.get("DATABASE_URL", "postgresql://rig:rig@localhost:5432/rig")
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.split("+")[0] + "://", 1)
    return url


_state: dict[str, Any] = {"pool": None}


async def get_pool() -> asyncpg.Pool:
    """Retorna (criando se necessário) o pool global de conexões."""
    if _state["pool"] is None:
        _state["pool"] = await asyncpg.create_pool(database_url(), min_size=1, max_size=10)
    pool: asyncpg.Pool = _state["pool"]
    return pool


async def close_pool() -> None:
    """Fecha o pool global, se existir."""
    pool = _state["pool"]
    if pool is not None:
        await pool.close()
        _state["pool"] = None


async def execute_sql_file(pool: Any, path: str) -> None:
    """Executa um arquivo .sql (útil para testes de migração)."""
    sql = await asyncio.to_thread(Path(path).read_text, encoding="utf-8")
    async with pool.acquire() as conn:
        await conn.execute(sql)
