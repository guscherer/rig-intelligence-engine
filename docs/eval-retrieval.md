# Benchmark de retrieval — recall@8 por variante (F1.5)

- Data da execução: 2026-11-07
- Versão do corpus (golden set): `cam-2026-11-06`
- Golden set: `eval/golden/retrieval_v1.yaml` (40 consultas, provisional)
- Top-k: 8; candidate-k: 50
- IC 95% por bootstrap (B=2000, seed=42)
- n=40 consultas; granularidade do recall = 2,5 p.p./consulta

## Tabela comparativa

| Variante | recall@8 | IC95 recall | MRR@8 | IC95 MRR | p50 | p95 | hits | errors |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.950 | [0.875, 1.000] | 0.673 | [0.564, 0.778] | 201.1 | 267.6 | 38/40 | 0 |
| sparse | 0.375 | [0.225, 0.525] | 0.302 | [0.181, 0.438] | 1.1 | 1.6 | 15/40 | 0 |
| rrf | 0.925 | [0.825, 1.000] | 0.687 | [0.574, 0.798] | 70.0 | 76.5 | 37/40 | 0 |
| rrf+rerank | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0 |

## Decisão

Variante escolhida: **dense** (recall@8=0.950, MRR@8=0.673, p50=201.1ms, p95=267.6ms).

Decisão: empate estatístico em n=40 (dense recall@8=0.950, IC95 [0.875, 1.000] vs. rrf 0.925, IC95 [0.825, 1.000] — diferença de uma consulta, intervalos sobrepostos). O híbrido (RRF) não supera o denso de forma estatisticamente relevante, e a afirmação recíproca também seria verdadeira. Mantém-se `dense` como default pela justificativa operacional: o encode da consulta já está no caminho, eliminar BM25+RRF reduz superfície de manutenção e latência de operação. O rerank (cross-encoder) é inviável neste host: tentou alocar ~3,3 GB (OOM) e, mesmo com liberação do encoder, cada consulta leva >10 min em CPU — não paga o custo de latência. Default alterado para `dense` (rerank desligado por padrão).

## Notas

- Labels provisórios (label_status=provisional); métricas carregam essa ressalva.
- `rrf+rerank` registrado como inviável neste host (ver docs/08-failures.md), não como recall 0.000 de desempenho.
- Latência da variante dense é end-to-end (encode + busca), n=40; encode da consulta medido isoladamente na mesma execução: p50=201.1 ms, p95=267.6 ms (n=40, mediana de 3 execuções: 201.08/202.22/201.01 ms). Carregamento do modelo (amortizado, uma vez por processo): 6.5 s.
- O número ~1010 ms reportado anteriormente corresponde a medição que incluía carga/amortização do modelo; o encode por consulta, com modelo já carregado, é o valor acima. Total (encode + busca) permanece consistente com encode + busca.
- Threshold de CI: 0.875 = 35/40 = borda inferior do IC95 do dense; não prova que dense > rrf (0.875 < 0.925). Ver tests/unit/test_recall_threshold.py.
