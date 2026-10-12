---
name: entrega-arquivos-onedrive-trabalho-externo
description: Pasta do OneDrive corporativo usada para entregar peças quando o Defensor trabalha presencialmente na DPU.
metadata:
  type: project
---

Quando o Defensor está trabalhando **fora de casa** (presencial na DPU) e me
aciona por Remote Control, os arquivos que ele precisar ver devem ser salvos em:

```
C:\Users\Administrador\OneDrive - dpudef\DPU\Claude
```

**Why:** no computador da DPU ele **não pode instalar** o Claude Code, e o
acesso tem de ser por navegador. Expor o painel `dpuscript-ui` por túnel foi
descartado por ora — ele não tem autenticação nenhuma e serve dados sigilosos de
assistidos. O OneDrive corporativo resolve o acesso via navegador já com
autenticação institucional, sem expor nada à internet.

**How to apply:** salvar na pasta acima (verificado em 2026-09-02: escrita OK,
OneDrive rodando, tenant `dpudef` sincronizado). Não é o único destino — as peças
seguem sendo geradas em `Ofício Geral/Peças Feitas` e na pasta do PAJ; esta pasta
é a via de entrega para acesso remoto. Ver
[[honorarios-dpu-fundo-aparelhamento]].
