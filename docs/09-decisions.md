# 09 — Decisões de arquitetura (ADRs)

Formato curto: contexto → decisão → consequência → o que foi rejeitado. Toda decisão aqui é reversível com custo declarado.

---

## ADR-001 — LangGraph em vez de CrewAI

**Contexto.** A vaga cita CrewAI e LangChain. O fluxo real tem aresta condicional (auditoria reprova e volta), limite de ciclos, orçamento e estado tipado que precisa sobreviver a retomada.

**Decisão.** LangGraph com grafo explícito e `RIGState` Pydantic.

**Por quê.** CrewAI é orientado a colaboração entre agentes com delegação implícita: bom para exploração, ruim para auditar. Aqui o valor está em *provar* que o caminho é determinístico e que o reparo tem limite. Um grafo com nós tipados é testável nó a nó (`test_draft_node` sem subir o grafo).

**Consequência.** Menos "mágica", mais código de orquestração — que é justamente o que se quer mostrar. CrewAI continua citado no README como alternativa avaliada, com o motivo.

**Rejeitado.** CrewAI (controle implícito), AutoGen (conversa livre = não determinístico), orquestração própria (reinventar retry/checkpoint sem necessidade).

---

## ADR-002 — pgvector em vez de Qdrant/Chroma

**Contexto.** Corpus alvo <2 M chunks. Precisamos de metadado relacional (tramitações, feedback, runs) junto do vetor.

**Decisão.** Postgres 16 + pgvector (HNSW) + FTS nativo no mesmo banco.

**Por quê.** Uma dependência em vez de duas. Filtro de metadado por `WHERE` no mesmo plano de execução, transacional com o resto. `docker compose up` fica com dois serviços (db, api) em vez de quatro — e o avaliador consegue rodar.

**Consequência.** FTS do Postgres não é BM25 de verdade (`ts_rank_cd`). Aceito no volume atual; se a avaliação de retrieval mostrar gap >10% de recall contra BM25 real, migra-se para ParadeDB — decisão registrada, não escondida.

**Rejeitado.** Qdrant (mais um serviço, filtro menos expressivo para metadado relacional), Chroma (não é para produção multi-processo), FAISS (sem persistência transacional).

---

## ADR-003 — Híbrido com RRF + cross-encoder local

**Contexto.** Texto legal tem dois regimes: termo exato ("Art. 5º, II", "ICMS") e semântica ("oneração da cadeia"). Nenhum dos dois cobre sozinho.

**Decisão.** Dense + sparse fundidos por Reciprocal Rank Fusion (k=60) e rerank com `bge-reranker-v2-m3` em CPU.

**Por quê.** RRF não exige calibrar scores entre retrieveres (que têm escalas incompatíveis). Reranker local custa zero por consulta — importante porque o orçamento vai para geração.

**Consequência.** ~200 ms de CPU por consulta. Se a máquina do avaliador for fraca, o compose tem perfil `lite` que desliga o rerank. A tabela comparativa em F1 mostra o ganho real; se não houver ganho, o rerank sai.

**Emenda (F1.6a, 2026-11-07).** O benchmark F1.5 (n=40) mostrou empate estatístico entre dense (0.950, IC95 [0.875, 1.000]) e rrf (0.925, IC95 [0.825, 1.000]) — diferença de uma consulta, intervalos sobrepostos. O híbrido não supera o denso de forma estatisticamente relevante (e a afirmação recíproca também seria verdadeira). Default alterado para `dense`, com justificativa operacional, não estatística: o encode da consulta já está no caminho (medido em ~2082 ms p95 no caminho completo), e eliminar BM25+RRF reduz superfície de manutenção e latência de operação. ADR-003 mantém a decisão arquitetural (híbrido disponível como modo `rrf`/`rrf+rerank`), mas o default de produção passa a ser `dense`.

---

## ADR-004 — Geração presa à citação

**Contexto.** "Sem alucinação" é requisito explícito da vaga e a maior fonte de risco reputacional do produto.

**Decisão.** Toda frase factual carrega `[C<n>]`; o parser rejeita frase factual sem citação; o auditor verifica cada claim contra o span citado em três camadas (regra, NLI, global).

