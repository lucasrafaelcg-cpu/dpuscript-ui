# Instruções do modo MPF (arquivadas)

**Status: fora de vigor desde 18/09/2026.** O Defensor optou pelo registro da
DPU. Este arquivo guarda a forma que ele usava como assessor do MPF
(2017-2018), medida em 284 documentos, para o caso de querer retomá-la.

## Como resgatar

Peça "volte ao modo MPF" e eu faço o seguinte:

1. Reponho esta Parte B no `~/.claude/manual-redacao.md`, restaurando a escala
   de três colunas (simples, intermediário, complexo).
2. Volto a coluna "complexo" ao núcleo do `~/.claude/CLAUDE.md` e ao bloco de
   redação em `services/chat_service.py`.
3. Mudo o default do diagnóstico de `--nivel simples` para `intermediario`.

As linhas de base do corpus do MPF continuam gravadas no `NIVEIS` de
`ferramentas/diagnostico_redacao.py`, sob a chave `complexo`, e o diagnóstico
aceita `--nivel complexo` mesmo com o modo DPU em vigor. Ou seja: nada foi
perdido, e medir pelo padrão do MPF continua possível a qualquer momento.

## Linhas de base medidas (corpus MPF, 284 documentos)

| Métrica | MPF |
|---|---|
| Frases por parágrafo | 5,2 |
| Parágrafos de uma frase | 39% |
| Palavras por frase | 26,0 |
| Âncora de documento por mil palavras | 2,48 |
| Conectivo clássico por mil palavras | 2,47 |
| Títulos de seção por mil palavras | 1,46 |

---

## Parte B — Peça judicial e caso complexo

*284 documentos do MPF. É o registro para inicial, recurso, contrarrazões e
alegações finais, e para o despacho de caso complexo.*

### B.1. Até quatro títulos, nunca mais

Na contrarrazões de 26 mil caracteres, a FUNDAMENTAÇÃO corre por 450 linhas com
uma única subdivisão interna. O padrão é `I - RELATÓRIO`, `II - FUNDAMENTAÇÃO`,
`III - CONCLUSÃO`, ou `I. DOS FATOS`, `II - DO DIREITO`, `III - DO ATO`,
`IV - DOS PEDIDOS`.

Proibido: subseção para trecho de menos de duas páginas; título de invenção
retórica ("DA FRAGILIDADE DA TESE RECURSAL"), porque o título nomeia a matéria
e não o argumento; e **tópico numerado embutido no parágrafo**, que é a forma
que o defeito assume no despacho, onde não há markdown ("1. DO ESCLARECIMENTO
SOBRE O ACIDENTE. Esclarecido que..."). O despacho do PAJ 2026/056-00674 tinha
sete deles, 7,11 por mil palavras.

Para organizar sem título: frase de passagem ("É o relatório." numa linha
sozinha; "Abaixo, serão rechaçadas as teses defensivas elencadas no recurso de
apelação."), ordem cronológica, e alíneas a)/b)/c) no dispositivo.

### B.2. Ordem narrativa

Os fatos andam no tempo, e a tese nasce da sequência: o convênio foi celebrado;
antes da licitação, os particulares ajustaram entre si; em 14 de fevereiro de
2007 foi publicado o edital; participaram apenas empresas controladas por eles;
a vencedora foi a ATIVOS; entretanto, a competição havia sido fraudada.

Abrir pelo direito só quando a questão é exclusivamente de direito (preliminar,
prescrição, competência).

### B.3. Âncora por assertiva

*2,48 por mil palavras no corpus dele.*

A referência vem colada ao fato, dentro da narrativa, três vezes num parágrafo
se for o caso: "ofício expedido pela Procuradoria da República no Município de
Monteiro/PB (fl. 2)", "informando 'acerca da obra em construção' (fl. 3)",
"cujos estudos ainda estão em andamento (fl. 5)".

Use o identificador do sistema: **`ID` no processo judicial do PJe** e **`mov.`
no processo do SISDPU**. A `fl.` era do tempo do processo físico e não deve ser
imitada.

Não acumular as citações num bloco de provas separado do relato.

### B.4. Parágrafo denso

5,2 frases por parágrafo, contra 1,5 no despacho simples. Cada parágrafo
carrega um passo completo do raciocínio ou da narrativa, e não uma frase
isolada.

---
