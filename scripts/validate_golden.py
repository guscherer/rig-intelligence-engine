"""Valida os chunk_ouro do golden set de retrieval contra o banco.

Uso:
    uv run python scripts/validate_golden.py
    uv run python scripts/validate_golden.py --yaml eval/golden/retrieval_v1.yaml

Sai com codigo 0 se todos os chunk_id existirem no banco e baterem com doc_id;
codigo 1 caso contrario. Roda no CI (com Postgres disponivel).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg
import yaml


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://rig:rig@localhost:5432/rig")
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.split("+")[0] + "://", 1)
    return url


async def _validate(data: dict) -> int:

    items = data.get("items", [])
    if not items:
        print("ERRO: nenhum item no golden set")
        return 1

    try:
        pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=5)
    except Exception as exc:
        print(f"Postgres indisponivel: {exc}")
        return 2

    failures: list[str] = []
    async with pool.acquire() as conn:
        for item in items:
            cid = item["chunk_ouro"]
            did = str(item["doc_id"])
            row = await conn.fetchrow(
                "SELECT doc_id, chunk_text FROM chunks WHERE chunk_id = $1", cid
            )
            if row is None:
                failures.append(f"{cid}: chunk_id nao existe no banco")
                continue
            if str(row["doc_id"]) != did:
                failures.append(f"{cid}: doc_id divergente (yaml={did}, db={row['doc_id']})")
            if not (row["chunk_text"] or "").strip():
                failures.append(f"{cid}: chunk_text vazio")

    await pool.close()

    total = len(items)
    ok = total - len(failures)
    print(f"validados: {ok}/{total}")
    if failures:
        for msg in failures:
            print("FALHA:", msg)
        return 1
    print("OK: todos os chunk_ouro existem no banco.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yaml", default="eval/golden/retrieval_v1.yaml")
    args = parser.parse_args()
    with open(args.yaml, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return asyncio.run(_validate(data))


if __name__ == "__main__":
    sys.exit(main())
