# Skills incluídas no projeto

Este diretório traz as skills do Claude Code que o painel usa diretamente.
Elas **não** são carregadas daqui em tempo de execução — o painel lê as skills
do *workspace* do Defensor (a pasta `Ofício Geral`, configurável via
`OFICIO_GERAL` no `.env`), em `OFICIO_GERAL/.claude/skills/<slug>/SKILL.md`.

O que está aqui é a **cópia versionada** dessas skills, para que colegas que
clonam o projeto tenham o material e possam instalá-lo no próprio workspace.

## `firac/` — Sistema Integrado de Análise Jurídica

A skill **FIRAC** é a porta de entrada de análise do painel. É ela que o botão
_"Baixar peças do PJe + análise da intimação"_ (Fase 3c) aciona, encadeando a
leitura das peças processuais com a análise Fatos · Questões · Regras ·
Aplicação · Conclusão. Também guia a análise automática da _Situação do PAJ_.

### Como instalar no seu workspace

1. Localize a pasta do seu workspace (o valor de `OFICIO_GERAL` no seu `.env`;
   por padrão `~/Desktop/Ofício Geral`).
2. Copie `skills/firac/` para `OFICIO_GERAL/.claude/skills/firac/`.
3. Reinicie o painel. A skill aparece no catálogo dinâmico (`/skills`) e passa
   a ser usada pelos fluxos de triagem e de análise do PJe.

> **Adapte à sua unidade.** A skill referencia "Justiça Federal de Osasco" e o
> nome do Defensor em alguns pontos — ajuste para o seu ofício antes de usar.
