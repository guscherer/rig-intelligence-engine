"""Teste de conteúdo do relatório gerado por scripts/eval_retrieval.py.

Gera o texto a partir de um payload fixo e verifica os trechos obrigatórios,
para que uma regeneração não apague de novo a coluna `errors` nem a nota do
threshold.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
MODULE_PATH = ROOT / "scripts" / "eval_retrieval.py"

spec = importlib.util.spec_from_file_location("eval_retrieval_report", MODULE_PATH)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _fixed_results() -> list[dict]:
    return [
        {
            "variant": "dense",
            "n": 40,
            "recall_at_8": 0.95,
            "mrr_at_8": 0.673,
            "recall_ci_95": [0.875, 1.0],
            "mrr_ci_95": [0.564, 0.778],
            "latency_p50_ms": 78.2,
            "latency_p95_ms": 85.3,
            "hits": 38,
            "errors": 0,
        },
        {
            "variant": "rrf+rerank",
            "n": 0,
            "recall_at_8": None,
            "mrr_at_8": None,
            "recall_ci_95": [None, None],
            "mrr_ci_95": [None, None],
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "hits": 0,
            "errors": 0,
        },
    ]


def test_generated_report_has_errors_column() -> None:
    text = mod.render_report(_fixed_results(), "2026-11-07", "cam-2026-11-06")
    assert (
        "| Variante | recall@8 | IC95 recall | MRR@8 | IC95 MRR | p50 | p95 | hits | errors |"
        in text
    )


def test_generated_report_has_granularity_header() -> None:
    text = mod.render_report(_fixed_results(), "2026-11-07", "cam-2026-11-06")
    assert "n=40 consultas; granularidade do recall = 2,5 p.p./consulta" in text


def test_generated_report_has_threshold_note() -> None:
    text = mod.render_report(_fixed_results(), "2026-11-07", "cam-2026-11-06")
    assert (
        "0.875 = 35/40 = borda inferior do IC95 do dense; não prova que dense > rrf (0.875 < 0.925)"
        in text
    )
