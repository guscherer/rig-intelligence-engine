# 07 — Roadmap e critérios de pronto

Cada fase termina em commit verde + entrada no README. Nenhuma fase "80% pronta".

## F0 — Ingestão real (1,5 dia)

**Entrega:** `make ingest` baixa e indexa proposições reais da Câmara, com chunking hierárquico e manifesto de corpus.

- [ ] `camara_client` com paginação, retry/backoff, cursor e cache
- [ ] Extração PDF (PyMuPDF) + detecção de scan + limpeza de cabeçalho
- [ ] Chunker com breadcrumb; 100% dos chunks com `kind` válido
- [ ] Testes com **fixtures** de PDF real (2 proposições pequenas commitadas com atribuição)
- [ ] `data/manifest.json` gerado; ingestão idempotente (rodar 2× não duplica)
- [ ] Métrica real registrada: nº de docs, nº de chunks, tempo de ingestão

**Pronto quando:** `pytest tests/ingestion` verde e o manifesto mostra contagem real (não estimada) no README.

## F1 — Retrieval híbrido (1,5 dia)

**Entrega:** `make search "reforma tributária"` devolve dispositivos com breadcrumb e score.

- [ ] pgvector + `immutable_unaccent` + coluna `tsvector` gerada
- [ ] Dense + FTS + RRF + rerank local
- [ ] Filtros de metadado antes do ANN
- [ ] Golden set de retrieval v1 (40 consultas rotuladas)
- [ ] Tabela comparativa dense / sparse / RRF / +rerank no relatório
- [ ] Teste de recall@8 com threshold no CI

**Pronto quando:** existe tabela de recall@8 por variante, com números medidos, e uma decisão escrita sobre manter ou não o híbrido.

## F2 — Grafo e redação (2 dias)

**Entrega:** `make run --id 2487262` produz uma minuta em Markdown, no disco, com citações.

- [ ] `RIGState` strict + `BudgetState` testado
- [ ] Nós `triage`, `retrieve`, `positioning`, `draft` com saídas tipadas
- [ ] Validação de `evidence_spans` como substring literal (teste adversarial)
- [ ] Parser de citações: frase factual sem `[C]` é rejeitada localmente
- [ ] Gate de orçamento e deadline (teste que força estouro)
- [ ] LLM mockado nos testes unitários; chamada real só nos testes `@pytest.mark.live`

**Pronto quando:** o PL 2338/2023 gera minuta coerente e o custo real do run está registrado.

## F3 — Auditoria (1,5 dia)

**Entrega:** nenhuma minuta sai sem `AuditReport`; os 15 casos adversariais passam.

- [ ] 6 regras duras determinísticas
- [ ] NLI por sentença com `temperature=0`
- [ ] Política de bloqueio implementada como tabela (testada linha a linha)
- [ ] Loop de reparo com `needed_fix` (máx. 2), testado com falha injetada
- [ ] `docs/08-failures.md` com ≥3 falhas reais encontradas durante o desenvolvimento

**Pronto quando:** `pytest tests/adversarial` verde e o relatório mostra a taxa de `UNSUPPORTED` antes/depois do reparo.

## F4 — HITL no Slack (1 dia)

**Entrega:** card no Slack com botões; aprovar/ajustar/rejeitar grava estado e regenera.

- [ ] App Slack em workspace de teste (ou `slack_sdk` mock com payloads reais gravados)
- [ ] HMAC + janela de 5 min + idempotência (teste de replay)
- [ ] Máquina de estados com transições inválidas → 409
- [ ] Modal de ajuste → `revision_notes` → regeneração
- [ ] `diff_ratio` calculado e persistido

**Pronto quando:** um ciclo completo acontece em vídeo de 60 s, com o texto mudando por causa do comentário.

## F5 — Avaliação e relatório (1,5 dia)

**Entrega:** `make eval` com relatório, CI e baseline commitada.

- [ ] Golden sets v1 (triagem 120, retrieval 40, draft 20)
- [ ] Ragas + juiz de tom + validação de concordância do juiz
- [ ] Bootstrap CI em toda proporção
- [ ] Gates de CI (smoke e completo)
- [ ] `reports/` commitado com o primeiro resultado real
- [ ] README atualizado **só** com números medidos

**Pronto quando:** o README tem tabela de resultados com CI e a frase "medido em <data>, corpus v1, n=…".

## F6 — Embalagem (1 dia)

- [ ] `docker compose up` sobe tudo em máquina limpa (testado em WSL2 limpo)
- [ ] `.env.example` completo; nenhum segredo no repo
- [ ] README com diagrama, resultados, limitações
- [ ] Vídeo de 90 s: radar → card → ajuste → nova versão
- [ ] `LICENSE` (MIT para código; nota separada sobre corpus de terceiros)

## Se o tempo apertar

Corte na ordem abaixo — do menos para o mais importante:

1. Teams, Salesforce, Prometheus (F6) — infraestrutura decorativa.
2. Juiz de tom (F5) — Ragas + regras duras já provam fidelidade.
3. `positioning` (F2) — pode virar recuperação simples sem brief tipado.
4. Slack (F4) — CLI com `approve/adjust/reject` + diff já demonstra HITL.

**Nunca cortar:** auditoria (F3), números medidos (F5), dados reais (F0). São os três diferenciais; o resto é embalagem.

## Marcos de verificação

| Marco | Critério |
|---|---|
| "Dá para mostrar" | F0+F1+F2: minuta real com citações que resolvem |
| "Dá para confiar" | F3: adversarial verde, bloqueio funcionando |
| "Dá para usar" | F4: ciclo humano completo |
| "Dá para contratar" | F5+F6: números, CI, demo, README |
