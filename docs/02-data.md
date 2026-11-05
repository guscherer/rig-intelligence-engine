# 02 — Dados: fontes, contratos e chunking

## 1. Fonte primária: Dados Abertos da Câmara

Base: `https://dadosabertos.camara.leg.br/api/v2` — pública, sem chave, JSON.

Endpoints usados (verificados em 2026-11-05 contra a API em produção):

| Uso | Endpoint | Observação verificada |
|---|---|---|
| Listar proposições | `GET /proposicoes?siglaTipo=PL&ano=2025&itens=100&pagina=1&ordem=DESC&ordenarPor=id` | paginação por `pagina`/`itens`; retorna `ementa`, `dataApresentacao` |
| Detalhe | `GET /proposicoes/{id}` | traz `keywords` (riquíssimo), `urlInteiroTeor`, `statusProposicao` |
| Tramitação | `GET /proposicoes/{id}/tramitacoes` | PL 2338/2023 → **389** eventos; usar para detectar urgência/mudança de estágio |
| Temas | `GET /proposicoes/{id}/temas` | PL 2338/2023 → 5 temas (CT&I, Direitos Humanos, Educação, Finanças, Trabalho) |
| Autores | `GET /proposicoes/{id}/autores` | partido/UF; sinal fraco de alinhamento, mas útil para o brief |
| Inteiro teor | `urlInteiroTeor` do detalhe | `content-type: application/pdf` (ex.: `codteor=2868197`) |

Exemplo canônico do projeto: **PL 2338/2023** (marco legal da IA) → `id=2487262`, 389 tramitações, 5 temas, PDF de inteiro teor. É o caso de demonstração ponta a ponta porque é longo, hierárquico e tem substitutivo — ou seja, exercita o chunker de verdade.

**Rate limit:** não há documentação pública de limite. Premissa conservadora: 1 req/s, `User-Agent` identificando o projeto, backoff exponencial com jitter em 429/5xx, e cache local de resposta por `id` + `hash`. Medir na F0 e ajustar para cima se a API permitir.

**Fonte secundária (opcional, F4):** Senado Federal (`legis.senado.leg.br/dadosabertos`) responde em **XML** e usa outra modelagem (`CodigoMateria`). O contrato precisa ser validado antes de entrar: uma resposta de pesquisa por `sigla/numero/ano` não devolveu `CodigoMateria` no formato esperado, então não assume-se nada. Enquanto não validado, fica fora do caminho crítico.

## 2. Estratégia de ingestão

Incremental, idempotente, retomável.

```
ingest_cursor(source, scope, last_id, last_ts, updated_at)
```

- Varredura por `id DESC` a partir do cursor; para em `last_id`.
- `upsert` por chave natural `(source, doc_id)`; se `content_hash` do texto não mudou, **não re-embeda** (economia direta de token).
- Reprocessa proposição quando: nova tramitação relevante (parecer, apensação, votação), novo inteiro teor (`codteor` diferente), ou mudança de situação.
- Toda execução grava `ingest_run` com contadores (`fetched`, `new`, `updated`, `skipped`, `failed`) — números reais, não impressão.

**Backfill inicial (F0):** PLs de 2023–2026, todos os tipos que podem virar norma (`PL`, `PLP`, `PEC`, `MPV`, `PDL`). Alvo ~12–15k documentos; medir tamanho real antes de fixar.

## 3. Extração de texto

```
PDF ──► PyMuPDF (texto por página)
     ├─ densidade < 100 chars/página  → extraction_quality = low, fora do índice
     ├─ detecta cabeçalho/rodapé repetido (linha igual em ≥60% das páginas) → remove
     ├─ junta hifenização quebrada, normaliza espaços e NBSP
     └─ preserva numeração de página em metadata (para citação conferível)
```

Nunca "consertar" o texto juridicamente. Se o PDF diz "Art. 12", o índice guarda "Art. 12" — mesmo que pareça erro de digitação da casa legislativa. O auditor compara contra o que está lá.

## 4. Chunker hierárquico

Chunking por janela fixa destrói citação legal. O chunker segue a estrutura do texto:

```
Título / Capítulo / Seção      → container (não vira chunk sozinho)
Art. 5º                        → unidade mínima
  § 1º                         → subunidade
    I / II / III               → inciso (nunca dividido)
      a) b) c)                 → alínea (nunca dividida)
Parágrafo único                → subunidade de artigo
```

Regras:

1. Um chunk = **um artigo inteiro** se couber em 512 tokens.
2. Se não couber, quebra por `§`; se um `§` ainda não couber, quebra por inciso — **jamais no meio de um inciso**.
3. Todo chunk carrega `breadcrumb` textual (`"Art. 5º, § 2º, II"`) e `hierarchy` estruturada.
4. Texto antes do primeiro artigo = `preambulo` (ementa, considerandos). Chunk próprio, marcado como tal: **não pode ser citado como dispositivo**.
5. Overlap só em fronteira de container, 1 bloco (≈80 tokens), e nunca duplica `breadcrumb`.
6. Texto de tabela/anexo = `anexo`, indexado, mas com flag que impede citação em minuta.

`chunk_id` é derivado, não aleatório:

```
cam:2487262:a5§2i2:07
 └── fonte └doc └breadcrumb └ordinal
```