**Por quê.** Instrução em prompt ("não invente") reduz, não elimina. A única forma de *provar* é exigir a referência e checar mecanicamente. Também torna o output mais útil ao revisor: ele confere a fonte, não o texto.

**Consequência.** Mais tokens por minuta (span precisa caber no contexto) e mais rigidez de estilo. Ambos aceitos: o produto é documento institucional auditável, não texto criativo.

**Rejeitado.** "Gerar e depois filtrar por similaridade com o corpus" (não localiza a claim), "confiar no self-check do modelo" (mesmo modelo, mesmo viés).

---

## ADR-005 — `arq` em vez de Celery

**Contexto.** Precisamos de execução assíncrona com retomada, sem operar um cluster.

**Decisão.** `arq` (Redis) no compose; `asyncio.create_task` no modo `dev` sem Redis.

**Por quê.** Celery exige broker + result backend + configuração de serialização para um workload de ~40 s por job. `arq` é async nativo, cabe em 30 linhas e o teste de integração sobe junto.

**Consequência.** Menos ecossistema (sem Flower, sem retry policies prontas). Para um projeto de portfólio, a simplicidade vale mais que o checklist.

---

## ADR-006 — Gemini Flash para iterar, modelo forte só na redação

**Contexto.** Custo restrito (~US$ 10 no total do desenvolvimento) e iteração rápida.

**Decisão.** Flash em triagem/auditoria/reparo de formato; modelo forte apenas no nó `draft`. Modelo configurável por nó em `config/models.yaml`.

**Por quê.** 80% das chamadas são classificação e checagem — tarefas em que o modelo barato acerta com rubrica bem escrita. Gastar modelo caro em triagem de ementa de 300 tokens é desperdício puro. A escolha é medida: F5 compara Flash vs. forte na qualidade do `draft` e publica a diferença de custo.

**Consequência.** `models.yaml` vira parte da configuração experimental. Nenhum modelo fica hardcoded.

**Rejeitado.** Tudo no modelo mais caro (custo), tudo no barato (qualidade de redação institucional cai visivelmente).

---

## ADR-007 — Salesforce e Teams fora do MVP

**Contexto.** A vaga lista Salesforce, Teams e Slack.

**Decisão.** Interfaces (`ReviewChannel`, `CrmSync`) definidas; só Slack implementado.

**Por quê.** Integração sem sandbox real vira mock com verniz — e mock de Salesforce é detectável em 10 segundos de leitura. Uma integração real (Slack, com HMAC e idempotência testados) demonstra mais competência de integração que três stubs.

**Consequência.** README declara a escolha e o motivo. Se houver sandbox disponível depois, o adapter entra sem tocar no grafo.

---

## ADR-008 — Score de triagem em código, LLM só classifica

**Contexto.** Pedir ao modelo "dê uma nota de 0 a 100 de relevância" produz número instável e inexplicável.

**Decisão.** LLM devolve dimensões discretas (`magnitude`, `urgency`, `direction`, `confidence`) + evidência literal; o score é `sensibilidade × magnitude × urgency × confiança`, calculado em Python, com a fórmula versionada.

**Por quê.** O número fica reproduzível, testável e explicável ao diretor ("esta PL tem score 42 porque é eixo tributário de sensibilidade alta, magnitude 4, urgência 3"). Mudar peso é mudar configuração, não prompt.

**Consequência.** Menos "nuance" que um score holístico do modelo. Em troca, consistência — que é o que uma fila de trabalho precisa.

---

## ADR-009 — Corpus de terceiros não versionado

**Contexto.** O repositório é público e o corpus inclui notas técnicas e pareceres de autoria de terceiros.

**Decisão.** Commitar apenas `manifest.json` (URL, título, autor, data, hash, licença declarada) + script de coleta. Texto integral fica em `data/` (gitignored), obtido por `make ingest`.

**Por quê.** Reprodutibilidade sem redistribuição. Também é a postura correta para alguém que vai trabalhar com propriedade intelectual e conteúdo institucional — o domínio da vaga.

