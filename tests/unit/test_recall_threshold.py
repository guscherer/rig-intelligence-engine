"""Teste de CI: recall@8 da variante escolhida (dense) não pode cair abaixo do threshold.

Threshold gravado aqui, com comentário do motivo. Ver docs/eval-retrieval.md.

Documentação do threshold (P1-1):
- n=40 consultas; granularidade do recall = 2,5 p.p. por consulta.
- Origem: borda inferior do IC95 do dense (recall@8=0.950, IC95 [0.875, 1.000]).
- O que NÃO prova: 0.875 < 0.925 (recall do rrf), portanto este gate não
  valida a escolha do dense sobre o híbrido; a escolha é justificada por
  empate estatístico em n=40 (ver docs/eval-retrieval.md). O gate só detecta
  regressão grosseira (>2,5 p.p.).
- Não afrouxar para fazer passar — se cair, registrar em docs/08-failures.md.
"""

from __future__ import annotations

import json
from pathlib import Path

# Variante escolhida no F1.5: dense (recall@8=0.950, IC95 [0.875, 1.000]).
# Threshold conservador na borda inferior do IC95 para evitar flakiness em n=40.
# Não afrouxar para fazer passar — se cair, registrar em docs/08-failures.md.
RECALL_THRESHOLD_DENSE: float = 0.875

RESULTS_PATH = Path("eval/results/recall_v1.json")


def test_recorded_recall_dense_above_threshold() -> None:
    assert RESULTS_PATH.exists(), "eval/results/recall_v1.json ausente — rode make eval-retrieval"
    payload = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    variants = {v["variant"]: v for v in payload["variants"]}
    assert "dense" in variants, "variante dense ausente do relatório"
    recall = variants["dense"]["recall_at_8"]
    assert recall is not None, "recall@8 da variante dense não medido"
    assert recall >= RECALL_THRESHOLD_DENSE, (
        f"recall@8 dense={recall} < threshold {RECALL_THRESHOLD_DENSE}"
    )
