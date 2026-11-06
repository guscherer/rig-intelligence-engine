"""Pacote ingestion do RIG Intelligence Engine.

Interface publica deste pacote: exportar aqui, nunca importar de submodulo
(ver docs/10-engineering-standards.md secao 1).
"""

from rig.ingestion.camara import CamaraClient, Proposition
from rig.ingestion.chunker import Chunk, chunk_document
from rig.ingestion.pdf import ExtractedDoc, extract_pdf
from rig.ingestion.store import (
    IngestCounters,
    ingest_run_record,
    upsert,
    upsert_chunks,
    upsert_document,
)

__all__ = [
    "CamaraClient",
    "Chunk",
    "ExtractedDoc",
    "IngestCounters",
    "Proposition",
    "chunk_document",
    "extract_pdf",
    "ingest_run_record",
    "upsert",
    "upsert_chunks",
    "upsert_document",
]
