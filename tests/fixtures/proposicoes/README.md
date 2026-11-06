# Fixtures de proposições reais

Texto de terceiros. **Única exceção ao ADR-009** (corpus de terceiros não versionado):
aqui commitamos PDFs pequenos para que a suíte de integração rode offline.

## Conteúdo

| Arquivo | Proposição | Autor | Data de apresentação | URL do inteiro teor |
|---|---|---|---|---|
| `2646598.pdf` | PL 2220/2024 | Senado Federal — Alan Rick | 2026-09-16 | https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=3180875 |
| `2644408.pdf` | PL 3878/2024 | Senado Federal — Castellar Neto | 2026-08-24 | https://www.camara.leg.br/proposicoesWeb/prop_mostrarintegra?codteor=3174690 |

Metadados completos (ementa, autores, chunk_ids esperados) em `*.json`.

## Atribuição e licença

- **Fonte:** Câmara dos Deputados — Dados Abertos (`https://dadosabertos.camara.leg.br`).
- **Licença:** dados abertos, uso livre com atribuição. O texto integral é de autoria
  do Congresso Nacional; redistribuído aqui apenas para fins de teste, com atribuição.
- **Coleta:** 2026-11-05 via `CamaraClient` (F0.1).

## Restrições

- Tamanho total da pasta ≤ 300 KB (atual: ~196 KB).
- Não adicionar fixtures sem atualizar esta tabela e o commit message com a justificativa.
- O snapshot de `chunk_id` em `*.json` (`expected_chunk_ids`) só muda com explicação no commit;
  não use `--update-snapshots` cego.
