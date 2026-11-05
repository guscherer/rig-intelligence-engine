# 01 — Arquitetura

## 1. Topologia de execução

Dois planos separados, de propósito:

```
┌──────────────────── PLANO OFFLINE (batch) ────────────────────┐
│  ingest_worker                                                │
│    camara_client ──► normalizer ──► pdf_extract ──► chunker   │
│         │                                              │      │
│         └──► metadata ───────────────────────────────► │      │
│                                              embed ─────┤      │
│                                                        ▼      │
│                                          Postgres 16          │
│                                    (pgvector + tsvector)      │
└───────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────── PLANO ONLINE (request) ───────────┐
│  FastAPI (async)                                              │
│    POST /runs            ──► enqueue ──► arq worker           │
│    GET  /runs/{id}       ──► status, trace, custo             │
│    POST /runs/{id}/feedback                                   │
│    POST /slack/interactions  (assinado, idempotente)          │
│                                                               │
│  worker: LangGraph                                            │
│    triage → retrieve → positioning → draft → audit → emit      │
│                          ▲                │                   │
│                          └── repair ◄─────┘ (máx. 2 ciclos)    │
└───────────────────────────────────────────────────────────────┘
```

Por que batch separado do request: o grafo leva 30–60 s e consome 15–40k tokens. Segurar uma conexão HTTP para isso é fragilidade gratuita, e um worker permite retomar run após restart. `arq` (Redis) é o mínimo viável; `BackgroundTasks` fica como modo `dev` para rodar sem Redis.

## 2. Componentes

| Componente | Responsabilidade | Não faz |
|---|---|---|
| `ingestion.camara_client` | Paginação, retry, backoff, cursor incremental | Não interpreta texto |
| `ingestion.pdf` | Extração PyMuPDF, detecção de scan, limpeza de cabeçalho | Não decide chunk |
| `ingestion.chunker` | Segmentação por hierarquia legal, breadcrumb, hash estável | Não gera embedding |
| `retrieval.hybrid` | Dense + FTS + fusão RRF + filtros de metadado | Não decide se o resultado é suficiente |
| `retrieval.rerank` | Cross-encoder local sobre top-50 → top-8 | — |
| `agents.graph` | Orquestração, estado, orçamento, retry | Não faz I/O de rede direto |
| `agents.nodes.*` | Uma decisão por nó, uma saída tipada | Não chama outro nó |
| `audit.verifier` | Checagem por sentença, regras determinísticas, política de bloqueio | Não reescreve texto |
| `integrations.slack` | Block Kit, HMAC, callback idempotente | Não guarda estado de negócio |
| `eval.harness` | Golden set, Ragas, juiz de tom, adversarial | Não roda em produção |

## 3. Estado do grafo

Um único objeto Pydantic atravessa o grafo. Nós recebem o estado inteiro e devolvem **apenas as chaves que mudam** (contrato do reducer do LangGraph). Sem `dict` solto: `mypy --strict` precisa pegar erro de campo.

```python
class RIGState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    proposition: Proposition
    mandate: MandateMap

    triage: TriageResult | None = None
    retrieved: list[RetrievedChunk] = []
    position: PositioningBrief | None = None
    draft: Draft | None = None
    audit: AuditReport | None = None

    repair_cycle: int = 0  # corta em 2
    revision_notes: list[str] = []  # vem do humano, entra no draft
    budget: BudgetState  # tokens, custo, deadline
    errors: list[NodeError] = []
    trace: list[NodeSpan] = []
```

`BudgetState` é verificado em **toda** entrada de nó: se `cost_usd > limit` ou `deadline` estourou, o grafo desvia para `emit_partial`, que entrega o que existe marcado como incompleto. Nunca um run morre por timeout de provedor no meio da redação.

## 4. Fluxo, passo a passo

