# Fixtures adversariais da auditoria

Casos de teste do portão `audit` (docs/03 §6), um JSON por caso. Sem rede, sem
LLM, sem custo — o juiz NLI é mockado via `nli_verdicts`.

## Atribuição

Todo texto aqui é **sintético** (ADR-009): nada de lei real ou texto de terceiro
versionado. PL fictício, nomes inventados, e cada fixture declara
`"synthetic": true` — a marcação é verificada em
`tests/adversarial/test_audit_cases.py`. Qualquer texto real de lei entrando aqui
é erro de contrato.

## Esquema de um caso

```json
{
  "description": "o que o caso adversaria",
  "synthetic": true,
  "draft": "minuta em Markdown (seções + citações [C<n>])",
  "chunks": [{"chunk_id": "c1", "text": "...", "kind": "dispositivo|preambulo"}],
  "nli_verdicts": ["SUPPORTED", ...],   // opcional: veredito por sentença citada
  "expected_decision": "PASS|REPAIR|BLOCKED",
  "expected_codes": ["orphan_citation", ...]  // conjunto EXATO de finding codes
}
```

`nli_verdicts` dirige o juiz NLI mockado (default: tudo `SUPPORTED`); a asserção
exige que a decisão **e** o conjunto de códigos batam exatamente.
