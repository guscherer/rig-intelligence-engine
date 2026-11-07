#!/usr/bin/env python3
"""Ingestao real do corpus da Camara em Postgres.

Encadeia ``listar_proposicoes -> detalhar -> inteiro_teor -> extract_pdf ->
chunk_document -> store``. Respeita ``INGEST_ANOS`` / ``INGEST_TIPOS`` /
``CAMARA_RPS`` do ambiente e persiste cursor incremental em ``ingest_cursor``.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg  # type: ignore[import-untyped]

from rig.core.db import close_pool, get_pool
from rig.ingestion.camara import CamaraClient, Proposition
from rig.ingestion.chunker import chunk_document
from rig.ingestion.pdf import extract_pdf
from rig.ingestion.store import (
    IngestCounters,
    _doc_content_hash,
    get_cursor,
    record_ingest_run,
    update_cursor,
    upsert,
)

SOURCE = "camara"


@dataclass
class IngestStats:
    """Contadores acumulados de uma execucao."""

    fetched: int = 0
    new: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    chunks: int = 0
    pages: int = 0
    low_quality: int = 0
    documents: list[dict[str, Any]] = field(default_factory=list)


class _CountingClient(CamaraClient):
    """CamaraClient que conta retries (via backoff)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.retries = 0

    async def _sleep_backoff(self, attempt: int, retry_after: str | None) -> None:
        self.retries += 1
        await super()._sleep_backoff(attempt, retry_after)


