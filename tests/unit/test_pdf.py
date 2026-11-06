"""Testes unitarios de extracao de PDF (sem rede)."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from rig.ingestion import ExtractedDoc, extract_pdf

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _make_pdf(pages_text: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def _make_image_pdf(page_count: int = 2) -> bytes:
    doc = pymupdf.open()
    for _ in range(page_count):
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(10, 10, 50, 50), color=(0, 0, 0), fill=(0, 0, 0))
    data = doc.tobytes()
    doc.close()
    return data


def test_extract_real_dummy_pdf() -> None:
    data = (FIXTURES / "w3c_dummy.pdf").read_bytes()
    doc = extract_pdf(data)
    assert isinstance(doc, ExtractedDoc)
    assert doc.page_count == 1
    assert doc.quality == "low"
    assert "Dummy PDF file" in doc.text
    assert len(doc.pages) == 1


def test_extract_real_multipage_pdf() -> None:
    data = (FIXTURES / "pdf995_vrml_excerpt.pdf").read_bytes()
    doc = extract_pdf(data)
    assert doc.page_count == 2
    assert doc.quality == "high"
    assert len(doc.pages) == doc.page_count
    assert doc.text


def test_scanned_pdf_returns_low_and_empty_text() -> None:
    data = _make_image_pdf(2)
    doc = extract_pdf(data)
    assert doc.quality == "low"
    assert doc.text == ""
    assert doc.page_count == 2


def test_header_footer_removal() -> None:
    header = "CABECALHO REPETIDO"
    footer = "RODAPE REPETIDO"
    pages = [f"{header}\n" + (f"Corpo da pagina {i}. " * 12) + f"\n{footer}" for i in range(5)]
    data = _make_pdf(pages)
    doc = extract_pdf(data)
    assert doc.quality == "high"
    for page in doc.pages:
        assert header not in page
        assert footer not in page
    assert "Corpo da pagina 0" in doc.pages[0]


def test_header_footer_threshold_not_remove_rare() -> None:
    rare = "LINHA RARA"
    pages = [f"Corpo {i}" for i in range(5)]
    pages[0] = rare + "\n" + pages[0]
    data = _make_pdf(pages)
    doc = extract_pdf(data)
    assert any(rare in p for p in doc.pages)


def test_hyphenation_normalization() -> None:
    data = _make_pdf(["in- telec- tual e Art. 12"])
    doc = extract_pdf(data)
    assert "intelectual" in doc.text
    assert "Art. 12" in doc.text


def test_nbsp_and_multiple_spaces() -> None:
    data = _make_pdf(["a\u00a0\u00a0b   c"])
    doc = extract_pdf(data)
    assert "a b c" in doc.text


def test_page_count_and_pages_length_match() -> None:
    data = _make_pdf(["p1", "p2", "p3"])
    doc = extract_pdf(data)
    assert doc.page_count == 3
    assert len(doc.pages) == 3