**Consequência.** O avaliador precisa rodar `make ingest` (requer rede) antes de `make demo`. Documentado no README, com fixtures pequenas commitadas para os testes rodarem offline.

---

## ADR-010 — Monólito modular em vez de microserviços

**Contexto.** A vaga fala em "ecossistema", "ponte entre áreas técnicas" e integração com Salesforce/Teams/Slack — vocabulário que costuma vir acompanhado de expectativa de arquitetura distribuída. O projeto, porém, tem um desenvolvedor, um deploy e um grafo que compartilha estado entre cinco etapas.

**Decisão.** Um binário, dois processos (`rig-api`, `rig-worker`) e fronteiras de pacote verificadas por `import-linter`. Nenhum serviço de rede interno.

**Por quê.** O `RIGState` atravessa `triage → retrieve → positioning → draft → audit`. Fatiar isso em serviços converte cada aresta do grafo em chamada de rede com estado serializado, e troca um bug de lógica por cinco modos de falha distribuída (retry parcial, consistência eventual entre draft e audit, versionamento de contrato entre quem escreve e quem audita). Os eixos que justificariam distribuição não existem aqui: volume de ~6k documentos/ano, p95 de 90 s dominado por latência de LLM (escala por worker, não por serviço), e um único consumidor do retrieval.

**Consequência.** O isolamento que importa — job longo não bloqueia request — vem de dois processos na mesma imagem, não de malha de serviços. As fronteiras de pacote são as mesmas que seriam as dos serviços, então extrair depois é mover arquivo, não reescrever. Critério declarado de extração: ingestão acima de 30 min competindo por CPU com geração, corpus acima de 50 M chunks, ou segundo consumidor do retrieval.

**Risco aceito.** Um avaliador raso pode ler "monólito" como imaturidade. A defesa é este ADR com os números, não a omissão da decisão. Candidato que sabe *por que não* distribuir é mais sênior que o que distribui por default.

**Rejeitado.** Microserviços por domínio (4 serviços para ~4k LOC = 1 serviço por 1k linhas, com 4 Dockerfiles, 4 pipelines e contratos entre eles); service mesh; event bus para um fluxo que é sequencial.

---

## ADR-011 — Embedding local (`bge-m3`, 1024 dims)

**Contexto.** Literalmente, tudo no projeto depende de vetor: retrieval, avaliação de recall, ingestão. Usar o embedding do provedor de geração amarra F0/F1/F5 a uma chave de API e a um custo por documento — e a vaga é justamente sobre rodar isso dentro de uma empresa, onde conta de API é processo de compras.

**Decisão.** `BAAI/bge-m3` via `sentence-transformers`, 1024 dimensões, rodando em CPU no plano offline.

**Por quê.** (1) Elimina o bloqueio de credencial: o repo roda ponta a ponta sem conta em provedor. (2) Custo marginal zero por documento, o que importa porque a ingestão é reprocessável. (3) Multilíngue com bom desempenho em português institucional longo. (4) Reprodutibilidade real — o modelo tem hash, a API do provedor muda de versão sem avisar.

**Consequência.** Custo de 4 KB por vetor: 100k chunks ≈ 400 MB, 2 M chunks ≈ 8 GB. Ingestão ganha custo de CPU (~30–60 chunks/s, a medir no F0) em vez de custo de token. O schema fixa `vector(1024)` — dimensão errada não dá erro na criação do índice, só degrada a busca silenciosamente, então está amarrada em `EMBEDDING_DIM` e validada no startup.

**Risco aceito.** bge-m3 pode perder para um modelo de fronteira em nuance semântica. Mitigação: F5 compara `recall@8` das duas opções no mesmo golden set de 40 consultas e publica a diferença. Se o local perder >10%, a decisão muda com número, não com opinião.

**Rejeitado.** Gemini `embedding-001` (bloqueio de chave + custo por doc), OpenAI `text-embedding-3` (idem, e menos forte em PT que bge-m3), `e5-small` (384 dims, mais barato de rodar e claramente mais fraco em texto jurídico longo).

---
