---
name: saude-natjus
description: Busca notas técnicas FAVORÁVEIS no e-NATJus (CNJ) e elabora a impugnação de nota técnica desfavorável em processo de saúde. Acionar quando a decisão judicial invocar nota técnica do NATJus como fundamento para negar ou obstar medicamento, insumo ou tratamento pleiteado pelo assistido. Também serve para pesquisar notas sobre uma tecnologia antes de peticionar.
---

# Skill: Saúde — Busca de Notas Técnicas do NATJus e Impugnação

## Quando acionar

- A decisão/despacho menciona **nota técnica desfavorável do NATJus** como
  fundamento para indeferir ou obstar o pleito de saúde; ou
- o Defensor pede uma **pesquisa de notas técnicas** sobre determinada
  tecnologia (medicamento/insumo/procedimento), antes de peticionar.

Não acionar preventivamente em todo processo de saúde — só quando houver menção
à nota técnica ou pedido expresso de pesquisa.

---

## Etapa 1 — Levantar os parâmetros de busca

Ler a decisão e os documentos do PAJ (o painel já traz o texto dos anexos no
contexto; se faltar, ler os `.txt` em `pecas/`) e extrair:

- **Tecnologia** — nome do medicamento/insumo/procedimento (obrigatório)
- **CID** — código da doença (opcional, mas melhora muito o filtro)
- **Princípio ativo** — substância ativa, quando houver

Sem a tecnologia não há busca possível: nesse caso, avise o Defensor e pare.

---

## Etapa 2 — Buscar e baixar as notas favoráveis

> **Onde isto roda.** A busca precisa de execução de comando, o que só está
> disponível na **elaboração de peça** (botão "Elaborar" do painel, com esta
> skill selecionada) e no **chat da aba Discussão**. A análise FIRAC da
> "Situação do PAJ" é somente leitura: ali, no máximo, aponte que cabe buscar
> notas no NATJus — não tente executar o script.

Execute o script (não tente navegar no e-NATJus manualmente). **Use o caminho
ABSOLUTO**, porque o diretório de trabalho varia conforme o fluxo:

```bash
python "<OFICIO_GERAL>/.claude/skills/saude-natjus/buscar_natjus.py" --tecnologia "<TECNOLOGIA>" --cid "<CID>" --paj "<PAJ-NORM>"
```

`<OFICIO_GERAL>` é a raiz do workspace do Defensor — duas pastas acima da pasta
do PAJ (ex.: se o PAJ está em `.../Ofício Geral/PAJs/PAJ-2025-056-00701`, então
`<OFICIO_GERAL>` é `.../Ofício Geral`). Exemplo concreto:

```bash
python "C:/Users/Administrador/Desktop/Ofício Geral/.claude/skills/saude-natjus/buscar_natjus.py" --tecnologia "Insulina Glargina" --cid E11 --paj PAJ-2025-056-00701
```

O script aceita o PAJ em qualquer formato (`PAJ-2025-056-00701`,
`2025-056-00701`, `2025/056-00701`) e resolve a pasta pelo `OFICIO_GERAL`.
Opções: `--max N` (padrão 3 notas), `--principio-ativo`, `--oficio <caminho>`.

O que ele faz: filtra por conclusão **Favorável**, ordena por data (mais
recentes primeiro), baixa os PDFs em `PAJs/<PAJ>/natjus/`, copia para
`pecas/` (assim a nota aparece na aba Peças e entra no contexto da análise) e
extrai o texto num `.txt` ao lado de cada PDF.

Leia a última linha da saída:

- `RESULTADO: N_NOTA(S)_BAIXADA(S)` → siga pela **Etapa 3-A**
- `RESULTADO: NENHUMA_NOTA_BAIXADA` → siga pela **Etapa 3-B**

Se aparecer `AVISO: PDF sem texto nativo`, a nota é digitalizada: o teor só
estará disponível depois do OCR do painel. Nesse caso **não presuma o conteúdo**
da nota — diga ao Defensor que o OCR é necessário.

---

## Etapa 3-A — Peça COM notas favoráveis localizadas

Leia os `.txt` das notas baixadas e escreva a impugnação. É uma **petição
intercorrente**: siga a convenção da skill `formatacao-docx` (endereçamento,
qualificação, apresentação terminando em "informar/requerer o que segue:", sem
linha-título nomeando a peça).

Estrutura do corpo:

1. **Síntese da nota desfavorável** invocada pelo Juízo — apenas o que consta
   da decisão; não presuma o teor da nota que você não leu.
2. **Contraponto com as notas favoráveis** — para cada uma: identificação,
   data e conclusão, com citação literal entre aspas e a referência
   `[NATJus-01]`, `[NATJus-02]`, `[NATJus-03]` ao final de cada citação.
3. **Fundamentação jurídica** — direito à saúde (art. 196 da CF), Lei
   8.080/1990, vulnerabilidade do assistido.
4. **Pedido** — que seja afastada a nota desfavorável e deferido o pleito, com
   base nas notas colacionadas, requerendo a juntada das notas anexas.

---

## Etapa 3-B — Peça SEM notas favoráveis localizadas

Mesma estrutura, suprimindo o contraponto e desenvolvendo a fundamentação:

1. Síntese da nota desfavorável invocada pelo Juízo.
2. Fundamentação: direito à saúde (art. 196 CF, Lei 8.080/1990);
   responsabilidade solidária dos entes federativos (STF, RE 855.178);
   dignidade da pessoa humana (art. 1º, III, CF); vulnerabilidade do assistido.
3. Pedido.

**Diga explicitamente ao Defensor que nenhuma nota favorável foi localizada** —
não sugira que a pesquisa confirmou a tese.

---

## Etapa 4 — Gerar DOCX e PDF

Salve o texto em `PAJs/<PAJ>/natjus_impugnacao.txt` (UTF-8). O DOCX/PDF é
gerado pelo botão **"Gerar DOCX/PDF"** do painel, que aplica a formatação
institucional. Não é preciso chamar o formatador manualmente.

---

## Regras absolutas de conteúdo

**PROIBIDO:**
- inventar dado clínico, estatística ou percentual de eficácia;
- afirmar eficácia além do que a nota diz literalmente;
- atribuir à nota conclusão diferente da que consta no texto baixado;
- citar jurisprudência não verificada.

**OBRIGATÓRIO:**
- toda afirmação técnica ancorada nas notas efetivamente baixadas e lidas;
- referência `[NATJus-NN]` em cada citação;
- linguagem direta, sem retórica.

---

## Resumo a entregar ao final

```
## Produto: PETIÇÃO — Impugnação de Nota Técnica NATJus

### Parâmetros pesquisados
- Tecnologia: [X] | CID: [Y] | Princípio ativo: [Z]

### Resultado da busca
[N notas favoráveis localizadas | Nenhuma nota favorável localizada]

### Notas utilizadas
- NATJus-01: [identificação] — [data] — [conclusão]

### Arquivos gerados
- PAJs/<PAJ>/natjus/natjus_01_AAAA-MM-DD.pdf (+ .txt)
- PAJs/<PAJ>/pecas/90_..._NOTA TECNICA NATJUS 01.pdf
- PAJs/<PAJ>/natjus_impugnacao.txt

### Pontos-chave
- [...]
```
