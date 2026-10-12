---
name: autorizacao-movimentacao-sisdpu
description: O pedido do Defensor já é a autorização para lançar movimentação/anexar petição no SISDPU — não reconfirmar.
metadata:
  type: feedback
---

Ao lançar movimentação no SISDPU (inclusive anexando petição), **o pedido do
Defensor já é a autorização**. Executar direto, sem dry-run prévio e sem
perguntar "posso efetivar?".

**Why:** ele definiu isso em 2026-09-02, depois que eu havia montado a
ferramenta exigindo dupla confirmação (dry-run + OK explícito). Reconfirmar a
cada vez só atrasa o trabalho dele — ele é o Defensor, é o sistema dele e o
pedido é ato de vontade suficiente.

**How to apply:** chamar `POST /api/paj/<PAJ>/movimentar` com
`"confirmar": true` de uma vez. Perguntar apenas em caso de **ambiguidade de
escopo** (qual PAJ, qual arquivo, qual fase) — isso não é pedir permissão.
Depois de executar, relatar PAJ, assistido, fase, anexo e se `gravado` veio
`true`; se vier `false`, avisar e NÃO repetir o comando (duplicaria a
movimentação).

As travas do módulo `ingestao/sisdpu_movimentacao.py` continuam ativas e não
são negociáveis, porque tratam de **correção, não de permissão**: PAJ divergente
do alvo, fase inexistente, anexo ausente e verificação pós-gravação. Ver
[[honorarios-dpu-fundo-aparelhamento]].