def _env_list(key: str, default: str) -> list[str]:
    raw = os.environ.get(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _env_ints(key: str, default: str) -> list[int]:
    return [int(x) for x in _env_list(key, default)]


def _situacao(prop: Proposition) -> str | None:
    sp = prop.status_proposicao
    if isinstance(sp, dict):
        return sp.get("descricaoSituacao") or sp.get("siglaSituacao")
    if sp is None:
        return None
    return str(sp)


def _doc_meta(
    prop: Proposition,
    extracted_quality: str,
    url: str,
    ano: int,
    tipo: str = "",
    page_count: int | None = None,
) -> dict[str, Any]:
    return {
        "doc_id": str(prop.id),
        "source": SOURCE,
        "doc_type": "proposicao",
        "sigla_tipo": prop.sigla_tipo or tipo,
        "numero": prop.numero,
        "ano": prop.ano or ano,
        "ementa": prop.ementa,
        "keywords": prop.keywords,
        "situacao": _situacao(prop),
        "url_inteiro_teor": url,
        "data_apresentacao": prop.data_apresentacao,
        "extraction_quality": extracted_quality,
        "page_count": page_count,
    }


def _manifest_entry(
    prop: Proposition, extracted: Any, chunks: list[Any], url: str, ano: int
) -> dict[str, Any]:
    return {
        "source": SOURCE,
        "doc_id": str(prop.id),
        "title": f"{prop.sigla_tipo or ''} {prop.numero}/{prop.ano or ano}".strip(),
        "sigla_tipo": prop.sigla_tipo,
        "numero": prop.numero,
        "ano": prop.ano or ano,
        "ementa": prop.ementa,
        "keywords": prop.keywords,
        "url_inteiro_teor": url,
        "data_apresentacao": prop.data_apresentacao,
        "page_count": extracted.page_count,
        "char_count": len(extracted.text),
        "extraction_quality": extracted.quality,
        "chunks": len(chunks),
        "content_hash": _doc_content_hash(chunks, None),
        "chunk_content_hashes": [c.content_hash for c in chunks],
    }


async def process_proposition(
    client: CamaraClient,
    pool: asyncpg.Pool,
    prop_summary: dict[str, Any],
    *,
    ano: int,
    tipo: str,
    source: str = SOURCE,
) -> dict[str, Any]:
    """Processa uma proposicao. Retorna dict com status/chunks/pages/quality."""
    result: dict[str, Any] = {
        "doc_id": str(prop_summary.get("id")),
        "status": "failed",
        "chunks": 0,
        "pages": 0,
        "quality": None,
        "manifest": None,
    }
    pid_raw = prop_summary.get("id")
    try:
        pid = int(str(pid_raw))
    except (TypeError, ValueError):
        return result
    result["doc_id"] = str(pid)

    try:
        prop = await client.detalhar(pid)
    except Exception:
        result["status"] = "failed_detail"
        return result

    url = prop.url_inteiro_teor
    if not url:
        result["status"] = "skipped_no_pdf"
        return result

    try:
        pdf_bytes = await client.inteiro_teor(url)
    except Exception:
        result["status"] = "failed_download"
        return result

    try:
        extracted = extract_pdf(pdf_bytes)
        doc_meta = _doc_meta(prop, extracted.quality, url, ano, tipo, extracted.page_count)
        chunks = chunk_document(extracted.text, doc_meta)

        counters = await upsert(
            pool,
            source=source,
            doc_id=str(prop.id),
            chunks=chunks,
            doc_type="proposicao",
            doc_meta=doc_meta,
        )
        if counters.new:
            status = "new"
        elif counters.updated:
            status = "updated"
        elif counters.skipped:
            status = "skipped"
        else:
            status = "failed"
        result["status"] = status
        result["chunks"] = len(chunks)
        result["pages"] = extracted.page_count
        result["quality"] = extracted.quality
        result["manifest"] = _manifest_entry(prop, extracted, chunks, url, ano)
        return result
    except Exception:
        result["status"] = "failed_process"
        return result


async def _process_scope(
    client: CamaraClient,
    pool: asyncpg.Pool,
    tipo: str,
    ano: int,
    source: str,
    stats: IngestStats,
) -> None:
    scope = f"{tipo}:{ano}"
    cursor = await get_cursor(pool, source, scope)
    desde_id = None
    if cursor and cursor.get("last_id") is not None:
        try:
            desde_id = int(cursor["last_id"])
        except (TypeError, ValueError):
            desde_id = None

    max_id: int | None = None
    async for item in client.listar_proposicoes(tipo, ano, desde_id=desde_id):
        stats.fetched += 1
        res = await process_proposition(client, pool, item, ano=ano, tipo=tipo, source=source)
        stats.chunks += res["chunks"]
        stats.pages += res["pages"]
        if res["quality"] == "low":
            stats.low_quality += 1
        if res["status"] == "new":
            stats.new += 1
        elif res["status"] == "updated":
            stats.updated += 1
        elif res["status"] == "skipped":
            stats.skipped += 1
        else:
            stats.failed += 1
        if res.get("manifest"):
            stats.documents.append(res["manifest"])

        iid = item.get("id") if isinstance(item, dict) else None
        if isinstance(iid, int) and (max_id is None or iid > max_id):
            max_id = iid

    if max_id is not None:
        await update_cursor(pool, source, scope, last_id=str(max_id))


def _write_manifest(path: Path, stats: IngestStats, duration: float, retries: int) -> None:
    manifest = {
        "generated_at": time.strftime("%Y-%m-%d"),
        "dataset_version": f"corpus-v1-{time.strftime('%Y-%m-%d')}",
        "scope": "F1.1 - ingestao real da Camara",
        "documents": stats.documents,
        "totals": {"documents": len(stats.documents), "chunks": stats.chunks},
        "timing": {"seconds": round(duration, 3), "retries": retries},
        "quality": {
            "low_quality_docs": stats.low_quality,
            "low_quality_pct": (
                stats.low_quality / len(stats.documents) * 100 if stats.documents else 0.0
            ),
        },
        "counters": {
            "fetched": stats.fetched,
            "new": stats.new,
            "updated": stats.updated,
            "skipped": stats.skipped,
            "failed": stats.failed,
        },
        "pages": stats.pages,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_ingest(
    *,
    client: CamaraClient | None = None,
    pool: Any | None = None,
    anos: list[int] | None = None,
    tipos: list[str] | None = None,
    source: str = SOURCE,
    data_dir: str | None = None,
    manifest_path: str | Path | None = None,
    rps: float | None = None,
) -> dict[str, Any]:
    """Executa a ingestao completa. Retorna resumo com numeros medidos."""
    if anos is None:
        anos = _env_ints("INGEST_ANOS", "2023,2024,2025,2026")
    if tipos is None:
        tipos = _env_list("INGEST_TIPOS", "PL,PLP,PEC,MPV,PDL")
    if data_dir is None:
        data_dir = os.environ.get("DATA_DIR", "./data")
    if manifest_path is None:
        manifest_path = Path(data_dir) / "manifest.json"

    owns_client = client is None
    owns_pool = pool is None
    if client is None:
        client = _CountingClient(
            rps=rps if rps is not None else None,
            cache_dir=Path(data_dir) / "cache" / "camara",
        )
    if pool is None:
        pool = await get_pool()

    stats = IngestStats()
    started = time.monotonic()
    try:
        for ano in anos:
            for tipo in tipos:
                await _process_scope(client, pool, tipo, ano, source, stats)

        duration = time.monotonic() - started
        retries = int(getattr(client, "retries", 0))

        counters = IngestCounters(
            fetched=stats.fetched,
            new=stats.new,
            updated=stats.updated,
            skipped=stats.skipped,
            failed=stats.failed,
        )
        run_id = await record_ingest_run(
            pool,
            source=source,
            scope="all",
            counters=counters,
            dataset_version=f"corpus-v1-{time.strftime('%Y-%m-%d')}",
        )

        mp = Path(manifest_path)
        _write_manifest(mp, stats, duration, retries)

        low_pct = stats.low_quality / len(stats.documents) * 100 if stats.documents else 0.0
        summary = {
            "run_id": run_id,
            "documents": len(stats.documents),
            "chunks": stats.chunks,
            "pages": stats.pages,
            "low_quality": stats.low_quality,
            "low_quality_pct": low_pct,
            "duration_seconds": duration,
            "retries": retries,
            "fetched": stats.fetched,
            "new": stats.new,
            "updated": stats.updated,
            "skipped": stats.skipped,
            "failed": stats.failed,
        }
        print(  # noqa: T201 - progresso da CLI de ingestao
            f"Ingestao concluida: docs={summary['documents']} chunks={summary['chunks']} "
            f"pages={summary['pages']} low_quality={summary['low_quality']} "
            f"({low_pct:.1f}%) duration={duration:.1f}s retries={retries}"
        )
        return summary
    finally:
        if owns_client:
            await client.aclose()
        if owns_pool:
            await close_pool()


def main() -> None:
    asyncio.run(run_ingest())


# Aliases para compatibilidade com testes/consumidores.
ingest = run_ingest
run = run_ingest
run_ingestion = run_ingest
ingest_all = run_ingest
ingest_corpus = run_ingest
ingest_proposition = process_proposition
ingest_one = process_proposition
process_proposition_async = process_proposition


if __name__ == "__main__":
    main()
