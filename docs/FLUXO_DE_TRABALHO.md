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
   controle. Padrão real (jun/2026): fase "Decurso de prazo", descrição
   `PAJ em decurso com situação "EFETIVADO" em DD/MM/AAAA a pedido do
   Defensor.(...)`. **Atenção:** decurso com situação **"PREVISTO"** é a
   inclusão/alteração do PAJ no controle (programação futura) — NÃO é envio
   ao defensor e é ignorado pelo classificador.

Ruído tratado: o classificador percorre as movimentações da mais recente para
trás pulando conclusões genéricas — PAJs encaminhados em duplicidade têm uma
"conclusão" posterior ao evento real, e ela não pode mascarar o motivo.

Persistência (mesmo padrão dos prazos):
- `metadata.json` do PAJ → `evento_triagem: {tipo, data, seq_origem,
  detectado_em, status}` com `status ∈ {pendente, em_analise, concluido}`.
- Empilha histórico em `triagem.jsonl` na raiz do workspace (como o
  `calendar_service.append_prazo` faz) para a fila central.

### Fase 2 — Fila de triagem na UI

> **Status: IMPLEMENTADO (v0.5.1)** — gancho no sincronizador grava
> `evento_triagem` na metadata a cada sync (só evento NOVO: movimentação com
> seq maior que a última sync, ou PAJ recém-criado; busca global/watchlist
> não gera evento). Dashboard ganhou a seção "Caixa de triagem" (some quando
> vazia), agrupada por tipo, com botão contextual que abre o PAJ direto na
> aba "Situação do PAJ" (`?tab=prompt`) e botão "Concluir" que tira da fila.

- Botões contextuais por tipo:

| Tipo | Botão |
|---|---|
| `abertura_paj` | "Analisar caso novo" |
| `intimacao` (TRF3) | "Puxar peças + analisar" (badge PJe/TRF3) |
| `intimacao` (outros) | "Analisar intimação" |
| `retorno_assistido` | "Analisar retorno" |
| `resposta_oficio` | "Analisar resposta" |
| `controle_prazo` | "Verificar prazo" |

- Rotas: `routes/triagem.py` — `GET /api/triagem` (fila),
  `POST /api/paj/{paj}/triagem/concluir`.

### Fase 3 — Análise dirigida por tipo de evento

> **Status: IMPLEMENTADO (v0.6.0)** — a aba "Situação do PAJ" agora exibe o
> RESULTADO da análise FIRAC executada (`SITUACAO.md`), não o prompt. O botão
> "Gerar análise FIRAC" roda o Claude CLI headless (services/situacao_service)
> com o molde do Defensor: 1. resumo da demanda · 2. razão do encaminhamento e
> situação atual · 3. sugestão de skill/plugin · 4. sugestão de despacho.
> O PROMPT_MAX.md vira contexto técnico (recolhido na aba) e ABRE com a
> análise quando ela existe — primeiro a situação, depois o prompt max.

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

### Fase 3b — Análise automática (sem botão)

> **Status: IMPLEMENTADO (v0.7.0)** — quando o sync detecta que um PAJ entrou
> na caixa (evento de triagem novo), a análise FIRAC é enfileirada e roda
> sozinha em segundo plano (`situacao_service.agendar_analise` + worker, 1
> Claude CLI por vez, sem atrasar o sync). A Caixa de triagem mostra
> "Ver análise ✓" quando a análise já está pronta (SITUACAO.md mais novo que
> a detecção do evento). Desligável com `SITUACAO_AUTO=false` no `.env`.
>
> **Ajuste (guard 3b × 3c):** intimação de TRF3 com peças pendentes NÃO é
> analisada automaticamente pelo sync (seria uma FIRAC cega, sem as peças do
> PJe). Esses PAJs são deixados para o 1 clique da Fase 3c, que baixa as peças
> antes de rodar a análise. Decisão em `situacao_service.analise_cega_intimacao_trf3`.

### Fase 3c — Intimação em 1 clique (peças do PJe + FIRAC encadeados)

> **Status: IMPLEMENTADO (v0.8.0)** — para intimação nova em processo do TRF3
> 1g, um único botão executa em sequência: (1) download das peças do PJe +
> OCR (`pje_service.puxar_pecas`, grava `_situacao_pje.md`) e (2) análise FIRAC
> (`situacao_service.gerar_situacao`, grava `SITUACAO.md` já COM as peças).
> Tudo numa stream SSE contínua no mesmo modal de log.
>
> - Rota: `GET /api/paj/{paj}/pje/intimacao/stream` (`routes/pje._job_intimacao`,
>   orquestração testável em `tests/test_pje_routes.py`). Se as peças falham,
>   aborta antes da análise (sem peças a análise seria cega).
> - PAJ (`paj_detail.html`): botão "⚡ Intimação nova — Puxar peças + análise
>   FIRAC", destacado quando `pje_intimacao_pendente`; JS `puxarEAnalisarPje`.
> - Dashboard: a Caixa de triagem dispara o mesmo fluxo direto no item de
>   intimação TRF3 (`acaoTriagem`) — não só navega ao PAJ.
> - Nota: a análise automática do sync (Fase 3b) roda SEM as peças (o sync não
>   abre Chrome); por isso, para intimação TRF3, o 1 clique é sempre a ação
>   certa e reanalisa com as peças em mãos.

### Fase 4 — Fechamento do ciclo (aprovação → minuta → concluído)

> **Status: IMPLEMENTADO** — ao concluir uma elaboração com peça/despacho/
> mensagem gravada na pasta do PAJ, o `evento_triagem` é marcado como
> `concluido` e some da Caixa de triagem. Idempotente e reabre no sync quando
> chega movimentação nova.
>
> - Gancho principal: `chat_service.ChatSession._persist` — ao terminar o turno
>   (`status == "done"`) com peça na pasta (`_tem_peca_gerada`, mesma regra de
>   `IGNORAR` do `paj_service`), chama `triagem_service.concluir_evento`.
> - Gancho secundário: `docgen_service.gerar_artefato` — ao gravar o DOCX/PDF
>   final no PAJ (cobre peça elaborada em sessão anterior).
> - Registrado no histórico como `triagem_concluida` (motivo: elaboracao / gerar_*).

- Plano aprovado → `chat_service` elabora com a skill certa
  (`redigir` | `despacho` | `mensagem`) — já existe.
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
4. ~~Padrão textual do "controle de prazo"?~~ **Respondido** (jun/2026):
   fase "Decurso de prazo" + situação "EFETIVADO" (ignorar "PREVISTO") —
   3 exemplos reais fixados nos testes.
