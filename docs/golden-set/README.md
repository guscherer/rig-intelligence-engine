# Golden set — protocolo de rotulagem

Golden set sem protocolo é opinião com planilha. Este documento define como os rótulos são produzidos, para que qualquer pessoa possa contestá-los.

## 1. Amostragem (triagem)

- Universo: proposições `PL`, `PLP`, `PEC`, `MPV`, `PDL` apresentadas entre 2023-01 e 2026-10.
- Estratificação: por tema da Câmara (5 temas mais frequentes + "outros") × ano.
- Amostra: 120, sendo:
  - 70 aleatórias da estratificação (representa a realidade);
  - 30 "difíceis" — ementa genérica, impacto indireto, tema transversal (escolhidas por heurística de ambiguidade: ementa curta + múltiplos temas);
  - 20 "negativas duras" — temas claramente fora do mandato (matéria eleitoral, homenagem, denominação de via).
- Seed fixa em `eval/golden/sampling.json` → a amostra é reproduzível.

A mistura é declarada. Relatar `precision@20` sobre amostra enriquecida com casos difíceis **infla** a dificuldade e **deprime** a métrica — por isso o relatório publica o resultado no subconjunto aleatório e no total, separados.

## 2. Guia de anotação

Para cada proposição, o anotador marca:

| Campo | Valores | Regra |
|---|---|---|
| `afeta` | sim / não / incerto | "afeta" = gera obrigação, custo, restrição ou oportunidade **operacional** para o perfil do `company.yaml` |
| `eixo` | tributario / dados_e_ia / trabalho / ambiental / comercio_exterior / nenhum | eixo predominante; múltiplos permitidos, com primário marcado |
| `severidade` | 1–5 | 1 = monitorar; 5 = ação em <30 dias |
| `justificativa` | ≤200 chars | obrigatória, citando o trecho da ementa que sustenta |
| `confianca_anotador` | alta / media / baixa | baixa = candidato a segunda opinião |

**Regras de desempate:**
1. Empate entre "afeta" e "não afeta" → decide pela pergunta: "se isso passar como está, alguém da empresa precisa fazer algo diferente na segunda-feira?" Sim = afeta.
2. "Incerto" é resposta válida e **não** é convertida em "não". Vai para revisão.
3. Severidade é sobre **magnitude × urgência**, não sobre probabilidade de aprovação. O sistema não prevê votação.

## 3. Dupla anotação e concordância

- 30% da amostra (36 itens) é anotada por duas pessoas, independentemente.
- Concordância reportada: **Cohen's κ** para `afeta` e **Spearman** para `severidade`.
- κ < 0.6 → o guia está ambíguo; o guia é revisado **antes** de usar o conjunto. Não se ajusta o rótulo para bater a métrica.
- Divergências ficam registradas em `disagreements.json`, não apagadas.

## 4. Draft set (20 minutas)

- Cada item: proposição + formato (nota técnica / memorando / emenda) + minuta de referência escrita por especialista.
- A referência **não** é usada como few-shot (vazamento). Os few-shots vêm de notas públicas, documento diferente.
- Avaliação humana é cega: o revisor não sabe qual versão é IA e qual é humana, quando aplicável.

## 5. Versionamento

```yaml
# eval/golden/triage_v1.yaml
version: 1
dataset_version: cam-2026-11-05
labels_by: <anotador>
label_status: provisional | validated
n: 120
items:
  - doc_id: "2487262"
    afeta: true
    eixo: dados_e_ia
    severidade: 5
    justificativa: "..."
```

Mudar qualquer rótulo exige `version: 2` e re-execução completa da baseline. Comparar métricas entre versões diferentes de golden set é erro grave — o relatório carrega `golden_version` no cabeçalho.

## 6. Estado inicial (honesto)

Hoje: **não existe anotador especialista**. O plano é:

1. F1–F2: rotulagem provisória feita pelo autor do projeto, com `label_status: provisional`.
2. Toda métrica derivada carrega `provisional: true` no relatório e no README.
3. Se houver acesso a um profissional de RIG, 30 itens são re-rotulados para medir a divergência — e esse número (o κ entre autor e especialista) é publicado, porque é a medida honesta de quanto o resultado provisório vale.

Publicar "0.78 provisório, κ autor×especialista = 0.71" é infinitamente mais forte que publicar "0.92" sem lastro.
