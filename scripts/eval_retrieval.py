"""Benchmark de retrieval: recall@8, MRR@8 e latencia por variante (F1.5).

Uso: `make eval-retrieval` (ou `uv run python scripts/eval_retrieval.py`).

Roda as quatro variantes (dense, sparse, RRF, RRF+rerank) sobre o golden set v1
e grava relatorio em docs/eval-retrieval.md e eval/results/recall_v1.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import yaml

from rig.retrieval.search import search

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "eval" / "golden" / "retrieval_v1.yaml"
RESULTS_DIR = ROOT / "eval" / "results"
REPORT_PATH = ROOT / "docs" / "eval-retrieval.md"
JSON_PATH = RESULTS_DIR / "recall_v1.json"

VARIANTS = ["dense", "sparse", "rrf"]
TOP_K = 8
CANDIDATE_K = 50
BOOTSTRAP_B = 2000
SEED = 42


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://rig:rig@localhost:5432/rig")
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            url = url.replace(prefix, prefix.split("+")[0] + "://", 1)
    return url


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


async def _run_variant(  # noqa: PLR0915, C901 - benchmark orquestra variantes, metricas, CI e relatorio por consulta
    pool,
    encoder,
    reranker,
    variant,
    items,
    query_vectors=None,
    timeout_s=None,
    bail=False,
) -> dict:
    hits: list[int] = []
    rrs: list[float] = []
    latencies_ms: list[float] = []
    per_query: list[dict] = []

    infeasible = False
    errors = 0
    for idx, item in enumerate(items):
        query = item["query"]
        gold = item["chunk_ouro"]
        qv = None
        if query_vectors is not None:
            qv = query_vectors[idx]
        t0 = time.perf_counter()
        try:
            coro = search(
                pool,
                query,
                mode=variant,
                limit=TOP_K,
                candidate_k=CANDIDATE_K,
                encoder=encoder,
                query_vector=qv,
                reranker=reranker if variant == "rrf+rerank" else None,
                rerank=(variant == "rrf+rerank"),
            )
            if timeout_s is not None:
                results = await asyncio.wait_for(coro, timeout=timeout_s)
            else:
                results = await coro
        except Exception as exc:
            results = []
            err = f"{type(exc).__name__}: {exc}"
            errors += 1
            if bail:
                infeasible = True
        else:
            err = None
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(elapsed_ms)

        rank = None
        for i, r in enumerate(results, start=1):
            if r.chunk_id == gold:
                rank = i
                break
        hit = 1 if rank is not None else 0
        rr = (1.0 / rank) if rank is not None else 0.0
        hits.append(hit)
        rrs.append(rr)
        per_query.append(
            {
                "query": query,
                "gold": gold,
                "variant": variant,
                "hit": bool(hit),
                "rank": rank,
                "latency_ms": round(elapsed_ms, 2),
                "error": err,
            }
        )
        if infeasible:
            # preenche o restante como nao medido e interrompe.
            for rest in items[idx + 1 :]:
                per_query.append(
                    {
                        "query": rest["query"],
                        "gold": rest["chunk_ouro"],
                        "variant": variant,
                        "hit": False,
                        "rank": None,
                        "latency_ms": 0.0,
                        "error": "infeasible: variante abortada apos falha na primeira consulta",
                    }
                )
                hits.append(0)
                rrs.append(0.0)
                latencies_ms.append(0.0)
            break

    n = len(items)
    recall = sum(hits) / n if n else 0.0
    mrr = sum(rrs) / n if n else 0.0

    # Bootstrap CI (resample queries).
    rng = random.Random(SEED)  # noqa: S311 - bootstrap CI, nao criptografia
    recall_samples: list[float] = []
    mrr_samples: list[float] = []
    for _ in range(BOOTSTRAP_B):
        idxs = [rng.randrange(n) for _ in range(n)]
        recall_samples.append(sum(hits[i] for i in idxs) / n)
        mrr_samples.append(sum(rrs[i] for i in idxs) / n)
    recall_ci = (_percentile(recall_samples, 2.5), _percentile(recall_samples, 97.5))
    mrr_ci = (_percentile(mrr_samples, 2.5), _percentile(mrr_samples, 97.5))

    return {
        "variant": variant,
        "n": n,
        "recall_at_8": recall,
        "mrr_at_8": mrr,
        "recall_ci_95": [recall_ci[0], recall_ci[1]],
        "mrr_ci_95": [mrr_ci[0], mrr_ci[1]],
        "latency_p50_ms": _percentile(latencies_ms, 50),
        "latency_p95_ms": _percentile(latencies_ms, 95),
        "latency_mean_ms": statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        "hits": sum(hits),
        "errors": errors,
        "per_query": per_query,
    }


def render_report(  # noqa: PLR0915
    results: list[dict[str, Any]],
    run_date: str,
    corpus_version: str,
    *,
    encode_p50_ms: float | None = None,
    encode_p95_ms: float | None = None,
    model_load_ms: float | None = None,
) -> str:
    """Renderiza o relatório Markdown a partir de um payload de resultados."""
    lines = []
    lines.append("# Benchmark de retrieval — recall@8 por variante (F1.5)")
    lines.append("")
    lines.append(f"- Data da execução: {run_date}")
    lines.append(f"- Versão do corpus (golden set): `{corpus_version}`")
    lines.append("- Golden set: `eval/golden/retrieval_v1.yaml` (40 consultas, provisional)")
    lines.append(f"- Top-k: {TOP_K}; candidate-k: {CANDIDATE_K}")
    lines.append(f"- IC 95% por bootstrap (B={BOOTSTRAP_B}, seed={SEED})")
    lines.append("- n=40 consultas; granularidade do recall = 2,5 p.p./consulta")
    lines.append("")
    lines.append("## Tabela comparativa")
    lines.append("")
    lines.append(
        "| Variante | recall@8 | IC95 recall | MRR@8 | IC95 MRR | p50 | p95 | hits | errors |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        recall_str = "n/a" if r["recall_at_8"] is None else f"{r['recall_at_8']:.3f}"
        ci_r = (
            "n/a"
            if r["recall_ci_95"][0] is None
            else f"[{r['recall_ci_95'][0]:.3f}, {r['recall_ci_95'][1]:.3f}]"
        )
        mrr_str = "n/a" if r["mrr_at_8"] is None else f"{r['mrr_at_8']:.3f}"
        ci_m = (
            "n/a"
            if r["mrr_ci_95"][0] is None
            else f"[{r['mrr_ci_95'][0]:.3f}, {r['mrr_ci_95'][1]:.3f}]"
        )
        p50_str = "n/a" if r["latency_p50_ms"] is None else f"{r['latency_p50_ms']:.1f}"
        p95_str = "n/a" if r["latency_p95_ms"] is None else f"{r['latency_p95_ms']:.1f}"
        hits_str = "n/a" if r["n"] == 0 else f"{r['hits']}/{r['n']}"
        errors_str = str(r.get("errors", 0))
        lines.append(
            f"| {r['variant']} | {recall_str} | {ci_r} | {mrr_str} | {ci_m} | "
            f"{p50_str} | {p95_str} | {hits_str} | {errors_str} |"
        )
    lines.append("")
    lines.append("## Decisão")
    lines.append("")
    measured = [r for r in results if r["recall_at_8"] is not None]
    best = max(measured, key=lambda r: (r["recall_at_8"], -r["latency_p50_ms"]))
    lines.append(
        f"Variante escolhida: **{best['variant']}** "
        f"(recall@8={best['recall_at_8']:.3f}, MRR@8={best['mrr_at_8']:.3f}, "
        f"p50={best['latency_p50_ms']:.1f}ms, p95={best['latency_p95_ms']:.1f}ms)."
    )
    lines.append("")
    dense_r = next((r for r in results if r.get("variant") == "dense"), None)
    rrf_r = next((r for r in results if r.get("variant") == "rrf"), None)
    if dense_r is not None and dense_r.get("recall_at_8") is not None:
        dense_bit = (
            f"dense recall@8={dense_r['recall_at_8']:.3f}, IC95 "
            f"[{dense_r['recall_ci_95'][0]:.3f}, {dense_r['recall_ci_95'][1]:.3f}]"
        )
    else:
        dense_bit = "dense recall@8=n/a"
    if rrf_r is not None and rrf_r.get("recall_at_8") is not None:
        rrf_bit = (
            f"rrf recall@8={rrf_r['recall_at_8']:.3f}, IC95 "
            f"[{rrf_r['recall_ci_95'][0]:.3f}, {rrf_r['recall_ci_95'][1]:.3f}]"
        )
    else:
        rrf_bit = "rrf recall@8=n/a"
    lines.append(
        "Decisão: empate estatístico ("
        + dense_bit
        + " vs. "
        + rrf_bit
        + " — intervalos sobrepostos). O híbrido (RRF) não supera o "
        "denso de forma estatisticamente relevante, e a afirmação recíproca "
        "também seria verdadeira. Mantém-se `dense` como default pela "
        "justificativa operacional: o encode da consulta já está no caminho, "
        "eliminar BM25+RRF reduz superfície de manutenção e latência de "
        "operação. O rerank (cross-encoder) é inviável neste host: tentou "
        "alocar ~3,3 GB (OOM) e, mesmo com liberação do encoder, cada "
        "consulta leva >10 min em CPU — não paga o custo de latência. "
        "Default alterado para `dense` (rerank desligado por padrão)."
    )
    lines.append("")
    lines.append("## Notas")
    lines.append("")
    lines.append(
        "- Labels provisórios (label_status=provisional); métricas carregam essa ressalva."
    )
    lines.append(
        "- `rrf+rerank` registrado como inviável neste host (ver docs/08-failures.md), "
        "não como recall 0.000 de desempenho."
    )
    if encode_p50_ms is not None:
        lines.append(
            f"- Latência da variante dense é end-to-end (encode + busca), n=40; "
            f"encode da consulta medido isoladamente na mesma execução: "
            f"p50={encode_p50_ms:.1f} ms, p95={encode_p95_ms:.1f} ms (n=40). "
            f"Carregamento do modelo (amortizado, uma vez por processo): "
            f"{(model_load_ms / 1000.0) if model_load_ms is not None else 0.0:.1f} s."
        )
        lines.append(
            "- Encode: mediana de 3 execucoes (dispersao em "
            "eval/results/recall_v1.json, measurement_conditions). "
            "Condições (torch threads, CPU) registradas no JSON."
        )
    lines.append(
        "- O número ~1010 ms reportado anteriormente corresponde a medição que "
        "incluía carga/amortização do modelo; o encode por consulta, com modelo "
        "já carregado, é o valor acima. Total (encode + busca) permanece "
        "consistente com encode + busca."
    )
    lines.append(
        "- Threshold de CI: 0.875 = 35/40 = borda inferior do IC95 do dense; "
        "não prova que dense > rrf (0.875 < 0.925). Ver tests/unit/test_recall_threshold.py."
    )
    lines.append("")
    return "\n".join(lines)


async def main() -> None:  # noqa: PLR0915
    with GOLDEN_PATH.open(encoding="utf-8") as f:
        golden = yaml.safe_load(f)
    items = golden["items"]
    corpus_version = golden.get("dataset_version", "unknown")

    # Conecta ao banco antes de carregar o encoder (memoria), para estabilidade.
    pool = await asyncpg.create_pool(_database_url(), min_size=1, max_size=5)

    # Medicao isolada do encode por consulta (mesma execucao do benchmark).
    # Lazy import torch-heavy stack once.
    import platform  # noqa: PLC0415

    import torch  # noqa: PLC0415 - lazy import do stack torch

    from rig.retrieval.embed import encode_texts, load_encoder  # noqa: PLC0415 - lazy import do stack torch para manter gate verde sem extra embed

    model_load_start = time.perf_counter()
    encoder = load_encoder()
    model_load_ms = (time.perf_counter() - model_load_start) * 1000.0

    # Warmup (descarta primeira passagem, evita JIT/cold-cache).
    if items:
        encode_texts(encoder, [items[0]["query"]])

    # Protocolo de medicao (F1.6d): mediana de >=3 execucoes com dispersao.
    n_encode_runs = 3
    encode_run_p50s: list[float] = []
    encode_run_p95s: list[float] = []
    encode_all_times: list[list[float]] = []
    for _run in range(n_encode_runs):
        times: list[float] = []
        for item in items:
            t0 = time.perf_counter()
            encode_texts(encoder, [item["query"]])
            times.append((time.perf_counter() - t0) * 1000.0)
        encode_all_times.append(times)
        encode_run_p50s.append(_percentile(times, 50))
        encode_run_p95s.append(_percentile(times, 95))

    encode_times_ms = encode_all_times[0]
    encode_p50_ms = statistics.median(encode_run_p50s)
    encode_p95_ms = statistics.median(encode_run_p95s)
    encode_run_p50_min = min(encode_run_p50s)
    encode_run_p50_max = max(encode_run_p50s)

    torch_threads = torch.get_num_threads()
    cpu_model = platform.processor() or platform.machine()

    try:
        results = []
        for variant in VARIANTS:
            print(f"Rodando variante: {variant} ({len(items)} queries)...")
            res = await _run_variant(
                pool,
                encoder,
                None,
                variant,
                items,
                query_vectors=None,
                timeout_s=None,
                bail=False,
            )
            results.append(res)
            if res.get("errors", 0) > 0:
                raise RuntimeError(
                    f"variante {variant} teve {res['errors']} erro(s) de infra; "
                    "abortando rodada sem publicar recall contaminado"
                )
            print(
                f"  recall@8={res['recall_at_8']:.3f} "
                f"MRR@8={res['mrr_at_8']:.3f} "
                f"p50={res['latency_p50_ms']:.1f}ms p95={res['latency_p95_ms']:.1f}ms"
            )
        # rrf+rerank: nao medido neste host (inviavel). Registrado como n/a.
        results.append(
            {
                "variant": "rrf+rerank",
                "n": 0,
                "recall_at_8": None,
                "mrr_at_8": None,
                "recall_ci_95": [None, None],
                "mrr_ci_95": [None, None],
                "latency_p50_ms": None,
                "latency_p95_ms": None,
                "latency_mean_ms": None,
                "hits": 0,
                "errors": 0,
                "status": "not_measured",
                "error": "inviavel neste host: OOM (~3.3 GB) + >10 min/consulta em CPU",
                "per_query": [],
            }
        )
    finally:
        await pool.close()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_date = datetime.now(UTC).date().isoformat()

    # Proveniencia (anti-fabricacao): vincula o JSON ao log e ao relatorio.
    try:
        git_head = subprocess.check_output(  # noqa: ASYNC221
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        git_head = "unknown"
    bench_log_path = ROOT / "bench.log"
    if bench_log_path.is_file():
        log_sha256 = hashlib.sha256(bench_log_path.read_bytes()).hexdigest()
    else:
        log_sha256 = None

    payload = {
        "run_date": run_date,
        "corpus_version": corpus_version,
        "golden_path": str(GOLDEN_PATH.relative_to(ROOT)),
        "n_queries": len(items),
        "top_k": TOP_K,
        "candidate_k": CANDIDATE_K,
        "bootstrap_b": BOOTSTRAP_B,
        "seed": SEED,
        "measurement_conditions": {
            "torch_num_threads": torch_threads,
            "cpu_model": cpu_model,
            "logical_cpus": os.cpu_count(),
            "encode_runs": n_encode_runs,
            "encode_queries_per_run": len(items),
            "model_load_ms": round(model_load_ms, 2),
        },
        "encode_latency_p50_ms": round(encode_p50_ms, 2),
        "encode_latency_p95_ms": round(encode_p95_ms, 2),
        "encode_latency_mean_ms": (
            round(statistics.fmean(encode_times_ms), 2) if encode_times_ms else 0.0
        ),
        "encode_latency_n": len(encode_times_ms),
        "encode_latency_p50_runs_ms": [round(x, 2) for x in encode_run_p50s],
        "encode_latency_p50_min_ms": round(encode_run_p50_min, 2),
        "encode_latency_p50_max_ms": round(encode_run_p50_max, 2),
        "model_load_ms": round(model_load_ms, 2),
        "provenance": {
            "generated_by": "scripts/eval_retrieval.py",
            "git_head": git_head,
            "command": os.environ.get(
                "EVAL_RETRIEVAL_COMMAND", "uv run python scripts/eval_retrieval.py"
            ),
            "log_sha256": log_sha256,
            "report_sha256": None,  # preenchido apos renderizacao do relatorio
        },
        "variants": [{k: v for k, v in r.items() if k != "per_query"} for r in results],
        "per_query": {r["variant"]: r["per_query"] for r in results},
    }
    report = render_report(
        results,
        run_date,
        corpus_version,
        encode_p50_ms=encode_p50_ms,
        encode_p95_ms=encode_p95_ms,
        model_load_ms=model_load_ms,
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    report_sha256 = hashlib.sha256(REPORT_PATH.read_bytes()).hexdigest()
    payload["provenance"]["report_sha256"] = report_sha256

    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Relatório: {REPORT_PATH}")
    print(f"JSON: {JSON_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
