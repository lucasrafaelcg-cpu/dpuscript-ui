---
name: juntada-peticao-quem-faz
description: "No ofício do Defensor, a juntada de petição intercorrente é dele; o Cartório só pré-cadastra e junta a inicial."
metadata:
  node_type: memory
  type: project
  originSessionId: e38f20af-9230-433a-b732-c6951e1a4040
  modified: 2026-10-09T11:28:44.030Z
---

A juntada de **petição intercorrente** é feita pelo próprio Defensor, não pelo
Cartório. O Cartório faz o **pré-cadastro e a juntada da petição inicial**,
apenas. Informado por ele em 09/10/2026.

**Why:** o despacho no PAJ fecha com uma instrução interna, e eu vinha podendo
escrever "ao Cartório para juntada" em qualquer peça. Em manifestação, réplica,
recurso, embargos, impugnação ou memoriais essa instrução manda o trabalho para
quem não o executa, e o protocolo não acontece.

**How to apply:** "ao Cartório para juntada" só em petição inicial. Na
intercorrente, o despacho registra que o próprio Defensor protocola. Isso
casa com a fila de Diligências do dpuscript-ui, que anexa as peças no SISDPU
pelo painel, sem passar pelo Cartório. A regra está em `~/.claude/CLAUDE.md`
(seção "Despacho no PAJ") e na instrução da análise FIRAC do painel
(`services/situacao_service.py`). Ver [[entrega-arquivos-onedrive-trabalho-externo]]
e [[autorizacao-movimentacao-sisdpu]].
