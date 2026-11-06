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

_Nenhuma encontrada em F0._

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
