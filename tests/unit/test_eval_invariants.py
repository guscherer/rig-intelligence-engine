"""Invariantes anti-fabricacao do artefato de medicao (F1.6e).

Roda sem rede, modelo ou banco: apenas le o JSON e o relatorio ja publicados.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
MODULE_PATH = ROOT / "scripts" / "eval_retrieval.py"
JSON_PATH = ROOT / "eval" / "results" / "recall_v1.json"
REPORT_PATH = ROOT / "docs" / "eval-retrieval.md"

spec = importlib.util.spec_from_file_location("eval_retrieval_invariants", MODULE_PATH)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def _load() -> dict:
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_dense_latency_exceeds_encode() -> None:
    data = _load()
    dense = next(v for v in data["variants"] if v["variant"] == "dense")
    assert dense["latency_p50_ms"] > data["encode_latency_p50_ms"]


def test_latency_mean_not_below_p50() -> None:
    data = _load()
    for variant in data["variants"]:
        mean = variant.get("latency_mean_ms")
        p50 = variant.get("latency_p50_ms")
        if mean is None or p50 is None:
            continue
        assert mean >= p50, (variant["variant"], mean, p50)


def test_recall_recomputes_from_per_query() -> None:
    data = _load()
    for declared in data["variants"]:
        name = declared["variant"]
        per_query = data["per_query"].get(name) or []
        if not per_query:
            continue
        n = len(per_query)
        hits = sum(1 for q in per_query if q.get("hit"))
        rrs = [1.0 / q["rank"] if q.get("rank") else 0.0 for q in per_query]
        mrr = sum(rrs) / n if n else 0.0
        assert abs(declared["recall_at_8"] - hits / n) < 1e-9, name
        assert abs(declared["mrr_at_8"] - mrr) < 1e-9, name


def test_provenance_hashes_match_files() -> None:
    data = _load()
    prov = data["provenance"]
    assert prov["report_sha256"] == hashlib.sha256(REPORT_PATH.read_bytes()).hexdigest()


def test_report_matches_json() -> None:
    data = _load()
    report = mod.render_report(
        data["variants"],
        data["run_date"],
        data["corpus_version"],
        encode_p50_ms=data["encode_latency_p50_ms"],
        encode_p95_ms=data["encode_latency_p95_ms"],
        model_load_ms=data["model_load_ms"],
    )
    expected = REPORT_PATH.read_text(encoding="utf-8")
    assert report == expected
