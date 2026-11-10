"""Testes das quatro checagens globais da auditoria (docs/03 §6.3) — sem rede.

Cada checagem tem um caso que dispara e um controle que NÃO dispara — o
controle é obrigatório: checagem testada só positivamente vira falso positivo
no reparo. Nenhuma das quatro chama LLM ou rede (o módulo não importa cliente
HTTP), e os testes rodam sem mock de rede. Todo texto é sintético (ADR-009).
"""

from __future__ import annotations

from rig.audit import (
    Finding,
    RuleCode,
    SectionTemplate,
    Severity,
    empty_sections,
    global_checks,
    missing_sections,
    uncited_quantities,
    unsupported_promises,
)


def _chunk(chunk_id: str, text: str = "") -> dict[str, str]:
    """Chunk sintético no contrato mínimo de ``chunk_text``/``chunk_id``."""
    return {"chunk_id": chunk_id, "text": text}


def _template(*sections: str) -> SectionTemplate:
    return SectionTemplate(sections=tuple(sections))


# ── Checagem 1: afirmação quantitativa sem fonte ─────────────────────────────


def test_uncited_quantity_flags_quantitative_markers_without_citation() -> None:
    findings = uncited_quantities("O reajuste de R$ 2 milhões representa 12% do orçamento.")
    assert [f.code for f in findings] == [RuleCode.UNCITED_QUANTITY]
    assert findings[0].severity == Severity.REPAIRABLE
    assert findings[0].sentence.startswith("O reajuste")


def test_uncited_quantity_control_cited_quantity_not_flagged() -> None:
    findings = uncited_quantities("O reajuste de R$ 2 milhões representa 12% [C1].")
    assert not any(f.code == RuleCode.UNCITED_QUANTITY for f in findings)


# ── Checagem 2: promessa de resultado/prazo ausente da fonte ─────────────────


def test_unsupported_promise_flags_deadline_not_in_source() -> None:
    findings = unsupported_promises(
        "A norma garantirá adaptação em 90 dias [C1].",
        [_chunk("c1", "A norma prevê regras gerais.")],
    )
    assert [f.code for f in findings] == [RuleCode.UNSUPPORTED_PROMISE]
    assert findings[0].severity == Severity.REPAIRABLE
    assert "90 dias" in findings[0].detail


def test_unsupported_promise_control_term_in_source_not_flagged() -> None:
    findings = unsupported_promises(
        "A norma garantirá adaptação em 90 dias [C1].",
        [_chunk("c1", "A norma prevê adaptação em 90 dias.")],
    )
    assert not any(f.code == RuleCode.UNSUPPORTED_PROMISE for f in findings)


def test_unsupported_promise_flags_year_deadline_not_in_source() -> None:
    findings = unsupported_promises(
        "A entrega ocorrerá até 2026 [C1].",
        [_chunk("c1", "A entrega ocorrerá em 2025.")],
    )
    assert [f.code for f in findings] == [RuleCode.UNSUPPORTED_PROMISE]


def test_unsupported_promise_verb_without_concrete_term_not_flagged() -> None:
    # "garantirá" sem prazo/termo concreto: o juízo de "resultado" é do NLI (§6.2).
    findings = unsupported_promises(
        "A norma garantirá a aprovação automática [C1].",
        [_chunk("c1", "A norma trata da aprovação.")],
    )
    assert not any(f.code == RuleCode.UNSUPPORTED_PROMISE for f in findings)


# ── Checagem 3: desvio de escopo (seção obrigatória ausente) ─────────────────


def test_missing_section_flags_absent_required_section() -> None:
    draft = "## Escopo\n- A lei estabelece normas [C1]."
    findings = missing_sections(draft, _template("Escopo", "Análise", "Recomendação"))
    assert [f.code for f in findings] == [RuleCode.MISSING_SECTION, RuleCode.MISSING_SECTION]
    assert {f.sentence for f in findings} == {"Análise", "Recomendação"}


def test_missing_section_control_all_present_not_flagged() -> None:
    draft = (
        "## Escopo\n- A lei estabelece normas [C1].\n"
        "## Análise\n- A medida impacta o setor [C1].\n"
        "## Recomendação\n- Observar os prazos [C1]."
    )
    findings = missing_sections(draft, _template("Escopo", "Análise", "Recomendação"))
    assert findings == []


# ── Checagem 4: seção vazia apresentada como concluída ───────────────────────


def test_empty_section_flags_placeholder_body() -> None:
    draft = "## Escopo\nTODO\n## Análise\n- A medida impacta o setor [C1]."
    findings = empty_sections(draft, _template("Escopo", "Análise"))
    assert [f.code for f in findings] == [RuleCode.EMPTY_SECTION]
    assert findings[0].sentence == "Escopo"
    assert findings[0].severity == Severity.REPAIRABLE


def test_empty_section_control_substantial_body_not_flagged() -> None:
    draft = (
        "## Escopo\n- A lei estabelece normas de governança [C1].\n"
        "## Análise\n- A medida impacta o setor [C1]."
    )
    findings = empty_sections(draft, _template("Escopo", "Análise"))
    assert not any(f.code == RuleCode.EMPTY_SECTION for f in findings)


# ── Agregador e contrato do tipo ─────────────────────────────────────────────


def test_global_checks_clean_document_returns_empty() -> None:
    draft = (
        "## Escopo\n"
        "- A lei estabelece normas gerais de governança [C1].\n"
        "## Análise\n"
        "- A norma prevê adaptação em 90 dias [C1].\n"
        "## Recomendação\n"
        "- Recomenda-se observar os prazos legais [C1].\n"
    )
    chunks = [
        _chunk("c1", "A lei estabelece normas gerais de governança e prevê adaptação em 90 dias.")
    ]
    template = _template("Escopo", "Análise", "Recomendação")
    assert global_checks(draft, template, chunks) == []


def test_global_checks_returns_shared_finding_type() -> None:
    draft = "## Escopo\n- A lei estabelece normas [C1].\n## Vazio\nTODO\n"
    chunks = [_chunk("c1", "A lei estabelece normas.")]
    result = global_checks(draft, _template("Escopo", "Vazio", "Ausente"), chunks)
    assert isinstance(result, list)
    assert all(isinstance(f, Finding) for f in result)
    assert {f.code for f in result} == {RuleCode.MISSING_SECTION, RuleCode.EMPTY_SECTION}
