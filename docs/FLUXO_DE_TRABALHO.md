# Fluxo de trabalho do 1º Ofício — desenho e plano de implementação

> Origem: diagrama manuscrito do Defensor (caderno, jun/2026).
> Status: **plano aprovado para implementação em fases** — v0.5.x.

## O fluxo desenhado

```
PAJ ──► 1º Ofício Osasco ──► DPU-script-SIS
                                   │
        ┌──────────────┬───────────┴────────┬──────────────────┐
        ▼              ▼                    ▼                  ▼
 Retorno do      Abertura de PAJ       Intimação         Resposta de ofício
 Assistido            │                    │                   │
        │        leitura da           abre PJe e          lê o documento
 lê movimentação  narrativa +         extrai peças        com OCR
 do atendimento   análise dos              │                   │
 e analisa:       documentos               │             analisa se a demanda
  (1) docs        (checklist DPU)          │             foi solucionada e os
      completos?                           │             próximos passos
      SIM→minuta                           │                   │
      NÃO→nova msg                         │                   │
  (2) questiona-                           │                   │
      mento? →                             │                   │
      responder                            │                   │
        └──────────────┴───────────┬───────┴───────────────────┘
                                   ▼
              ANÁLISE PARA O DEFENSOR sobre a demanda,
                      conforme as SKILLS
                                   ▼
              Após a APROVAÇÃO, minuta a petição ou
              despacho solicitando documentos
```

## O que já existe (não reimplementar)

| Caixa do desenho | Componente existente |
|---|---|
| DPU-script-SIS recebe a caixa | `ingestao/sincronizador.py` (sync SISDPU, OCR, prazos) |
| Intimação → abre PJe → extrai peças | flag `pje_intimacao_pendente` (sincronizador) + botão "Puxar peças do PJe" (`services/pje_service.puxar_pecas`) |
| Lê documento com OCR | `ingestao/ocr.py` (roda no sync e no puxar peças) |
| Análise conforme skills | `services/skills_catalog.py` + skills `triagem-civel/previdenciaria/penal`, `novo-caso`, etc. via `services/chat_service.py` (Claude CLI) |
| Aprovação antes de minutar | `services/planejar_service.py` + modal Planejar (plano estruturado revisado pelo Defensor) |
| Minuta petição / despacho / mensagem | skills `redigir`, `despacho`, `mensagem` + `chat_service` + docgen |

**O que falta é a cola**: classificar cada evento novo da caixa em um dos
4 tipos de entrada e oferecer ao Defensor uma fila com a *próxima ação certa*
em 1 clique — em vez de ele decidir manualmente PAJ por PAJ.

## Implementação em fases

### Fase 1 — Classificador de eventos (`services/triagem_service.py`)

> **Status: IMPLEMENTADO (v0.5.0)** — classificador em
> `services/triagem_service.py`, consumido pelo PROMPT_MAX ("Situação do
> PAJ") como dica heurística. Pendente: gancho no sincronizador (gravar
> `evento_triagem` na metadata) e fila na UI (Fase 2).

São **5 fluxos de entrada** (o Defensor acrescentou o 5º ao desenho original):

1. **`abertura_paj`** — abertura ou **redistribuição à unidade de Osasco**
   (`abertura de PAJ|redistribui|distribuição do PAJ`); no sync, também
   quando a pasta do PAJ não existia antes (`ja_existia == False`).
2. **`retorno_assistido`** — `atendimento de retorno` na FASE ou na descrição.
   Exemplos reais (capturados em `tests/test_triagem_service.py`):
   - Fase "Concluso ao defensor" / descrição "Atendimento de retorno com
     juntada de documentos";
   - Fase "Atendimento de retorno" / descrição "Fase incluída automaticamente,
     verificar fase anterior" (o sinal está na FASE);
   - Fase "Concluso ao defensor" / descrição "Atendimento de retorno.".
3. **`intimacao`** — `intima|citação|notifica`. O flag `pje_intimacao_pendente`
   do TRF3 continua como subtipo (com PJe).
4. **`resposta_oficio`** — `resposta de ofício|ofício resposta|resposta do órgão`.
5. **`controle_prazo`** — envio automático pelo sistema ao encerrar um prazo de
   controle (`controle de prazo|decurso de prazo|prazo encerrado/vencido`).

Ruído tratado: o classificador percorre as movimentações da mais recente para
trás pulando conclusões genéricas — PAJs encaminhados em duplicidade têm uma
"conclusão" posterior ao evento real, e ela não pode mascarar o motivo.

