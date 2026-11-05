# 04 — Human-in-the-loop

## 1. Por que Slack e não uma UI

O revisor sênior não vai abrir um dashboard. Ele já vive no Slack/Teams, e a decisão dele dura 40 segundos: aprovar, ajustar duas frases, ou rejeitar. Uma UI web própria seria mais bonita na demo e menos usada na vida real. O card no Slack é o produto.

## 2. Máquina de estados da minuta

```
                    ┌──────────────┐
                    │   DRAFTED    │
                    └──────┬───────┘
                           │ auditoria PASS
                           ▼
                    ┌──────────────┐   rejeitar   ┌──────────────┐
                    │  IN_REVIEW   ├─────────────►│   REJECTED   │
                    └──┬────┬──────┘              └──────┬───────┘
              aprovar  │    │  ajustar                   │
                       ▼    ▼                            │
              ┌──────────┐ ┌────────────────┐            │
              │ APPROVED │ │CHANGES_REQUESTED│           │
              └──────────┘ └───────┬────────┘            │
                                   │ regenera com notas  │
                                   ▼                     │
                            ┌──────────────┐             │
                            │   DRAFTED v2 │◄────────────┘
                            └──────────────┘   (rejeição
                                                vira caso de
                                                teste, não loop)
```

Transições são as únicas escritas possíveis. UPDATE fora da máquina = erro 409, não "estado inconsistente descoberto depois".

## 3. Card no Slack

Block Kit, um card por run, thread para histórico de versões:

```json
{
  "blocks": [
    {"type": "header", "text": {"type": "plain_text", "text": "PL 2338/2023 — Nota Técnica v1"}},
    {"type": "context", "elements": [{"type": "mrkdwn",
      "text": "Score 42/50 · eixo *dados_e_ia* · risco *alto* · R$ 0,11 · 38 s"}]},
    {"type": "section", "text": {"type": "mrkdwn",
      "text": "*Impacto:* obrigações de avaliação de risco para sistemas de alto risco afetam a linha de produtos X.\n*Base:* Art. 5º, § 2º, II · Art. 12 · diretriz DIR-04"}},
    {"type": "section", "fields": [
      {"type": "mrkdwn", "text": "*Claims auditados*\n12"},
      {"type": "mrkdwn", "text": "*Com suporte*\n11"},
      {"type": "mrkdwn", "text": "*Parcial*\n1"},
      {"type": "mrkdwn", "text": "*Bloqueantes*\n0"}
    ]},
    {"type": "actions", "block_id": "review_actions", "elements": [
      {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Aprovar"},
       "action_id": "approve", "value": "run_01HX..."},
      {"type": "button", "text": {"type": "plain_text", "text": "Ajustar"},
       "action_id": "adjust", "value": "run_01HX..."},
      {"type": "button", "style": "danger", "text": {"type": "plain_text", "text": "Rejeitar"},
       "action_id": "reject", "value": "run_01HX..."}
    ]}
  ]
}
```

Se `audit.verdict == BLOCKED`, entra um bloco `section` no topo com as frases problemáticas — o revisor vê **por que** antes de ver o texto. Esconder o bloqueio seria o pior design possível: o humano aprovaria no automático.

## 4. Ajustar: instrução, não edição livre

Clicar "Ajustar" abre modal com dois campos:

- `reason` (obrigatório, ≤500 chars) — o que está errado.
- `must_keep` (opcional) — trechos que não podem mudar.

O texto editado à mão **não** é reaproveitado como entrada. Ele é guardado como `human_edited` para diff e para o golden set; a regeneração usa `reason` como `revision_notes`. Isso evita o modo de falha clássico: humano corrige 6 parágrafos, o sistema "aprende" nada e a próxima sai igual.

```
POST /runs/{run_id}/feedback
{
  "action": "adjust",
  "reviewer": "U0123ABC",
  "reason": "O 2º parágrafo afirma prazo de 90 dias que não está no texto. Remover.",
  "must_keep": ["conclusão sobre avaliação de risco"],
  "draft_version": 1,
  "idempotency_key": "run_01HX:adjust:U0123ABC:9f2c"
}
```

## 5. Contrato do feedback

```python
class FeedbackEvent(BaseModel):
    run_id: str
    draft_version: int
    action: Literal["approve", "adjust", "reject"]
    reviewer: str
    reason: str | None
    must_keep: list[str] = []
    human_edited: str | None  # só em adjust
    diff_ratio: float | None  # edit distance normalizada vs draft
    created_at: datetime
    idempotency_key: str

    @model_validator(mode="after")
    def _reason_required(self):
        if self.action in ("adjust", "reject") and not self.reason:
            raise ValueError("adjust/reject exigem motivo")
        return self
```

`diff_ratio` é o KPI mais honesto do sistema: quanto o humano teve que mexer. Baixo = o texto serviu. Alto = o texto foi enfeite caro.

## 6. Como o feedback vira melhoria (e não teatro)

| Sinal | Uso |
|---|---|
| `reason` de `adjust` | `revision_notes` na regeneração imediata |
| `reason` recorrente (mesmo padrão ≥3×) | vira regra em `prompts/guidelines/` + caso em `tests/adversarial/` |
| `human_edited` com `diff_ratio` baixo | entra no few-shot como exemplo de tom aprovado |
| `reject` | nunca regenera em loop — vira caso do golden set e issue de análise |
| `approve` sem edição | âncora de qualidade: se a taxa cair, algo regrediu |

Nada disso é "aprendizado automático" mágico. É curadoria explícita — e é honesto dizer isso no README. Fine-tuning fica fora até haver massa crítica (≥200 pares aprovados), o que não existe no início.

## 7. Segurança do endpoint

- **Assinatura**: `X-Slack-Signature` verificada com HMAC-SHA256 sobre `v0:timestamp:body`, janela de 5 min.
- **Replay**: `idempotency_key` único no banco; segunda entrega retorna 200 sem efeito.
- **Autorização**: `reviewer` precisa estar em `SLACK_REVIEWER_IDS`; fora da lista → 403 com log.
- **Resposta rápida**: ACK em <3 s (exigência do Slack), processamento no worker.

## 8. Teams

Adapter com a mesma interface (`send_review`, `parse_callback`), usando Adaptive Cards. Fica atrás de feature flag e **não** é implementado no MVP — declarado em `docs/00-vision.md`. Interface pronta é honestidade arquitetural; implementação dupla sem uso é peso morto.
