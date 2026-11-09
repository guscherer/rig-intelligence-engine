#!/usr/bin/env python3
"""CLI do grafo RIG — ``make run --id <doc_id>``.

Monta o ``RIGState`` (``BudgetState`` de US$ 0,20 / 90 s), executa
``triage -> retrieve -> positioning -> draft`` e grava a minuta + ``run.json``
em ``reports/<run_id>/``. A saída stdout é o ``run.json`` (evidência de custo).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from rig.adapters import DeepSeekGenerator
from rig.core.config import get_settings
from rig.core.db import close_pool, get_pool
from rig.graph.runner import run_pipeline
from rig.retrieval.fetch import fetch_doc_chunks, fetch_document


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Executa o grafo RIG e emite a minuta")
    parser.add_argument("--id", dest="doc_id", required=True, help="doc_id da proposição")
    parser.add_argument("--chunk-limit", type=int, default=10, help="máx. de chunks na minuta")
    parser.add_argument("--reports-dir", default="reports", help="diretório de saída")
    return parser


async def _run(doc_id: str, chunk_limit: int, reports_dir: str) -> dict[str, object]:
    settings = get_settings()
    generator = DeepSeekGenerator(
        api_key=settings.deepseek_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.model_draft,
    )
    pool = await get_pool()
    try:
        outcome = await run_pipeline(
            doc_id=doc_id,
            generator=generator,
            load_document=lambda did: fetch_document(pool, did),
            load_chunks=lambda did: fetch_doc_chunks(pool, did, limit=chunk_limit),
            settings=settings,
            reports_dir=Path(reports_dir),
        )
    finally:
        await generator.aclose()
        await close_pool()
    return outcome.report.model_dump()


def main() -> None:
    args = _build_parser().parse_args()
    report = asyncio.run(_run(args.doc_id, args.chunk_limit, args.reports_dir))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