Persistência (mesmo padrão dos prazos):
- `metadata.json` do PAJ → `evento_triagem: {tipo, data, seq_origem,
  detectado_em, status}` com `status ∈ {pendente, em_analise, concluido}`.
- Empilha histórico em `triagem.jsonl` na raiz do workspace (como o
  `calendar_service.append_prazo` faz) para a fila central.

### Fase 2 — Fila de triagem na UI

- Dashboard: nova seção/aba **"Caixa de triagem"** listando PAJs com
  `evento_triagem.status == pendente`, agrupados por tipo (4 grupos do
  desenho), com badge colorido por tipo.
- Cada item mostra **um botão de ação contextual**:

| Tipo | Botão | O que dispara |
|---|---|---|
| `abertura_paj` | "Analisar caso novo" | análise com skill `triagem-*` da área (fase 3) |
| `intimacao` (TRF3) | "Puxar peças do PJe" | já existe; ao concluir, encadeia a análise |
| `intimacao` (outros) | "Analisar intimação" | análise direta (peças já vêm do SISDPU) |
| `retorno_assistido` | "Analisar retorno" | análise com as 2 perguntas do desenho |
| `resposta_oficio` | "Analisar resposta" | análise "demanda solucionada?" |

- Rotas novas: `routes/triagem.py` — `GET /api/triagem` (fila),
  `POST /api/paj/{paj}/triagem/concluir`.

### Fase 3 — Análise dirigida por tipo de evento

`services/prompt_builder.py` ganha um bloco por tipo (hoje o PROMPT_MAX é
único). Cada tipo injeta a *pergunta-guia* do desenho no final do prompt:

- **retorno_assistido**: "(1) O assistido apresentou documentos? Estão
  completos frente ao checklist? SIM → proponha a minuta de petição.
  NÃO → redija nova mensagem pedindo o que falta (skill `mensagem`).
  (2) O assistido fez questionamento? → redija a resposta."
- **abertura_paj**: "Leia a narrativa e os documentos, aplique o checklist
  DPU da área (skill `novo-caso`/`checklist-dpu`) e aponte lacunas."
- **intimacao**: "Considere as peças do PJe (`_situacao_pje.md`) / anexos,
  identifique o ato, o prazo e proponha a peça cabível."
- **resposta_oficio**: "Leia o documento (OCR). A demanda foi solucionada?
  SIM → proponha despacho de conclusão/comunicação ao assistido.
  NÃO → proponha os próximos passos."

A saída de TODAS as análises desemboca no fluxo **já existente** do
Planejar: plano estruturado → modal de revisão → aprovação do Defensor.

### Fase 4 — Fechamento do ciclo (aprovação → minuta → concluído)

- Plano aprovado → `chat_service` elabora com a skill certa
  (`redigir` | `despacho` | `mensagem`) — já existe.
- Ao gravar a peça/mensagem na pasta do PAJ, marcar
  `evento_triagem.status = concluido` (e limpar da fila).
- O item some da Caixa de triagem; histórico permanece no `triagem.jsonl`
  e no Pipeline monitor.

## Ordem e esforço estimado

| Fase | Risco | Observação |
|---|---|---|
| 1 — Classificador | baixo | função pura + 1 gancho no sincronizador; testável offline com metadata real |
| 2 — Fila UI | baixo | replica padrões do dashboard/watchlist |
| 3 — Prompts por tipo | médio | exige calibrar perguntas-guia com casos reais |
| 4 — Fechamento | baixo | gancho no fim da elaboração |

Regra de versão: cada fase = um commit + tag (`v0.5.0`, `v0.5.1`, ...) para
rollback simples, como feito na v0.4.1.

## Decisões em aberto (validar com o uso real)

1. ~~Quais movimentações identificam "retorno do assistido"?~~ **Respondido**
   (jun/2026): "Atendimento de retorno" na fase ou na descrição — 3 exemplos
   reais fixados nos testes.
2. "Resposta de ofício" chega como movimentação, anexo, ou ambos?
3. Um PAJ pode ter 2 eventos pendentes ao mesmo tempo (ex.: intimação +
   retorno)? Proposta: `evento_triagem` vira lista se acontecer na prática.
4. Padrão textual exato do evento "controle de prazo" no SISDPU (regex atual
   é palpite — calibrar com um exemplo real).
