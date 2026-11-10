"""Testes das seis regras determinísticas da auditoria (docs/03 §6.1).

Cada regra tem um caso que dispara e um controle que NÃO dispara — o controle é
obrigatório: regra testada só positivamente vira falso positivo em produção.
Todo texto é sintético (ADR-009: nada de lei real copiada).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rig.audit import (
    Finding,
    RuleCode,
    Severity,
    forbidden_language,
    hard_rules,
    missing_articles,
    number_mismatches,
    orphan_citations,
    preamble_as_device,
    uncited_facts,
)


def _chunk(chunk_id: str, text: str = "", kind: str = "dispositivo") -> dict[str, str]:
    """Chunk sintético no contrato mínimo de ``chunk_text``/``chunk_id``/kind."""
    return {"chunk_id": chunk_id, "text": text, "kind": kind}


# ── Regra 1: citação órfã ────────────────────────────────────────────────────


def test_orphan_citation_flags_index_beyond_chunks() -> None:
    findings = orphan_citations("A norma estabelece o prazo [C9].", [_chunk("c1")])
    assert len(findings) == 1
    assert findings[0].code == RuleCode.ORPHAN_CITATION
    assert findings[0].severity == Severity.REPAIRABLE


def test_orphan_citation_control_valid_index_not_flagged() -> None:
    findings = orphan_citations("A norma estabelece o prazo [C1].", [_chunk("c1")])
    assert not any(f.code == RuleCode.ORPHAN_CITATION for f in findings)


# ── Regra 2: artigo inexistente ──────────────────────────────────────────────


def test_missing_article_flags_article_beyond_source() -> None:
    findings = missing_articles("Art. 42 veda a prática.", [_chunk("c1", "Art. 30 ...")])
    assert len(findings) == 1
    assert findings[0].code == RuleCode.MISSING_ARTICLE
    assert findings[0].severity == Severity.BLOCKING


def test_missing_article_control_within_source_not_flagged() -> None:
    findings = missing_articles("Art. 30 veda a prática.", [_chunk("c1", "Art. 30 ...")])
    assert not any(f.code == RuleCode.MISSING_ARTICLE for f in findings)


# ── Regra 3: número/data divergente ──────────────────────────────────────────


def test_number_mismatch_flags_divergent_number() -> None:
    findings = number_mismatches("O prazo é de 3,5 anos.", [_chunk("c1", "O prazo é de 3,7 anos.")])
    assert len(findings) == 1
    assert findings[0].code == RuleCode.NUMBER_MISMATCH
    assert findings[0].severity == Severity.BLOCKING


def test_number_mismatch_control_normalized_equal_not_flagged() -> None:
    findings = number_mismatches("O prazo é de 3,5 anos.", [_chunk("c1", "O prazo é de 3.5 anos.")])
    assert not any(f.code == RuleCode.NUMBER_MISMATCH for f in findings)


def test_number_mismatch_flags_divergent_date() -> None:
    findings = number_mismatches(
        "A lei entra em vigor em 05/02/2024.",
        [_chunk("c1", "A lei entra em vigor em 01/02/2024.")],
    )
    assert [f.code for f in findings] == [RuleCode.NUMBER_MISMATCH]


# ── Regra 4: frase factual sem citação ───────────────────────────────────────


def test_uncited_fact_flags_factual_sentence_without_citation() -> None:
    findings = uncited_facts("A lei estabelece prazo de 90 dias.", [])
    assert len(findings) == 1
    assert findings[0].code == RuleCode.UNCITED_FACT
    assert findings[0].severity == Severity.REPAIRABLE


def test_uncited_fact_control_cited_sentence_not_flagged() -> None:
    findings = uncited_facts("A lei estabelece prazo de 90 dias [C1].", [_chunk("c1")])
    assert not any(f.code == RuleCode.UNCITED_FACT for f in findings)


# ── Regra 5: linguagem proibida ──────────────────────────────────────────────


def test_forbidden_language_flags_forbidden_term() -> None:
    findings = forbidden_language("Esta medida é certamente inconstitucional.", [])
    assert {f.code for f in findings} == {RuleCode.FORBIDDEN_LANGUAGE}
    assert all(f.severity == Severity.REPAIRABLE for f in findings)


def test_forbidden_language_control_clean_sentence_not_flagged() -> None:
    findings = forbidden_language("Esta medida observa os prazos legais.", [])
    assert not any(f.code == RuleCode.FORBIDDEN_LANGUAGE for f in findings)


# ── Regra 6: preâmbulo como dispositivo ──────────────────────────────────────


def test_preamble_as_device_flags_preamble_citation() -> None:
    findings = preamble_as_device(
        "O Art. 1º estabelece a obrigação [C1].", [_chunk("c1", "Preâmbulo ...", "preambulo")]
    )
    assert len(findings) == 1
    assert findings[0].code == RuleCode.PREAMBLE_AS_DEVICE
    assert findings[0].severity == Severity.REPAIRABLE
    assert findings[0].chunk_id == "c1"


def test_preamble_as_device_control_device_citation_not_flagged() -> None:
    findings = preamble_as_device(
        "O Art. 1º estabelece a obrigação [C1].", [_chunk("c1", "Art. 1º ...", "dispositivo")]
    )
    assert not any(f.code == RuleCode.PREAMBLE_AS_DEVICE for f in findings)


# ── Agregador e contrato do tipo ─────────────────────────────────────────────


def test_hard_rules_concatenates_all_six_rules() -> None:
    draft = (
        "Art. 42 veda a prática [C9]. "
        "A lei estabelece prazo de 3,5 anos certamente. "
        "O Art. 1º institui a taxa [C2]."
    )
    chunks = [
        _chunk("c1", "Art. 30 ...", "dispositivo"),
        _chunk("c2", "Preâmbulo ...", "preambulo"),
    ]
    expected = (
        orphan_citations(draft, chunks)
        + missing_articles(draft, chunks)
        + number_mismatches(draft, chunks)
        + uncited_facts(draft, chunks)
        + forbidden_language(draft, chunks)
        + preamble_as_device(draft, chunks)
    )
    result = hard_rules(draft, chunks)
    assert isinstance(result, list)
    assert all(isinstance(f, Finding) for f in result)
    assert result == expected
    assert {f.code for f in result} == {
        RuleCode.ORPHAN_CITATION,
        RuleCode.MISSING_ARTICLE,
        RuleCode.NUMBER_MISMATCH,
        RuleCode.UNCITED_FACT,
        RuleCode.FORBIDDEN_LANGUAGE,
        RuleCode.PREAMBLE_AS_DEVICE,
    }


def test_finding_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Finding(
            code=RuleCode.UNCITED_FACT,
            sentence="x",
            detail="y",
            chunk_id=None,
            severity=Severity.REPAIRABLE,
            campo_inventado="não deveria existir",
        )
