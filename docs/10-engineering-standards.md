# 10 — Padrões de engenharia

Documento normativo. O que está aqui é verificável por ferramenta ou por revisão; o que não é verificável não entra.

## 1. Fronteira de deploy: um binário, dois processos

**Decisão:** monólito modular. Sem microserviços. Razão completa em [ADR-010](09-decisions.md).

```
Processo 1: rig-api      (FastAPI, request curto: enfileira e consulta estado)
Processo 2: rig-worker   (arq, job longo: grafo de 30-60 s)
Imagem única, comando diferente.
```

Fronteiras de pacote que **seriam** as dos serviços, se um dia fossem extraídos:

| Pacote | Interface pública | Pode importar |
|---|---|---|
| `rig.core` | modelos, config, db, telemetria | nada interno |
| `rig.adapters` | providers (`StructuredGenerator` + SDK) | core |
| `rig.ingestion` | `CamaraClient`, `chunk_document` | core |
| `rig.retrieval` | `HybridSearch.search(query) -> list[RetrievedChunk]` | core |
| `rig.audit` | `audit_draft(draft, chunks) -> AuditReport` | core |
| `rig.integrations` | `ReviewChannel` (protocolo) + adapters | core |
| `rig.graph` | estado tipado, nós, runner (`run_pipeline`) | adapters, retrieval, audit, core |
| `rig.agents` | shim de compatibilidade (re-exporta `rig.graph.state`) | graph (deprecated; canônico é `rig.graph`) |
| `rig.api` | routers | tudo abaixo |
| `rig.eval` | harness | tudo (ninguém importa `eval`) |

Regras que o CI verifica (`.importlinter`):

1. Camadas só descem: `eval → api → agents → (ingestion | retrieval | audit | integrations) → core` (mais as camadas do grafo: `graph → (adapters | retrieval | audit) → core`).
2. Nenhum módulo de produção importa `rig.eval`.
3. `rig.agents` não importa `rig.ingestion` — agente recebe proposição pronta; buscar dado é do plano offline. `rig.graph` segue a mesma regra (não importa `rig.ingestion`) e também não importa `rig.api`/`rig.eval`/`rig.integrations`.
4. `rig.adapters` é folha: só `rig.core` (e libs externas). SDK de provedor não sai de `adapters/`.

**Quando extrair de verdade** (critério declarado, não estético): ingestão acima de 30 min competindo por CPU com a geração; corpus acima de 50 M chunks; segundo consumidor do retrieval. Antes disso, extração é custo sem retorno.

## 2. Limites de tamanho

LOC por arquivo é **sinal**, não objetivo. O critério que vale é: quantos saltos até entender uma run.

| Alvo | Brando | Duro | Verificação |
|---|---|---|---|
| Função | 40 linhas | 60 (`PLR0915`) | **gate** |
| Complexidade ciclomática | — | 10 (`C901`) | **gate** |
| Parâmetros | 5 | 8 (`PLR0913`) → usar Pydantic model | **gate** |
| Aninhamento | 3 | 4 (`PLR0912`) | **gate** |
| Classe | 200 | 300 | revisão |
| Módulo | 400 | 600 **com justificativa no docstring** | revisão |
| Arquivo de teste | sem limite | — | — |

Exceções legítimas e esperadas (documentar no topo do arquivo):

- `audit/hard_rules.py` — tabela de regras; será grande e está correto.
- `prompts/*.py` — catálogo de texto, não lógica.
- `core/models.py` — schemas Pydantic agregados.
- migrations.

Justificativa aceitável: *"este arquivo é grande porque é uma tabela de X"*. Inaceitável: *"estava com pressa"*.

## 3. Estilo: o que é lei e o que é dogma rejeitado

**Lei:**

- Nome revela intenção, no vocabulário do domínio: `unsupported_claims`, `breadcrumb`, `red_line_hit`.
- Uma função = um nível de abstração.
- Comentário explica **por que**, nunca o quê.
- Erro explícito nas bordas do sistema; exceção de domínio (`ChannelError`, `InsufficientBaseError`) em vez de `ValueError` genérico.
- Sem código morto, sem parâmetro booleano de configuração (`def draft(strict: bool)` → duas funções ou um enum).
- `print` proibido em `src/` (ruff `T20`); `structlog` sempre.

**Dogma rejeitado, com motivo:**

