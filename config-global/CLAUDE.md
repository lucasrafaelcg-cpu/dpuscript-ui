# Instruções globais

## Base de Entendimentos DPU (CCR) — fonte de consulta complementar

Existe uma base local com os entendimentos institucionais da DPU (Boletins da
Câmara de Coordenação e Revisão — Cível e Previdenciário: Enunciados, Teses de
Arquivamento e Precedentes), em `~/.claude/conhecimento-dpu/`.

**Esta base é um ACRÉSCIMO — não substitui nem altera nenhum fluxo existente.**
É mais uma fonte de consulta, complementar à pesquisa do processo e às demais
orientações de cada projeto.

Ao **elaborar peças ou despachos da DPU**:

1. **Consulte também** a base. Comece pelo índice:
   `~/.claude/conhecimento-dpu/INDICE.md`.
2. **Busque sob demanda** — NÃO carregue os arquivos inteiros (são grandes).
   Localize por tema/palavra-chave:
   ```bash
   grep -rin "PALAVRA-CHAVE" ~/.claude/conhecimento-dpu/ccr/
   ```
   e leia apenas o trecho relevante do arquivo apontado.
3. Quando um enunciado/tese/precedente se aplicar ao caso, **cite-o
   diretamente** com a fonte que já consta na própria entrada (nº/edição do
   Boletim, SEI, PAJ ou tema de tribunal).
4. **Regra anti-alucinação:** cite apenas o que está literalmente na base. Se a
   base não cobrir o ponto, não invente — siga as fontes do processo e as
   regras do projeto.

## Formatação padrão de peças jurídicas (Word/PDF)

Ao elaborar **peças jurídicas** (recursos, embargos, contestação, memoriais,
petições, impugnações) em qualquer projeto — inclusive fora do dpuscript —
seguir, por padrão, este **padrão de formatação institucional da DPU**:

- **Títulos de seção:** numeração romana (I, II, III…); no formato de marcação
  use `## TÍTULO`. Subtítulos: `### Subtítulo`.
- **Citações longas** (ementas, dispositivos legais, doutrina): bloco recuado
  (~4 cm), fonte menor, cor cinza; no formato de marcação use `> trecho`.
- **Negrito** (`**texto**`) inline, com parcimônia (máx. 2-3 por tópico).
- **Prosa contínua**, sem listas/bullets no corpo da peça.
- **Parágrafos** separados por linha em branco. Encoding **UTF-8**.
- **Notas de rodapé de fonte:** marcador `[Fxxx]` quando houver banco de fontes.
- **Assinatura ao final** (nome em negrito, cargo abaixo):

  ```
  Campina Grande/PB, [data por extenso].

  **LUCAS RAFAEL GALDINO DE ARAÚJO LUCENA**
  Defensor Público Federal
  ```

  Nunca usar outro nome/cidade. (No dpu-workspace, nome e cidade vêm do `.env`
  via `DEFENSOR_NOME`/`DEFENSOR_CIDADE`.)

**Observações:**
- No projeto **dpu-workspace**, essa formatação é aplicada automaticamente pelo
  script `skills/formatacao-docx/formatar_peca.py` (gera DOCX + PDF a partir do
  `.txt` com os marcadores acima). Lá, basta escrever o `.txt` com os marcadores.
- **Fora do dpuscript** (onde o script não existe), reproduzir o mesmo padrão
  visual ao gerar o documento Word/PDF por outros meios (ex.: skill `docx`).
- **Despachos/petições simples de mero expediente** (ciência, juntada, prazo)
  não levam título nem viram DOCX/PDF — apenas texto direto.

## Embargos à execução fiscal: critério antes da minuta

Regra do Defensor, 20/09/2026. **Só minutar embargos quando houver tese
realmente viável.** Embargos sem tese consomem tempo e expõem o assistido sem
contrapartida.

Antes de propor ou redigir embargos, verificar, um a um:

1. **Prescrição e decadência.** Conferir a data de inscrição de cada CDA, a
   constituição do crédito e o despacho que ordenou a citação. Inscrição
   recente elimina a tese.
2. **Legitimidade do corresponsável.** Só há o que discutir se o devedor
   principal for **pessoa jurídica com personalidade autônoma**. Se a razão
   social do CNPJ for o próprio nome da pessoa natural, sem LTDA, ME ou
   EIRELI, trata-se de **empresário individual**: CNPJ e CPF são o mesmo
   sujeito de direito, não há redirecionamento, e o art. 135, III, do CTN e a
   Súmula 435 do STJ não têm objeto. Foi o erro cometido no PAJ
   2026/056-00658.
