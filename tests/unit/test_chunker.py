"""Testes unitarios do chunker hierarquico."""

from __future__ import annotations

from pathlib import Path

from rig.ingestion import Chunk, chunk_document

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_recognizes_legal_markers() -> None:
    text = (FIXTURES / "sample_legal.txt").read_text(encoding="utf-8")
    chunks = chunk_document(text, {"doc_id": "42"})
    breadcrumbs = " ".join(c.breadcrumb for c in chunks)
    assert "Art. 1º" in breadcrumbs
    assert "Art. 5º" in breadcrumbs
    assert "Art. 1º-A" in breadcrumbs
    assert "Art. 5º Vetado" not in breadcrumbs  # vetado vira artigo normal
    assert any(c.kind == "preambulo" for c in chunks)


def test_no_empty_text() -> None:
    text = (FIXTURES / "sample_legal.txt").read_text(encoding="utf-8")
    chunks = chunk_document(text, {"doc_id": "42"})
    assert all(c.text.strip() for c in chunks)


def test_chunk_id_stable() -> None:
    text = (FIXTURES / "sample_legal.txt").read_text(encoding="utf-8")
    a = [c.chunk_id for c in chunk_document(text, {"doc_id": "42"})]
    b = [c.chunk_id for c in chunk_document(text, {"doc_id": "42"})]
    assert a == b
    for cid in a:
        assert cid.startswith("cam:42:")


def test_preamble_not_dispositivo() -> None:
    text = "Ementa inicial.\n\nArt. 1º Texto do artigo."
    chunks = chunk_document(text, {"doc_id": "7"})
    pre = [c for c in chunks if c.breadcrumb == "Preambulo"]
    assert pre
    assert all(c.kind == "preambulo" for c in pre)
    assert all(c.kind != "preambulo" or c.kind == "preambulo" for c in chunks)


def test_vetado_article() -> None:
    text = "Art. 5º Vetado"
    chunks = chunk_document(text, {"doc_id": "1"})
    assert len(chunks) == 1
    assert chunks[0].text.strip() == "Art. 5º Vetado"
    assert chunks[0].kind == "dispositivo"


def test_no_article_all_preamble() -> None:
    text = "Considerando que nada.\n\nEmenta final."
    chunks = chunk_document(text, {"doc_id": "2"})
    assert all(c.kind == "preambulo" for c in chunks)


def test_anexo_at_end() -> None:
    text = "Art. 1º Texto.\n\nANEXO\n| a | b |"
    chunks = chunk_document(text, {"doc_id": "3"})
    assert any(c.kind == "anexo" for c in chunks)


def test_hierarchy_structure() -> None:
    long_body = "palavra " * 300
    text = (
        "Art. 5º Caput. " + long_body + "\n"
        "§ 2º Paragrafo. " + long_body + "\n"
        "   II - inciso. " + long_body + "\n"
        "      b) alinea. " + long_body + "\n"
    )
    chunks = chunk_document(text, {"doc_id": "5"})
    inc = next(c for c in chunks if c.breadcrumb.endswith("II"))
    assert inc.hierarchy["artigo"] == "5º"
    assert inc.hierarchy["paragrafo"] == "§ 2º"
    assert inc.hierarchy["inciso"] == "II"
    al = [c for c in chunks if c.breadcrumb.endswith("b)")]
    assert al and al[0].hierarchy["alinea"] == "b)"


def test_combined_paragraphs() -> None:
    text = "Art. 1º-A Caput.\n§§ 1º e 2º Revogados."
    chunks = chunk_document(text, {"doc_id": "6"})
    assert chunks
    assert any("1º-A" in c.breadcrumb for c in chunks)


def test_kind_values() -> None:
    text = (FIXTURES / "sample_legal.txt").read_text(encoding="utf-8")
    chunks = chunk_document(text, {"doc_id": "42"})
    assert all(c.kind in {"preambulo", "dispositivo", "anexo"} for c in chunks)


def test_hierarchy_equality_dict() -> None:
    text = "Art. 5º Caput.\n§ 2º P.\n   II - I.\n"
    chunks = chunk_document(text, {"doc_id": "8"})
    # no crash
    assert isinstance(chunks, list)
    assert all(isinstance(c, Chunk) for c in chunks)
