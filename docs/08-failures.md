# 08 — Registro de falhas

Este arquivo nasce vazio de propósito. Cada linha entra **depois** de observada em execução, com o caso reproduzível em `tests/adversarial/` e o link para o commit que fechou.

Regra: se uma falha foi encontrada e não está aqui, o registro está incompleto. `docs/FAILURES.md` é o documento que separa "testei" de "funciona".

## Formato

```markdown
### F-00X — <título curto>

- **Data:** AAAA-MM-DD
- **Fase:** F0..F6
- **Sintoma:** o que apareceu, com trecho literal da saída
- **Impacto:** o que o usuário teria recebido de errado
- **Causa raiz:** por que aconteceu (não "o modelo alucinou" — o mecanismo)
- **Correção:** o que mudou (arquivo/commit)
- **Caso de teste:** `tests/adversarial/test_xxx.py::test_yyy`
- **Residual:** o que ainda não está coberto
```

## Registro

### F-012 — Rerank (cross-encoder) inviável neste host

- **Data:** 2026-11-07
- **Fase:** F1
- **Sintoma:** `rrf+rerank` tentou alocar ~3,3 GB (`DefaultCPUAllocator: not enough memory: tried to allocate 3288929408 bytes`), derrubou o WSL/Postgres (37x `WinError 1225`) e cada consulta levou >10 min em CPU mesmo com liberação do encoder. Zero hits não é recall; é ausência de medição.
- **Impacto:** variante `rrf+rerank` não medida (n/a), não entra na comparação. Default de busca alterado para `dense` (rerank desligado por padrão).
- **Causa raiz:** cross-encoder bge-reranker-v2-m3 + bge-m3 não cabem juntos neste host (~5 GB com torch/WSL); mesmo isolado, inferência por consulta é proibitivamente lenta em CPU.
- **Correção:** `src/rig/retrieval/search.py` (`run_search` default `dense`); `docs/eval-retrieval.md` registra `n/a` com evidência.
- **Caso de teste:** `tests/unit/test_recall_threshold.py` (threshold da variante escolhida).
- **Residual:** rerank pode ser reavaliado em host com GPU ou modelo menor; fora do escopo do F1.

Registrado em 2026-11-05 após fechamento da F0: nenhuma falha real observada durante F0.1–F0.5 (CamaraClient, extração PDF, chunker, schema/store, fixtures E2E). Suíte `tests/ingestion` verde; `make check` verde.

<!--
Modelos de falhas que a spec já antecipa e que serão registradas quando ocorrerem:
- F-001 PDF escaneado gerando chunk vazio e citação fantasma
- F-002 `evidence_span` que é paráfrase, não substring (validação falhando corretamente)
- F-003 breadcrumb errado em texto com "Art. 1º" citando outro artigo dentro do corpo
- F-004 rerank local derrubando dispositivo correto por score de cross-encoder
- F-005 juiz de tom premiando texto vazio/curto
- F-006 injeção embutida em ementa tentando alterar o veredito da triagem
- F-007 custo estourando por loop de reparo não contabilizado
-->

### F-008 — Colisão de porta mascarada (Postgres nativo sem pgvector)

- **Data:** 2026-11-06
- **Fase:** F1
- **Sintoma:** ingestão rodou com "sucesso" (766 docs, idempotência OK) mas gravou num PostgreSQL 18.6 nativo do Windows escutando em `127.0.0.1:5432`, sem pgvector. `chunks.embedding` virou `bytea` e o índice HNSW não existia. Nenhum erro foi levantado.
- **Impacto:** corpus aparentemente populado, mas sem embeddings/vetores; reindexação e busca densa impossíveis; falso positivo de sucesso.
- **Causa raiz:** pipeline não validava que o alvo tinha o schema esperado (extensão `vector`, coluna `vector`). O proxy do WSL perdia para o servidor nativo na mesma porta.
- **Correção:** validação de arranque que falha rápido se `chunks.embedding` não for `vector` ou se `vector` não estiver entre as extensões (a implementar em F1.2/F1.3); confirmar alvo com `SELECT count(*)` + tipo da coluna.
- **Caso de teste:** `tests/integration/test_ingest_e2e.py` (a ser estendido com checagem de tipo de coluna).
- **Residual:** validação ainda não automatizada no código; depende de operação manual.

### F-009 — Cursor grosseiro impede retomada

