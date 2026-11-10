"""Testes das seis regras determinísticas da auditoria (docs/03 §6.1).

Cada regra tem um caso que dispara e um controle que NÃO dispara — o controle é
obrigatório: regra testada só positivamente vira falso positivo em produção.
Todo texto é sintético (ADR-009: nada de lei real copiada).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rig.audit import (
    AuditReport,
    AuditStatus,
    Finding,
    FindingCode,
    Severity,
    audit_draft,
    forbidden_language,
    hard_rules,
    missing_articles,
    number_mismatches,
    orphan_citations,
    preamble_as_device,
    uncited_facts,
)


def _chunk(chunk_id: str, text: str = "", kind: str = "dispositivo") -> dict[str, str]:
    """Chunk sintético no contrato mínimo de chunk_text/chunk_id/kind."""
    return {"chunk_id": chunk_id, "text": text, "kind": kind}


# ── Regra 1: citação órfã ────────────────────────────────────────────────────


def test_orphan_citation_flags_index_beyond_chunks() -> None:
    findings = orphan_citations("A norma estabelece o prazo [C9].", [_chunk("c1")])
    assert len(findings) == 1
    assert findings[0].code == FindingCode.ORPHAN_CITATION
    assert findings[0].severity == Severity.REPAIRABLE


def test_orphan_citation_control_valid_index_not_flagged() -> None:
    findings = orphan_citations("A norma estabelece o prazo [C1].", [_chunk("c1")])
    assert not any(f.code == FindingCode.ORPHAN_CITATION for f in findings)


# ── Regra 2: artigo inexistente ──────────────────────────────────────────────


def test_missing_article_flags_article_beyond_source() -> None:
    findings = missing_articles("Art. 42 veda a prática.", [_chunk("c1", "Art. 30 ...")])
    assert len(findings) == 1
    assert findings[0].code == FindingCode.MISSING_ARTICLE
    assert findings[0].severity == Severity.BLOCKING


def test_missing_article_control_within_source_not_flagged() -> None:
    findings = missing_articles("Art. 30 veda a prática.", [_chunk("c1", "Art. 30 ...")])
    assert not any(f.code == FindingCode.MISSING_ARTICLE for f in findings)


# ── Regra 3: número/data divergente ──────────────────────────────────────────


def test_number_mismatch_flags_divergent_number() -> None:
    findings = number_mismatches("O prazo é de 3,5 anos.", [_chunk("c1", "O prazo é de 3,7 anos.")])
    assert len(findings) == 1
    assert findings[0].code == FindingCode.NUMBER_MISMATCH
    assert findings[0].severity == Severity.BLOCKING


def test_number_mismatch_control_normalized_equal_not_flagged() -> None:
    findings = number_mismatches("O prazo é de 3,5 anos.", [_chunk("c1", "O prazo é de 3.5 anos.")])
    assert not any(f.code == FindingCode.NUMBER_MISMATCH for f in findings)


def test_number_mismatch_control_thousands_written_differently_not_flagged() -> None:
    # 1.000 e 1000 são o mesmo número escrito diferente (separador de milhar).
    findings = number_mismatches("O valor é 1.000 reais.", [_chunk("c1", "O valor é 1000 reais.")])
    assert not any(f.code == FindingCode.NUMBER_MISMATCH for f in findings)


def test_number_mismatch_flags_divergent_date() -> None:
    findings = number_mismatches(
        "A lei entra em vigor em 05/02/2024.",
        [_chunk("c1", "A lei entra em vigor em 01/02/2024.")],
    )
    assert [f.code for f in findings] == [FindingCode.NUMBER_MISMATCH]


# ── Regra 4: frase factual sem citação ────────────────────────────────────────


def test_uncited_fact_flags_factual_sentence_without_citation() -> None:
    findings = uncited_facts("A lei estabelece prazo de 90 dias.", [])
    assert len(findings) == 1
    assert findings[0].code == FindingCode.UNCITED_FACT
    assert findings[0].severity == Severity.REPAIRABLE


def test_uncited_fact_control_cited_sentence_not_flagged() -> None:
    findings = uncited_facts("A lei estabelece prazo de 90 dias [C1].", [_chunk("c1")])
    assert not any(f.code == FindingCode.UNCITED_FACT for f in findings)


def test_uncited_fact_transition_not_flagged() -> None:
    # "Ponto não coberto pelas fontes consultadas" é transição, não afirmação factual.
    findings = uncited_facts("Ponto não coberto pelas fontes consultadas.", [])
    assert not any(f.code == FindingCode.UNCITED_FACT for f in findings)


# ── Regra 5: linguagem proibida ──────────────────────────────────────────────


def test_forbidden_language_flags_forbidden_term() -> None:
    findings = forbidden_language("Esta medida é certamente inconstitucional.", [])
    assert {f.code for f in findings} == {FindingCode.FORBIDDEN_LANGUAGE}
    assert all(f.severity == Severity.REPAIRABLE for f in findings)


def test_forbidden_language_negated_still_flags() -> None:
    # Mesmo negada, a linguagem de parecer jurídico proibida dispara.
    findings = forbidden_language("Esta medida não é inconstitucional.", [])
    assert any(f.code == FindingCode.FORBIDDEN_LANGUAGE for f in findings)


def test_forbidden_language_control_clean_sentence_not_flagged() -> None:
    findings = forbidden_language("Esta medida observa os prazos legais.", [])
    assert not any(f.code == FindingCode.FORBIDDEN_LANGUAGE for f in findings)


# ── Regra 6: preâmbulo como dispositivo ──────────────────────────────────────


def test_preamble_as_device_flags_preamble_citation() -> None:
    findings = preamble_as_device(
        "O Art. 1º estabelece a obrigação [C1].", [_chunk("c1", "Preâmbulo ...", "preambulo")]
    )
    assert len(findings) == 1
    assert findings[0].code == FindingCode.PREAMBLE_AS_DEVICE
    assert findings[0].severity == Severity.REPAIRABLE


def test_preamble_as_device_control_device_citation_not_flagged() -> None:
    findings = preamble_as_device(
        "O Art. 1º estabelece a obrigação [C1].", [_chunk("c1", "Art. 1º ...", "dispositivo")]
    )
    assert not any(f.code == FindingCode.PREAMBLE_AS_DEVICE for f in findings)


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
        FindingCode.ORPHAN_CITATION,
        FindingCode.MISSING_ARTICLE,
        FindingCode.NUMBER_MISMATCH,
        FindingCode.UNCITED_FACT,
        FindingCode.FORBIDDEN_LANGUAGE,
        FindingCode.PREAMBLE_AS_DEVICE,
    }


def test_each_finding_has_sentence_index() -> None:
    findings = hard_rules(
        "Art. 42 veda a prática [C9].", [_chunk("c1", "Art. 30 ...", "dispositivo")]
    )
    assert findings
    for f in findings:
        assert isinstance(f.sentence_index, int)


def test_finding_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Finding(
            code=FindingCode.UNCITED_FACT,
            severity=Severity.REPAIRABLE,
            sentence_index=0,
            detail="y",
            needed_fix="z",
            campo_inventado="não deveria existir",
        )


# ── audit_draft ───────────────────────────────────────────────────────────────


def test_audit_draft_returns_report() -> None:
    report = audit_draft("Texto limpo.", [])
    assert isinstance(report, AuditReport)
    assert report.status == AuditStatus.PASS
    assert report.findings == []
    assert report.verdicts == []


def test_audit_draft_blocked_on_blocking_finding() -> None:
    report = audit_draft("Art. 42 veda a prática.", [_chunk("c1", "Art. 30 ...")])
    assert report.status == AuditStatus.BLOCKED
    assert any(f.code == FindingCode.MISSING_ARTICLE for f in report.findings)
    assert report.needed_fixes


def test_audit_draft_repair_on_repairable_finding() -> None:
    report = audit_draft("Esta medida é certamente inconstitucional.", [])
    assert report.status == AuditStatus.REPAIR
    assert report.reasons