3. **Nulidade da CDA.** Faltam requisitos do art. 2º, § 5º, da Lei nº
   6.830/1980, ou a CDA traz número, série, natureza, data de inscrição,
   processo administrativo e valor?
4. **Excesso de execução.** Conferir os encargos. O encargo legal de 20% do
   DL nº 1.025/69 é devido nas execuções da União e não é, por si, matéria de
   embargos.
5. **Impenhorabilidade.** Se já foi ventilada em manifestação anterior e
   rejeitada, **repeti-la em embargos não é tese nova**.

**Não havendo tese viável**, e tendo a impenhorabilidade já sido discutida, o
produto **não é petição, é despacho** no PAJ, que deve:

- sustentar a inviabilidade dos embargos, dizendo qual tese foi examinada e
  por que não se sustenta, uma a uma;
- **ressaltar as dificuldades inerentes à curadoria especial**: o curador não
  tem e não pode ter contato com o executado revel citado por edital, não
  dispõe dos documentos do devedor, não conhece a origem dos créditos nem a
  situação patrimonial, e por isso a defesa se limita ao que os autos revelam;
- registrar o prazo dos embargos e a consequência de deixá-lo correr (em
  regra, conversão do valor bloqueado em renda da União);
- manifestar ciência.

Sobre a sucumbência: em execução fiscal da União, a Súmula 168 do extinto TFR
firma que o encargo do DL nº 1.025/69 substitui, nos embargos, a condenação em
honorários. Não usar o risco de sucumbência como fundamento sem antes
confirmar isso no caso.

A negativa geral (art. 341, parágrafo único, do CPC, e Súmula 196 do STJ) é
faculdade, não dever de embargar: ela permite defender sem conhecer os fatos,
mas não transforma em viável uma execução sem vício aparente.

## Redação: modo DPU (em vigor)

Ao redigir **peças e despachos**, seguir `~/.claude/manual-redacao.md`, derivado
da medição de 173 despachos da DPU escritos pelo próprio Defensor.

**Modo em vigor: DPU**, por decisão dele em 18/09/2026. O modo MPF, que valia
para o caso complexo, está arquivado em `~/.claude/_modelo-anterior/
instrucoes-mpf.md` e volta quando ele pedir "volte ao modo MPF".

| | Simples | Trabalhoso |
|---|---|---|
| Frases por parágrafo | 1,5 | 2,3 |
| Parágrafos de uma frase | 74% | 62% |
| Palavras por frase | 21 | 24 |
| Âncora de documento (por mil palavras) | 0,3 | 0,6 |
| Conectivo clássico (por mil palavras) | 4,3 | 4,1 |
| Títulos de seção | zero | zero |
| Tamanho do despacho | 200 a 300 palavras | 400 a 700 |

**Simples:** um requisito objetivo resolve (renda acima do teto, perda da
qualidade de segurado por data, laudo claro, matéria pacificada em repetitivo
ou parecer da CCR), arquivamento padrão, diligência de documento, mero
expediente. **Trabalhoso:** requisitos a confrontar um a um, prova a conferir,
primeiro contato com mérito.

**Referência de tamanho:** os despachos dele têm 245 palavras de média; os meus
tinham 973, quatro vezes mais. Cortar é o padrão, não a exceção.

### Despacho no PAJ

