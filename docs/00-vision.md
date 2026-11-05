# 00 — Visão, personas e escopo

## 1. Por que triagem, e não geração

A leitura ingênua da vaga sugere "gerador de minutas". Mas o gerador só vale algo se o time já souber **sobre o que** escrever. Na prática, o custo está distribuído assim (estimativa a validar com o usuário real na F1):

| Etapa | Tempo típico hoje | Onde a IA agrega |
|---|---|---|
| Varrer proposições novas | 3–6 h/semana de analista | alto — é classificação com ground truth |
| Decidir se afeta a empresa | 30–60 min por proposição | alto, se houver mapa de mandato explícito |
| Levantar posição histórica | 1–2 h | alto — busca em acervo |
| Redigir nota técnica | 3–6 h | médio-alto, com revisão obrigatória |
| Checar se o texto inventou algo | 30–90 min | muito alto — é mecânico e verificável |

O sistema ataca os extremos: o começo (radar) e o fim (auditoria). É onde a IA é mensurável sem depender de gosto.

## 2. Personas

**P1 — Analista de RIG (usuário diário).** Quer abrir o dia e ver uma fila curta, ordenada, com o motivo de cada item estar ali. Não confia em score sem justificativa. Custo de erro alto nas duas direções: perder um PL tributário é caro; levantar 40 irrelevantes destrói a confiança na ferramenta.

**P2 — Especialista sênior (revisor).** Recebe a minuta pronta no Slack. Sua pergunta é única: *"posso assinar isso?"*. Ele não vai reescrever do zero; vai ajustar duas frases e conferir as citações. Se precisar conferir tudo, a ferramenta falhou.

**P3 — Diretor de Relações Institucionais (patrocinador).** Quer três números: tempo até o primeiro rascunho, custo por minuta, e quantas minutas passaram sem ajuste. Não quer ver LangGraph.

**P4 — Engenheiro de IA (avaliador técnico da vaga).** Quer clonar, rodar, e encontrar: testes de verdade, falhas documentadas, decisões justificadas, e nenhum `except: pass`.

## 3. Jobs-to-be-done

- **J1** — "Quando sai uma proposição nova, quero saber em minutos se ela toca o meu mandato, e por quê."
- **J2** — "Quando decido me posicionar, quero a posição histórica da empresa e as diretrizes aplicáveis, não a minha memória."
- **J3** — "Quando preciso entregar, quero uma minuta no tom da casa, com cada afirmação rastreável."
- **J4** — "Quando reviso, quero aprovar em dois cliques e que meu ajuste ensine o sistema."

## 4. Perfil de empresa demonstrativo

O motor é genérico: o que define "relevante" é um arquivo de configuração, o **mapa de mandato**. Para que o golden set seja rotulável, fixamos uma persona declaradamente fictícia:

```yaml
# config/company.yaml  (Empresa Demo S.A. — fictícia, para fins de demonstração)
nome: Empresa Demo S.A.
setor: indústria de tecnologia industrial
atuacao: [SP, MG, PR, BA, PE]
mandato:
  - eixo: tributario
    palavras_chave: [tributação, ICMS, PIS, COFINS, reforma tributária, incentivo fiscal, ZFM]
    sensibilidade: alta
  - eixo: dados_e_ia
    palavras_chave: [dados pessoais, LGPD, inteligência artificial, algoritmos, plataformas digitais]
    sensibilidade: alta
  - eixo: trabalho
    palavras_chave: [CLT, jornada, terceirização, contribuição sindical, trabalho remoto]
    sensibilidade: média
  - eixo: ambiental
    palavras_chave: [licenciamento, resíduos sólidos, carbono, logística reversa]
    sensibilidade: média
  - eixo: comercio_exterior
    palavras_chave: [importação, exportação, tarifa, antidumping, ex-tarifário]
    sensibilidade: média
linhas_vermelhas:            # o sistema deve recusar posicionamento sobre estes temas
  - matéria eleitoral
  - nomeação de autoridade
  - conflito de interesse de pessoa física
```

Trocar de empresa = trocar de YAML e re-rotular o golden set (o protocolo de rotulagem é o mesmo). Isso é o que faz a ferramenta ser produto, e não demo.

## 5. Escopo

**Dentro:**
- Ingestão incremental de proposições da Câmara (API oficial), com inteiro teor.
- Triagem com score, eixo de mandato e evidência citada.
- RAG híbrido sobre proposições + corpus institucional (posições, diretrizes, notas anteriores).
- Redação de três formatos: nota técnica, memorando de posicionamento, sugestão de emenda.
- Auditoria claim-a-claim com reparo iterativo e bloqueio.
- HITL no Slack com máquina de estados e feedback persistido.
- Avaliação automatizada e relatório de qualidade versionado.

**Fora (e por quê):**
- **Salesforce.** Só entra como adapter de interface na F6, sem credencial real. Integrar CRM sem sandbox vira mock com verniz.
- **Teams e Slack simultâneos.** Um canal, feito bem. Slack tem Block Kit + assinatura HMAC, que dá para testar.
- **Celery/Redis.** Fila distribuída para um grafo que roda em 40 s é cerimônia. `arq` ou `BackgroundTasks` resolvem, e o custo cognitivo é menor.
- **Kubernetes, service mesh, multi-tenant.** Nada disso é avaliado e tudo isso vira dívida de demo.
- **Parecer jurídico.** O sistema produz insumo para especialista, não opinião legal. Essa fronteira é uma linha vermelha do produto, não uma limitação técnica.

## 6. Princípios de engenharia

1. **Determinístico antes de generativo.** Filtro por regra sempre que possível; LLM só onde a regra não alcança. Corte de custo e de variância.
2. **Toda saída é verificável.** Se não dá para checar, não entra no produto.
3. **Falha é dado.** Cada alucinação encontrada vira caso de teste em `tests/adversarial/` e linha em `docs/08-failures.md`.
4. **O humano tem veto, não curadoria de lixo.** Se o revisor precisa reescrever, o bug é do sistema.
5. **Nenhum número no README sem execução registrada.** Métrica inventada é o jeito mais rápido de perder a vaga.