Estável entre reindexações → citação `[C7]` continua válida depois de reprocessar outro documento.

## 5. Contrato do chunk

```json
{
  "chunk_id": "cam:2487262:a5§2i2:07",
  "source": "camara",
  "doc_id": "2487262",
  "doc_type": "proposicao",
  "doc_meta": {
    "sigla_tipo": "PL", "numero": 2338, "ano": 2023,
    "temas": ["Ciência, Tecnologia e Inovação", "Trabalho e Emprego"],
    "situacao": "Aguardando Parecer",
    "autores": ["Dep. Fulano (PARTIDO-UF)"],
    "url": "https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=2868197",
    "data_apresentacao": "2023-05-03"
  },
  "breadcrumb": "Art. 5º, § 2º, II",
  "hierarchy": {"artigo": "5º", "paragrafo": "2º", "inciso": "II", "alinea": null},
  "kind": "dispositivo",
  "text": "II - ......",
  "ordinal": 7,
  "char_span": [1204, 1330],
  "page": 3,
  "extraction_quality": "high",
  "content_hash": "sha256:..."
}
```

`kind ∈ {preambulo, dispositivo, anexo, institucional}`. O auditor usa `kind` para recusar citação de preâmbulo como se fosse norma.

## 6. Corpus institucional (tom e posição)

Três camadas, **todas com origem declarada**:

| Camada | Conteúdo | Origem | Versionado no git? |
|---|---|---|---|
| `publico` | Notas técnicas e pareceres de consultorias legislativas; manifestações públicas de entidades setoriais (CNI, Fiesp, Abes, Febraban) | coleta manual + script, com URL de origem | **não** — só o manifesto (URL, título, hash, data, licença declarada) |
| `sintetico` | Diretrizes internas fictícias da Empresa Demo (tom de voz, linhas vermelhas, posições históricas) | escritas para o projeto | sim, marcado `synthetic: true` |
| `golden` | Minutas de referência aprovadas (para few-shot e para avaliação) | sintéticas + trechos públicos citados | sim, com atribuição |

**Por que não versionar texto de terceiros:** o repo é público e o material é de autores diversos. Guardar URL + hash + script de coleta é o suficiente para reprodutibilidade e evita problema de direito autoral — um detalhe que importa numa vaga de RIG, onde propriedade de conteúdo é assunto sério. O README documenta isso explicitamente.

O corpus `sintetico` é **declaradamente fictício** em todo lugar que aparece. Nenhuma minuta de exemplo é apresentada como se fosse de empresa real.

## 7. Busca híbrida

```
query ──┬─► dense: pgvector (HNSW, cosine)      top-50  ─┐
        └─► sparse: tsvector 'portuguese' + unaccent top-50 ─┤
                                                             ▼
                                          RRF (k=60) → top-50
                                                             ▼
                              cross-encoder local (bge-reranker) → top-8
                                                             ▼
                                     filtros de metadado (ano, tema, tipo, kind)
```

Detalhes que quebram na prática e já estão resolvidos na spec:

- `unaccent` não é `IMMUTABLE` → precisa de wrapper `immutable_unaccent(text)` antes de usar em coluna gerada. Sem isso o `CREATE INDEX` falha.
- FTS do Postgres **não é BM25** (é `ts_rank_cd`). Aceitável no volume alvo; se a avaliação de retrieval mostrar gap, a troca é por `pg_bm25`/ParadeDB — decisão registrada, não escondida.
- Rerank local roda em CPU (bge-reranker-v2-m3, batch 16). Custo zero, ~200 ms para 50 candidatos em máquina modesta. Cohere fica como alternativa configurável se houver chave.
- Filtro de metadado é aplicado **antes** do ANN (`WHERE` no `SELECT`, com índice parcial), não depois — senão o recall despenca em tema raro.

### Embedding: local, `BAAI/bge-m3`, 1024 dimensões

Decisão registrada em [ADR-011](09-decisions.md). Consequência direta no schema: `chunks.embedding vector(1024)`.

| | bge-m3 (local) | Gemini `embedding-001` |
|---|---|---|
| Custo por 1k docs | R$ 0 | ~US$ 0,10–0,40 |
| Depende de chave | não | sim |
| Português | multilíngue treinado em PT, forte em texto longo | forte |
| Velocidade | ~30–60 chunks/s em CPU (a medir) | latência de rede |
| Reprodutibilidade | total (modelo versionado por hash) | depende do provedor |

O avaliador consegue clonar o repo e rodar `make ingest` **sem conta em provedor nenhum**. Isso não é detalhe de conveniência: é o que faz o projeto ser executável por quem avalia. O F5 mede `recall@8` das duas opções no golden set de 40 consultas e publica a diferença — se o local perder feio, a decisão é revista com número na mão, não com opinião.

## 8. Versionamento e reprodutibilidade

- `data/manifest.json` — hash do corpus por documento, gerado na ingestão, commitado.
- `dataset_version` gravado em cada run: permite dizer "esta minuta foi gerada com o corpus de 2026-11-05".
- Golden set versionado (`golden_set/v1.yaml`) com hash; mudar rótulo exige bump de versão e reavaliação completa.
- Nenhum número de avaliação é comparável entre versões diferentes de corpus sem re-rodar a baseline.
