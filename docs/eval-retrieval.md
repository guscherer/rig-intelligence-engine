# Benchmark de retrieval — recall@8 por variante (F1.5)

- Data da execução: 2026-11-07
- Versão do corpus (golden set): `cam-2026-11-06`
- Golden set: `eval/golden/retrieval_v1.yaml` (40 consultas, provisional)
- Top-k: 8; candidate-k: 50
- IC 95% por bootstrap (B=2000, seed=42)

## Tabela comparativa

| Variante | recall@8 | IC95 recall | MRR@8 | IC95 MRR | p50 | p95 | hits |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.950 | [0.875, 1.000] | 0.673 | [0.564, 0.778] | 78.2 | 85.3 | 38/40 |
| sparse | 0.375 | [0.225, 0.525] | 0.302 | [0.181, 0.438] | 1.2 | 1.8 | 15/40 |
| rrf | 0.925 | [0.825, 1.000] | 0.687 | [0.574, 0.798] | 73.8 | 79.1 | 37/40 |
| rrf+rerank | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Decisão

Variante escolhida: **dense** (recall@8=0.950, MRR@8=0.673, p50=78.2ms, p95=85.3ms).

Decisão: empate estatístico em n=40 (dense recall@8=0.950, IC95 [0.875, 1.000] vs. rrf 0.925, IC95 [0.825, 1.000] — diferença de uma consulta, intervalos sobrepostos). O híbrido (RRF) não supera o denso de forma estatisticamente relevante, e a afirmação recíproca também seria verdadeira. Mantém-se `dense` como default pela justificativa operacional: o encode da consulta já está no caminho, eliminar BM25+RRF reduz superfície de manutenção e latência de operação. O rerank (cross-encoder) é inviável neste host: tentou alocar ~3,3 GB (OOM) e, mesmo com liberação do encoder, cada consulta leva >10 min em CPU — não paga o custo de latência. Default alterado para `dense` (rerank desligado por padrão).

## Notas

- Labels provisórios (label_status=provisional); métricas carregam essa ressalva.
- `rrf+rerank` registrado como inviável neste host (ver docs/08-failures.md), não como recall 0.000 de desempenho.
- Latência (p50/p95) é end-to-end: inclui o encode da consulta (main() passa query_vectors=None; o vetor é calculado dentro da janela cronometrada), n=40. Não há medição separada de encode neste run.
- Threshold de CI gravado em tests/ (ver comentário no teste) a partir do recall@8 da variante escolhida.
