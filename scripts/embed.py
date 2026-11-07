#!/usr/bin/env python3
"""CLI de backfill de embeddings (bge-m3)."""

from __future__ import annotations

import asyncio
import sys

from rig.retrieval.embed import main


async def _run() -> int:
    stats = await main()
    print(
        f"embed: total={stats.total} embedded={stats.embedded} "
        f"failed={stats.failed} duration={stats.duration_s:.2f}s "
        f"throughput={stats.throughput:.2f} chunks/s"
    )
    for err in stats.errors[:10]:
        print(f"embed: error: {err}", file=sys.stderr)
    return 1 if stats.failed > 0 else 0


def main_sync() -> None:
    code = asyncio.run(_run())
    raise SystemExit(code)


if __name__ == "__main__":
    main_sync()
