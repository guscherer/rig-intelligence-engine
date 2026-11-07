"""Extração de texto de PDF de inteiro teor.

Interface pública: ``ExtractedDoc`` e ``extract_pdf``.
"""

from __future__ import annotations

import re
from typing import Any, Literal, cast

import pymupdf
from pydantic import BaseModel, ConfigDict


class ExtractedDoc(BaseModel):
    """Documento extraído de um PDF de inteiro teor."""

    model_config = ConfigDict(frozen=True)

    pages: list[str]
    page_count: int
    quality: Literal["high", "low"]
    text: str


def extract_pdf(data: bytes) -> ExtractedDoc:
    """Extrai texto de um PDF, detectando scan e limpando cabeçalho/rodapé."""
    doc: Any = cast(Any, pymupdf.open(stream=data, filetype="pdf"))  # type: ignore[no-untyped-call]  # pymupdf nao tipado
    try:
        raw_pages = [_page_text(page) for page in doc]
        page_count = len(raw_pages)
        normalized = [_normalize_spaces(page) for page in raw_pages]
        cleaned = _drop_repeated_lines(normalized)
        pages = [_fix_hyphenation(page) for page in cleaned]
        quality: Literal["high", "low"] = "low" if _low_density(pages, page_count) else "high"
        text = "\n\n".join(pages).strip()
        return ExtractedDoc(pages=pages, page_count=page_count, quality=quality, text=text)
    finally:
        doc.close()


def _page_text(page: Any) -> str:
    return str(page.get_text())


def _normalize_spaces(text: str) -> str:
    text = text.replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(lines)


def _drop_repeated_lines(pages: list[str]) -> list[str]:
    if not pages or len(pages) < 2:
        return pages
    page_lines = [page.split("\n") for page in pages]
    freq: dict[str, int] = {}
    total_pages = len(page_lines)
    for lines in page_lines:
        for line in set(lines):
            if line.strip():
                freq[line] = freq.get(line, 0) + 1
    repeated = {line for line, count in freq.items() if count / total_pages >= 0.6}
    return ["\n".join(line for line in lines if line not in repeated) for lines in page_lines]


def _fix_hyphenation(text: str) -> str:
    return re.sub(r"(\w)-\s+(?=\w)", r"\1", text)


def _low_density(pages: list[str], page_count: int) -> bool:
    if page_count <= 0:
        return False
    total = sum(len(page.strip()) for page in pages)
    return total / page_count < 100