Sem título de seção, nenhum, inclusive na forma numerada embutida no parágrafo
("1. DO ESCLARECIMENTO. Esclarecido que..."). A ordem é: uma frase dizendo o
que a parte quer; o requisito ou a norma, quando o caso depende dela; a
verificação, um ponto por parágrafo de uma frase; a decisão em primeira pessoa
("Verifico que", "entendo imprescindível", "tenho por inviável", "arquivo este
PAJ", "procedo ao arquivamento", "tramito à CCR"); e a instrução interna curta
("Ao atendimento para solicitar a declaração acima.", "Cartório: gentileza,
proceder à tramitação...", "Intime-se a requerente desta decisão, inclusive da
possibilidade de oferecimento de recurso.").

**Bloco "Atendimento:"** sempre que a parte tiver de ser informada: instrução
ao atendimento sobre o que dizer a ela, em linguagem de leigo. Quando a decisão
é negativa, traz o que foi decidido em palavras simples, que o Defensor não vai
recorrer e por quê, que ela pode contratar advogado (10 dias úteis) e recorrer
da decisão da própria Defensoria (10 dias corridos), e a orientação prática.

No despacho, **data, valor e prazo sempre exatos, mas sem âncora de documento**:
quem lê tem o PAJ aberto.

**Quem junta a petição.** A juntada de **petição intercorrente** é do próprio
Defensor; o Cartório faz o pré-cadastro e a juntada da **petição inicial**,
apenas. A instrução interna do despacho nunca manda o Cartório juntar
manifestação, réplica, recurso, embargos, impugnação ou memoriais: "ao Cartório
para juntada" só cabe em inicial. Na intercorrente, o despacho registra que o
Defensor protocola.

### Peça judicial

Mesmo registro seco, com três exigências que o despacho não tem: endereçamento
e qualificação conforme o rito; **até quatro títulos romanos** (`I - RELATÓRIO`,
`II - FUNDAMENTAÇÃO`, `III - CONCLUSÃO`, ou `I. DOS FATOS` / `II - DO DIREITO` /
`III - DO ATO` / `IV - DOS PEDIDOS`), sem subseção para trecho de menos de duas
páginas e sem título retórico; e **âncora por assertiva**, com `ID` no PJe e
`mov.` no SISDPU, porque aqui quem lê não tem o PAJ aberto. Nunca `fl.`, que
era do processo físico.

### Título de seção: nomeia a matéria, nunca o argumento

Apontado pelo Defensor em 18/09/2026. Ele tem 1 caso em 457 documentos; eu
tinha em 27 peças. O que a seção quer demonstrar vem **no texto**, em prosa.

- Errado: `DO QUE A PRÓPRIA AUTARQUIA JÁ RECONHECEU`, `DO ERRO DA DECISÃO: A
  DATA DE INÍCIO`, `SUBSIDIARIAMENTE: DA NULIDADE`, `DA PROVA TÉCNICA: O QUE OS
  TRÊS LAUDOS PROVARAM`, `PRIMEIRA DISCUSSÃO: BPC/LOAS`.
- Certo: `DOS REQUISITOS DO BENEFÍCIO E DO NEXO ACIDENTÁRIO`, `DO TERMO INICIAL
  DO BENEFÍCIO`, `DA NULIDADE DO INDEFERIMENTO`, `DA PROVA TÉCNICA`,
  `DO BPC/LOAS`.

Quatro sinais de que o título virou argumento: dois-pontos (corte o que vem
depois); verbo conjugado (matéria é substantivo); substantivo valorativo (ERRO,
FRAGILIDADE, ACERTO — mas nulidade, prescrição e incompetência são categorias
jurídicas e servem); advérbio de sinalização como prefixo (a ressalva vai na
primeira frase da seção).

Uma seção por matéria, o que dá de três a cinco. O número é consequência das
matérias, não meta. Nunca criar seção para hospedar um argumento.

### Regras que valem em qualquer caso

1. **Travessão em par: zero.** Um caso em 284 documentos dele, 198 nas minhas
   peças. Use vírgula, ponto ou parênteses.
2. **Sem frase de efeito.** Nada de frase curta e cortada fechando parágrafo com
   um golpe ("Falta o suporte fático.", "Não é documento novo."). No despacho o
   parágrafo TEM uma frase só, e isso é correto: a diferença é ser afirmação com
   conteúdo, não sentença de impacto.
3. **Nunca anunciar quantidade** ("Duas razões...", "A primeira é que..."). As
   alíneas a)/b)/c) continuam, inclusive dentro da frase, para listar requisitos
   legais.
4. **Negrito só em nome de parte e denominação da ação.** No despacho, que é
   texto puro, o equivalente é a CAIXA ALTA, também proibida como ênfase.
5. **Adjetivo de ênfase trocado pelo dado** (não "insofismável"; a data, o
   valor, o intervalo).
6. **Fecho sem grandiloquência:** a última frase é a consequência jurídica ou o
   dispositivo.
7. **"Não se trata de X, mas de Y"** só quando X foi alegado. Zero ocorrências
   em 457 documentos dele.
8. **Valor e prazo:** algarismo com extenso entre parênteses onde fundam pedido
   ou prazo. Em série de remunerações do CNIS, algarismo simples.

**Conectivos liberados**, porque são o registro dele e eu uso dez vezes menos:
"Outrossim", "Com efeito", "Nesse contexto", "Nesse sentido", "Nessa linha",
"Nesse passo", "Ademais", "Entretanto", "Todavia", "Em que pese", "Afinal",
"Para tanto", "Como se sabe", "Registre-se que", "salienta-se que",
"Em resumo", "Em síntese", "Do mesmo modo", "Nesse cenário", e a frase que
anuncia o roteiro.

**Continua proibido** só o anúncio vazio de importância: "É importante destacar
que", "É fundamental notar que", "Cabe salientar que".

Para medir, no dpuscript-ui: `python ferramentas/diagnostico_redacao.py`
(default `--nivel simples`; `--nivel complexo` compara com o modo MPF
arquivado).
