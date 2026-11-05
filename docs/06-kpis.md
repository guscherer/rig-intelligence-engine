# 06 — KPIs: o que o negócio vê

Três públicos, três níveis. Cada KPI tem dono, fonte de dados e um jeito de ser contestado.

## 1. Nível produto (analista / revisor)

| KPI | Definição | Alvo | Fonte |
|---|---|---|---|
| **Precisão da fila** | % de itens no top-20 marcados como relevantes pelo analista | ≥ 80% | feedback implícito (abriu / descartou) + golden set |
| **Cobertura** | % de proposições relevantes que apareceram no top-50 | ≥ 85% | golden set |
| **Tempo até o 1º rascunho** | do `dataApresentacao` (ou do run) até card no Slack | ≤ 3 min | `runs.created_at` → `runs.card_sent_at` |
| **Taxa de aprovação sem edição** | `approve` sem `adjust` / total de revisões | ≥ 40% no início (subir com feedback) | `feedback_events` |
| **Esforço de edição** | `diff_ratio` médio no texto aprovado | ≤ 0.25 | diff draft → human_edited |
| **Taxa de bloqueio** | runs `BLOCKED` / runs com minuta | monitorar; nem baixo demais (auditor frouxo) nem alto (sistema inútil) | `audit_reports` |

A taxa de bloqueio é o KPI mais informativo e o mais mal interpretado: 0% é suspeito, 40% é produto quebrado. A leitura correta é a **curva** ao longo das versões, com a taxa de `UNSUPPORTED` caindo e a de `approve` subindo.

## 2. Nível engenharia (custo e confiabilidade)

| KPI | Alvo | Como |
|---|---|---|
| Custo por minuta | ≤ US$ 0,15 (iteração) / ≤ US$ 0,25 (modelo forte) | tokens × preço, por run |
| Latência p95 | ≤ 90 s | spans OTel |
| Taxa de falha de run | ≤ 2% | `runs.status='FAILED'` |
| Taxa de reparo | ≤ 30% dos drafts precisam de 1 reparo | `repair_cycle>0` |
| Cache hit de retrieval | ≥ 20% após 1 mês | chave normalizada de query |
| Custo de ingestão por 1k docs | ≤ US$ 0,40 | embeddings medidos |

## 3. Nível negócio (diretor)

Só três números, e todos são proxies declarados:

| KPI | Como é calculado | Como apresentar |
|---|---|---|
| **Horas de especialista liberadas** | (tempo de redação baseline − tempo de revisão) × nº de minutas | "proxy; baseline de 4–6 h a validar com o time" |
| **Cobertura do radar** | proposições relevantes identificadas / total relevante estimado | com intervalo de confiança |
| **Custo por minuta vs. custo hora-especialista** | razão direta | R$ por minuta vs. R$ por hora |

O que **não** entra: "ROI de 340%", "redução de 80% no tempo". Esses números são inventados em 100% dos decks de IA corporativa e são o primeiro sinal de que o candidato não mediu nada.

## 4. Como os KPIs são instrumentados

- `runs` — uma linha por execução: estado, tokens in/out, custo, latência por nó, `dataset_version`, `model_version`, `prompt_version`.
- `audit_reports` — veredito por claim, para calcular `grounding_rate` e `unsupported_claim_rate` em produção.
- `feedback_events` — ação, revisor, motivo, `diff_ratio`.
- Dashboard: `/metrics` (Prometheus) + um `reports/ops.md` gerado semanalmente a partir do banco.

`prompt_version` é obrigatório: sem isso não se sabe se a queda de qualidade veio do modelo, do corpus ou do prompt. Toda mudança de prompt é um arquivo versionado com hash, não uma string no meio do código.

## 5. Definição de "pronto" para cada KPI

Um KPI só entra no README quando:

1. Existe query reproduzível que o calcula.
2. Existe valor medido sobre o golden set (ou sobre runs reais, quando houver).
3. Existe intervalo de confiança, se a amostra for pequena.
4. Está escrito **como pode estar errado**.

Sem os quatro, fica em `docs/06-kpis.md` como alvo — nunca no README como resultado.
