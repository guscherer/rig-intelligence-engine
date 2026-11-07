#!/usr/bin/env python3
"""CLI de busca híbrida (make search)."""

from __future__ import annotations

import argparse
import asyncio
import sys

from rig.retrieval.search import SearchFilters, run_search


def main_sync() -> None:
    parser = argparse.ArgumentParser(description="Busca híbrida RIG")
    parser.add_argument("query", nargs="*")
    parser.add_argument("--mode", default="rrf+rerank")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--kind", default=None)
    parser.add_argument("--source", default=None)
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--sigla-tipo", default=None)
    parser.add_argument("--ano", type=int, default=None)
    parser.add_argument("--tema", default=None)
    parser.add_argument("--no-rerank", action="store_true", default=False)
    args = parser.parse_args()

    query = " ".join(args.query).strip()
    if not query:
        print('informe a consulta: make search "..."', file=sys.stderr)
        raise SystemExit(2)

    filt = SearchFilters(
        kind=args.kind,
        source=args.source,
        doc_id=args.doc_id,
        sigla_tipo=args.sigla_tipo,
        ano=args.ano,
        tema=args.tema,
    )
    mode = args.mode
    if args.no_rerank and mode in {"rrf+rerank", "rerank"}:
        mode = "rrf"

    results = asyncio.run(
        run_search(query, mode=mode, filters=filt, limit=args.limit, candidate_k=args.candidate_k)
    )
    for r in results:
        print(f"{r.doc_id}\t{r.breadcrumb}\tpage={r.page}\tscore={r.score:.4f}")


if __name__ == "__main__":
    main_sync()