- **Data:** 2026-11-06
- **Fase:** F1
- **Sintoma:** `update_cursor` só chamado no fim de um escopo (`tipo:ano`). Execução morrendo no meio reprocessava o escopo inteiro; retomada de `PL:2023` (275+ docs) ficou em ~1 doc/min por re-baixar e re-parsear tudo.
- **Impacto:** retomada lenta, desperdício de rede/CPU, risco de reprocessamento duplicado.
- **Causa raiz:** granularidade do cursor por escopo, não por documento/página.
- **Correção:** gravar `last_id` incrementalmente (a cada N docs) ou por página.
- **Caso de teste:** `tests/integration/test_ingest_e2e.py` (retomada após interrupção).
- **Residual:** não implementado neste card; registrado para F1.1/F1.6.

### F-010 — Falha de lote não isolada no backfill

- **Data:** 2026-11-06
- **Fase:** F1
- **Sintoma:** `_process_batch` capturava exceção e marcava `failed += len(batch)` (lote de 32). Resultado: `total=2429 embedded=2269 failed=160 duration=20443.06s`; 160 pendentes = 5 lotes, não 160 textos ruins (150 com caracteres de controle; maior chunk 20423 chars, limite bge-m3 8192).
- **Impacto:** ~155 textos íntegros não embedados por contaminação de um vizinho ruim; throughput aparente 0.11 chunks/s.
- **Causa raiz:** exceção de um chunk derrubava o lote inteiro; erro engolido sem uso de `exc`.
- **Correção:** fallback por chunk em `_process_batch`/`_process_one` (`src/rig/retrieval/embed.py`): lote tenta encode em bloco; em falha, reprocessa chunk a chunk, registrando `chunk_id` e motivo; chunk problemático é pulado.
- **Caso de teste:** `tests/unit/test_embed.py` (isolamento com encoder falso que falha em texto específico).
- **Residual:** chunks >8192 tokens ainda podem ser lentos; truncagem a avaliar.

### F-011 — Exceção engolida com exit 0 (falso positivo)

- **Data:** 2026-11-06
- **Fase:** F1
- **Sintoma:** exceção capturada e descartada (`exc` nunca usado); CLI retornava 0 mesmo com `failed=160`.
- **Impacto:** falha parcial reportada como sucesso (mesma classe do falso positivo da colisão de porta).
- **Causa raiz:** ausência de propagação de status de falha no CLI.
- **Correção:** `scripts/embed.py` agora retorna 1 quando `failed > 0`, imprime tipo/mensagem + `chunk_id` amostrado em stderr.
- **Caso de teste:** `tests/unit/test_embed.py` (assert exit via stats.failed).
- **Residual:** códigos de saída específicos por tipo de falha não diferenciados.

### F-013 — Artefato de medição ajustado manualmente para satisfazer o esperado

- **Data:** 2026-11-07
- **Fase:** F1
- **Sintoma:** o commit `d835ca6` publicou `docs/eval-retrieval.md` e `eval/results/recall_v1.json` editados à mão em vez de gerados pelo script. Evidências: diff de 48 linhas; `dense.latency_p50_ms` copiado do encode (201,1 ms) sem atualizar a média; `rrf` byte-idêntico à rodada anterior; bloco `measurement_conditions` anexado fora de ordem; `\ No newline at end of file`; ausência de `bench.log` correspondente. No `d835ca6`, `dense.latency_mean_ms` permaneceu **70,42** enquanto `latency_p50_ms` passou a **201,08** — média menor que a mediana é impossível numa distribuição de tempos, e prova que só um dos dois campos foi atualizado.
- **Impacto:** o número fabricado iria para a base do GO do F2 (decisão de variante default), contaminando a justificativa operacional com latência subestimada. Recall permaneceu correto (0,950/0,375/0,925), mas a latência era falsa.
- **Causa raiz:** edição manual do JSON/relatório para "satisfazer o esperado" em vez de medir; ausência de vínculo entre o artefato publicado e o log de execução, e ausência de invariantes que detectassem inconsistência interna (dense > encode, mean ≥ p50, recall recalculável a partir de `per_query`, relatório byte-idêntico ao gerado).
- **Correção:** artefato autêntico recommitado a partir da execução real (bench.log sha256 `caae8a9f881011e1e266e95eb1f241bcd21a1cceb5e5e88ebf0af3ea66d93c62`); bloco `provenance` (`git_head`, `command`, `log_sha256`, `report_sha256`) adicionado ao `payload` de `scripts/eval_retrieval.py`; 4 invariantes em `tests/unit/test_eval_invariants.py`.
- **Caso de teste:** `tests/unit/test_eval_invariants.py::test_dense_latency_exceeds_encode`, `::test_latency_mean_not_below_p50`, `::test_recall_recomputes_from_per_query`, `::test_report_matches_json`, `::test_provenance_hashes_match_files`.
- **Residual:** proveniência depende da existência de `bench.log` no diretório de execução; sem log, `log_sha256` fica `null` e a ligação se quebra (detectável pelo gate).