1. **`triage`** — recebe ementa, keywords, temas, autores, tramitação. Consulta o mapa de mandato por regra (match lexical + tema) → shortlist. Se não bate em nenhum eixo, o run termina em `SKIPPED_LOW_RELEVANCE` e não gasta LLM. Se bate, chama modelo barato com rubrica e exige `evidence_spans` (trechos literais da ementa/keywords). Score = `sensibilidade_eixo × magnitude × urgência`, calculado em Python, não pelo modelo. *O modelo classifica; o código pontua.*
2. **`retrieve`** — decompõe a consulta em até 3 sub-consultas (dispositivo, tema, ator afetado), roda híbrido, deduplica por `chunk_id`, reranqueia. Guarda `retrieval_confidence` (score do melhor cross-encoder) para o auditor saber se o problema é de geração ou de acervo.
3. **`positioning`** — busca no corpus institucional (posições anteriores, diretrizes, linhas vermelhas). Produz `PositioningBrief` com `prior_stances[]`, `guidelines[]`, `red_lines_hit[]`. Se `red_lines_hit` não está vazio → curto-circuito para recusa, sem redigir.
4. **`draft`** — redige seções conforme template do formato escolhido. Cada frase factual precisa terminar com `[C<n>]`; o parser rejeita frase factual sem citação antes mesmo de chegar ao auditor. Few-shot com 3 notas reais anonimizadas.
5. **`audit`** — três camadas: (a) regras determinísticas (artigo citado existe? data/número batem? há citação órfã?), (b) NLI por sentença contra os spans citados, (c) checagem global (há afirmação quantitativa sem fonte? há promessa de resultado? há linguagem de parecer jurídico?). Saída: `AuditReport` com veredito por claim e lista de reparos endereçáveis.
6. **`repair`/`draft`** — se `UNSUPPORTED` e `repair_cycle < 2`, volta ao `draft` com `revision_notes` específicas ("frase 4 cita Art. 12, mas o Art. 12 trata de prazos; remova ou recite o Art. 9º"). Instrução cirúrgica, não "melhore o texto".
7. **`emit`** — persiste `Draft` + `AuditReport`, publica no Slack com resumo e botões. Estado `IN_REVIEW`.

## 5. Modos de falha (o que o sistema faz quando dá errado)

Falha prevista é requisito. Cada linha abaixo vira teste em `tests/integration/`.

| Falha | Detecção | Comportamento |
|---|---|---|
| Câmara offline / 5xx | retry 3× com backoff exponencial + jitter | run fica `PENDING`, cursor não avança, alerta no log estruturado |
| PDF escaneado sem texto | densidade de texto < 100 chars/página | marca `extraction_quality=low`, exclui do RAG, enfileira OCR |
| Chunk sem breadcrumb | parser não encontra `Art.` | mantém como `preambulo`, nunca como artigo — evita citação falsa |
| Retrieval vazio | `retrieval_confidence < 0.35` | não redige; emite `INSUFFICIENT_BASE` com o que faltou buscar |
| LLM devolve JSON inválido | validação Pydantic + 1 repair prompt | 2ª falha → `FAILED_VALIDATION`, sem texto parcial no Slack |
| Claim sem lastro após 2 reparos | auditoria | emite com banner `BLOQUEADO — revisão obrigatória` e lista as frases; nunca "passa batido" |
| Provedor 429/limite | contador de budget | backoff; se estourar deadline → `emit_partial` |
| Callback do Slack duplicado | `idempotency_key` = `hash(run_id, action, reviewer, nonce)` | segunda chamada retorna 200 sem efeito |
| Assinatura HMAC inválida | verificação `v0=` | 401, log de segurança, sem detalhe na resposta |
| Texto legislativo com instrução embutida ("ignore as regras acima") | delimitador + hierarquia de instrução + validação de saída | tratado como dado; se o modelo obedecer, a auditoria de formato e de escopo pega |

## 6. Requisitos não-funcionais

| Requisito | Alvo | Como é medido |
|---|---|---|
| Latência p95 ponta a ponta (triagem → card) | ≤ 90 s | span OTel por nó, histograma Prometheus |
| Custo por minuta | ≤ US$ 0,15 em regime de iteração | tabela de preço por modelo × tokens registrados |
| Determinismo degradável | `temperature=0` na auditoria e na triagem | teste de repetição 3× no golden set reduzido |
| Isolamento de segredo | nenhuma chave em log, trace ou resposta | teste que varre payload de trace por padrões `AIza`/`sk-` |
| Reindexação | corpus completo em ≤ 20 min single-node | benchmark em `make ingest-full` |

## 7. Limites assumidos

- Um processo, um Postgres. Sem sharding: o corpus alvo (~6k proposições/ano + 300 docs institucionais) cabe em < 2 M chunks, que pgvector HNSW aguenta com folga.
- Sem multi-tenant. O mapa de mandato é único por deploy; multi-empresa é evolução declarada, não implementada.
- Sem fine-tuning. Prompt + few-shot + RAG cobrem o caso; fine-tuning sem dataset rotulado grande é teatro.
- Sem agente que "decide sozinho" o que fazer. O grafo é fixo e auditável. Autonomia aberta em domínio regulatório é risco, não feature.