| Prática comum | Por que não aqui |
|---|---|
| "Máximo 3 parâmetros" | 6 campos relacionados = 1 Pydantic model tipado. Melhor em tipo, validação e teste. |
| "Sem comentários, o código fala" | Parte do porquê é regulatória. Ex.: número é comparado por igualdade de **string** porque `"90"` e `"90,0"` no texto legal são o mesmo número e um float perderia o rastro da fonte. Sem comentário, alguém "conserta" e quebra a auditoria. |
| "Tudo vira classe" | Pipeline é função pura sobre estado tipado. Classe só onde há estado real (sessão HTTP, credencial, conexão). |
| "DRY sempre" | Duas regras de auditoria parecidas ficam duplicadas até a terceira aparecer. Abstração prematura em regra de negócio custa mais que duplicação. |

## 4. SOLID aplicado — com o anti-exemplo de cada letra

| | Decisão | Anti-exemplo que o revisor deve barrar |
|---|---|---|
| **S** | `audit/` separado em `hard_rules` (regra legal), `nli` (modelo), `global_checks` (escopo), `policy` (bloqueio). Quatro razões de mudança independentes. | `DocumentService` que ingere, redige e audita. |
| **O** | `FORMATS` registry: novo formato = nova classe + entrada. Zero `if` em `draft.py`. | `if formato == "nota": ... elif formato == "memorando": ...` |
| **L** | Todo `ReviewChannel` levanta `ChannelError` e respeita idempotência. Slack e CLI são substituíveis sem `try/except` específico. | Adapter que vaza `SlackApiError` e obriga o chamador a importar `slack_sdk`. |
| **I** | Três protocols estreitos: `StructuredGenerator`, `Embedder`, `Judge`. | `LLMClient` com 12 métodos; fake de teste com 12 stubs. |
| **D** | Nós recebem protocols; composition root único em `app/container.py`; SDK do provedor só em `adapters/`. | `import google.genai` dentro de um nó do grafo. |

**Contenção obrigatória do DIP:** protocolo só existe onde há **2ª implementação real** ou onde o **teste exige**. Proibido: `ClockProtocol`, `UUIDProvider`, `ConfigProvider`, `LoggerFactory`. Abstração sem variação é ruído.

## 5. Onde os princípios brigam — e quem desempata

| Tensão | Desempate |
|---|---|
| SRP vs. profundidade | SRP conta **razão de mudança** (quem pede a alteração), não verbo. "Valida", "formata" e "salva" no mesmo módulo podem ser uma só responsabilidade se mudam juntos. |
| OCP vs. YAGNI | Registry só com a 2ª variante existente. Antes, `if` é honesto. |
| DIP vs. legibilidade | Cada protocolo custa um salto no debugger. Teste de aceitação: seguir uma run do request ao card em **≤ 3 saltos**. |

## 6. Enforcement

| Regra | Ferramenta | Falha o build? |
|---|---|---|
| Complexidade, tamanho de função, parâmetros | `ruff` (`C901`, `PLR09xx`) | sim |
| Bug provável (`B`), async esquecido (`ASYNC`), segurança (`S`), import (`I`) | `ruff` | sim |
| Tipagem completa | `mypy --strict` | sim |
| Fronteiras de pacote | `import-linter` | sim |
| SDK de provedor fora de `adapters/` | `ruff` banned-api + per-file-ignore | sim |
| LOC de arquivo/classe | `scripts/size_report.py` (relatório no CI) | não (warning) |
| Testes | `pytest -m "not live"` | sim |

```bash
make check   # ruff + format + mypy + import-linter + pytest
```

`make check` é o único comando que o CI roda. Se não está nele, não é regra — é sugestão.

## 7. Checklist de revisão

Toda PR é revisada com veredito explícito e estas perguntas, nesta ordem:

1. **Fronteira:** algum import atravessou camada proibida?
2. **Contrato:** erro de domínio é explícito? Falha previsível tem teste?
3. **Profundidade:** a interface nova é menor que o comportamento que esconde? Passaria no teste de deleção?
4. **Abstração:** existe protocolo sem segunda implementação? Existe `if` que deveria ser registry (ou registry prematuro)?
5. **Teste:** o teste falha se a lógica quebrar? (rodar mentalmente a mutação)
6. **Números:** algum número apareceu em código sem vindo de config ou de fonte?

Saída da revisão: `APPROVE` ou `REQUEST_CHANGES`, com críticos / importantes / menores separados. Sem "LGTM" sem justificativa.

## 8. Exceção ao padrão

Exceção não é proibida — é registrada. Formato, no docstring da função ou no corpo da PR:

```
padrão: §2 (módulo > 600 linhas)
motivo: tabela de regras legais, cada entrada é uma linha de dados
revisar quando: passar de 900 linhas ou quando as regras virarem YAML
```

Regra sem escape vira contorno escondido. Escape declarado vira decisão.
