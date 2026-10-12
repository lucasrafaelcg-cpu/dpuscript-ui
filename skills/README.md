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

## `saude-natjus/` — Busca de notas técnicas do NATJus + impugnação

Pesquisa notas técnicas **favoráveis** na base pública do **e-NATJus (CNJ)**,
baixa os PDFs, extrai o texto e orienta a elaboração da impugnação da nota
desfavorável invocada pelo juízo.

O script `buscar_natjus.py` grava em `PAJs/<PAJ>/natjus/` e copia para
`pecas/`, de modo que as notas apareçam na aba Peças e entrem no contexto da
análise. Uso:

```bash
python .claude/skills/saude-natjus/buscar_natjus.py --tecnologia "Insulina Glargina" --cid E11 --paj PAJ-2025-056-00701
```

> **Vocabulário controlado.** O formulário do e-NATJus não aceita texto livre
> para a tecnologia: a escolha é feita em listas (princípio ativo / nome
> comercial). O script tenta o princípio ativo e, se não achar, o nome
> comercial; se nenhum existir na base, ele avisa em vez de pesquisar errado.
> Se o CNJ mudar o formulário, os seletores estão documentados no cabeçalho do
> script.

### Como instalar no seu workspace

1. Copie `skills/saude-natjus/` para `OFICIO_GERAL/.claude/skills/saude-natjus/`.
2. Dependências: `playwright` (com Chromium instalado) e `pymupdf` no Python
   que o Claude Code usa para rodar scripts.

## `formatacao-docx/` — Formatação de Peças Jurídicas em .docx

Converte o texto final de uma peça (marcado com `##`/`###`/`>`/`**negrito**`,
ver `SKILL.md`) num `.docx` no modelo institucional da DPU — cabeçalho, barra
lateral, marca d'água, fontes embutidas — e gera o `.pdf` correspondente via
`formatar_peca.py`. É o mesmo script usado no `dpu-workspace`.

### Como instalar no seu workspace

1. Copie `skills/formatacao-docx/` para `OFICIO_GERAL/.claude/skills/formatacao-docx/`.
2. Garanta as dependências Python no ambiente que o Claude Code CLI usa para
   rodar scripts (normalmente o `python` global, não a venv do painel):
   `pip install python-docx lxml docx2pdf`. No Windows, `docx2pdf` exige o
   Microsoft Word instalado.
3. Reinicie o painel. A skill passa a ser usada pela elaboração de peças via
   chat e pelo botão "Gerar DOCX/PDF".

> **Assinatura fixa.** O script já vem com nome/cidade do Defensor
> (`LUCAS RAFAEL GALDINO DE ARAÚJO LUCENA` / `Campina Grande/PB`) — ajuste em
> `formatar_peca.py` (`_adicionar_assinatura`) se mudar de titular ou de ofício.
