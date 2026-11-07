# Benchmark de retrieval — recall@8 por variante (F1.5)

- Data da execução: 2026-11-07
- Versão do corpus (golden set): `cam-2026-11-06`
- Golden set: `eval/golden/retrieval_v1.yaml` (40 consultas, provisional)
- Top-k: 8; candidate-k: 50
- IC 95% por bootstrap (B=2000, seed=42)

## Tabela comparativa

| Variante | recall@8 | IC95 recall | MRR@8 | IC95 MRR | p50 | p95 | hits |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.950 | [0.875, 1.000] | 0.673 | [0.564, 0.778] | 75.6 | 83.4 | 38/40 |
| sparse | 0.375 | [0.225, 0.525] | 0.302 | [0.181, 0.438] | 1.3 | 1.7 | 15/40 |
| rrf | 0.925 | [0.825, 1.000] | 0.687 | [0.574, 0.798] | 73.9 | 79.1 | 37/40 |
| rrf+rerank | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Decisão

Variante escolhida: **dense** (recall@8=0.950, MRR@8=0.673, p50=75.6ms, p95=83.4ms).

Decisão: o híbrido (RRF) não supera o denso puro de forma estatisticamente relevante (dense recall@8=0.950, IC95 [0.875, 1.000] vs. rrf 0.925, IC95 [0.825, 1.000] — intervalos sobrepostos, n=40). O rerank (cross-encoder) é inviável neste host: tentou alocar ~3,3 GB (OOM) e, mesmo com liberação do encoder, cada consulta leva >10 min em CPU — não paga o custo de latência. Default alterado para `dense` (rerank desligado por padrão).

## Notas

- Labels provisórios (label_status=provisional); métricas carregam essa ressalva.
- `rrf+rerank` registrado como inviável neste host (ver docs/08-failures.md), não como recall 0.000 de desempenho.
- Threshold de CI gravado em tests/ (ver comentário no teste) a partir do recall@8 da variante escolhida.
