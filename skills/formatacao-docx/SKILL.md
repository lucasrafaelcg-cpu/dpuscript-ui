# Skill: Formatação de Peças Jurídicas em .docx

## Objetivo
Converter o texto final da peça jurídica em arquivo .docx formatado conforme o modelo institucional da DPU, com cabeçalho, rodapé, barra lateral e identidade visual completa.

## Quando Usar
- Ao final do pipeline de qualquer Skill de recurso (ED, agravo interno, embargos de divergência, etc.)
- Quando o Defensor pedir para formatar um texto em .docx
- Para despachos de arquivamento, se solicitado

## ⚠️ IMPORTANTE: Formato do Texto de Entrada

O script de formatação **EXIGE** que o texto de entrada (.txt) use marcadores específicos:

### Marcadores Obrigatórios

```
## Título Principal     → Título de seção em negrito (tamanho 12, como o corpo)
### Subtítulo           → Subtítulo em negrito (mesmo tamanho do corpo)
> Citação longa         → Recuo de 4cm (mesma fonte/tamanho do corpo)
[DENOMINACAO] AÇÃO ...  → Nome da ação em caixa: centralizado, negrito,
                          bordas externas e sombreamento cinza
[ASSINATURA]            → Bloco de assinatura (nome + cargo), centralizado,
                          em linhas separadas — para a página de apresentação
**texto em negrito**    → Negrito inline (funciona em parágrafos e citações; máx. 2-3 por tópico)
[Fxxx]                  → Nota de rodapé de fonte verificada (com --banco)
Texto normal            → Parágrafo com recuo de primeira linha

(linha em branco)       → Quebra de parágrafo
```

### ❌ NÃO USE estes Markdown

**INCORRETO:**
```
*texto em itálico*      → NÃO FUNCIONA
# Título (um só #)      → NÃO é reconhecido (use ## ou ###)
- bullets / listas      → NÃO usar no corpo da peça (prosa contínua)
TÍTULO EM MAIÚSCULAS    → sem ## não terá formatação especial
```

**CORRETO:**
```
## TÍTULO EM MAIÚSCULAS → Heading 1 formatado

Parágrafo normal com texto corrido. Use quebras de linha duplas
para separar parágrafos.

Outro parágrafo aqui.
```

### 🔧 Encoding Obrigatório: UTF-8

**SEMPRE** salve arquivos .txt com encoding UTF-8:

```python
# ✅ CORRETO
with open('peca.txt', 'w', encoding='utf-8') as f:
    f.write(texto)

# ❌ INCORRETO (causa corrupção de acentos)
with open('peca.txt', 'w') as f:  # Sem encoding explícito
    f.write(texto)
```

### Exemplo Completo de Texto Formatado

```
## I – INTRODUÇÃO

Este é o primeiro parágrafo após o título. Ele terá recuo de primeira
linha e espaçamento adequado.

Este é o segundo parágrafo. Note a linha em branco acima para separar
os parágrafos.

### Subtópico Importante

Texto do subtópico aqui.

> Esta é uma citação longa de jurisprudência ou doutrina. Será
> formatada com recuo de 4cm.

Continuação do texto normal após a citação.

## II – CONCLUSÃO

Texto da conclusão.
```

## Cabeçalho da Peça: Endereçamento + Qualificação Processual

Quando a peça se dirige a um juízo (petição, manifestação, recurso — não se
aplica a despacho interno/ofício), **escreva os dois primeiros parágrafos do
texto exatamente nesta forma**, pois o script detecta e formata esse bloco
automaticamente:

1. **1º parágrafo — Endereçamento.** Uma linha (ou poucas linhas) em caixa
   alta, com o vocativo formal. Ex.: `EXCELENTÍSSIMO(A) SENHOR(A) DOUTOR(A)
   JUIZ(A) FEDERAL DA VARA FEDERAL COM COMPETÊNCIA CÍVEL DA SUBSEÇÃO
   JUDICIÁRIA DE CAMPINA GRANDE - SEÇÃO JUDICIÁRIA DA PARAÍBA`. O script
   renderiza em **negrito e alinhamento justificado**.
2. **(linha em branco)**
3. **2º parágrafo — Qualificação.** Uma linha para o número do processo e
   uma linha para cada parte, sem recuo. O script aceita as DUAS formas: tudo
   num parágrafo só (uma linha por item) ou cada item em seu próprio
   parágrafo, separados por linha em branco — ele consome os parágrafos
   seguidos que tenham forma de "Rótulo: valor". Rótulos reconhecidos:
   Processo, PAJ, Autor(a), Ré/Réu, Requerente, Requerido, Exequente,
   Executado, Impetrante, Impetrado, Recorrente, Recorrido, Agravante,
   Agravado, Embargante, Embargado, Apelante, Apelado, Assistido, Juízo,
   Vara, Decisão agravada, Origem, Classe, Assunto, Valor, Benefício, NB.
   Ex.:
   ```
   Processo nº 0803623-58.2024.4.05.8201 — Execução de Título Extrajudicial
   Executado: WELLINGTON RODRIGUES MOREIRA (citado por edital)
   ```
4. **(linha em branco)**
5. **A partir daqui, a apresentação da peça** (ex.: "A DEFENSORIA PÚBLICA DA
   UNIÃO, no exercício da função de CURADORA ESPECIAL do executado..., vem,
   respeitosamente, perante Vossa Excelência..."). O script insere
   automaticamente um espaçamento de 6 linhas entre a qualificação e este
   parágrafo — **não insira você mesmo linhas em branco extras aqui**.

**Não** repita o número do processo/partes dentro da apresentação — eles já
constam da qualificação acima.

### Nomeação da Peça — Petições Intercorrentes

Petições intercorrentes (manifestações no curso do processo: réplica,
impugnação, cumprimento de determinação judicial, resposta a intimação
etc.) **não devem ser nomeadas** com uma linha isolada como `MANIFESTAÇÃO`,
`PETIÇÃO INTERCORRENTE` ou similar entre a apresentação e o corpo da peça.

Em vez disso, encerre o parágrafo de apresentação com uma fórmula neutra do
tipo **"vem, respeitosamente, informar/requerer o que segue:"** (adapte ao
caso — "informar" quando for só comunicar algo ao juízo, "requerer" quando
houver pedido), e siga direto para os tópicos (`##`) do corpo. Ex.:

```
A DEFENSORIA PÚBLICA DA UNIÃO, no exercício da função de CURADORA ESPECIAL
do executado WELLINGTON RODRIGUES MOREIRA, citado por edital e revel, nos
autos da execução em epígrafe, vem, respeitosamente, perante Vossa
Excelência, em atenção à intimação para manifestação sobre a
indisponibilidade de ativos financeiros formalizada via SISBAJUD (art. 854,
§3º, do CPC), informar/requerer o que segue:

## I – DOS FATOS
...
```

Essa regra vale só para petições intercorrentes. Peças com nome técnico
próprio e consagrado (agravo, embargos de declaração, apelação, contestação,
petição inicial etc.) continuam identificadas normalmente pelo contexto —
não pela inserção de uma linha-título no corpo do documento.

### Denominação da ação — marcador `[DENOMINACAO]`

Quando a peça **nomeia a ação que está sendo proposta** — o caso típico é a
petição inicial, onde o nome da ação fica entre a qualificação do autor e o
"em face de ..." —, essa denominação vai numa **caixa destacada**: centralizada,
em negrito, com as quatro bordas externas e sombreamento cinza.

Para isso, escreva a linha com o marcador `[DENOMINACAO]`:

```
JOSÉ DE ANCHIETA FERREIRA DOS SANTOS, brasileiro, solteiro, pessoa com
deficiência, por intermédio da DEFENSORIA PÚBLICA DA UNIÃO, vem propor

[DENOMINACAO] AÇÃO DE RESTABELECIMENTO DE BENEFÍCIO DE PRESTAÇÃO CONTINUADA À PESSOA COM DEFICIÊNCIA (BPC/LOAS)

em face do INSTITUTO NACIONAL DO SEGURO SOCIAL – INSS, pelos fatos e
fundamentos a seguir.
```

O marcador não aparece no documento: o script o consome e renderiza a caixa.
Escreva a denominação **em uma única linha**, em caixa alta, sem ponto final.

**Onde usar:** petição inicial e qualquer peça que nomeie a ação/recurso que
se está propondo (ex.: `[DENOMINACAO] AÇÃO DE OBRIGAÇÃO DE FAZER`,
`[DENOMINACAO] EMBARGOS À EXECUÇÃO`).

**Onde NÃO usar:** petições intercorrentes — elas seguem a regra da seção
acima, sem nome nenhum. Também não use para títulos de seção (isso é `##`)
nem para o endereçamento (que é o 1º parágrafo).

## Quem decide o endereçamento

Três fontes, nesta ordem de precedência:

1. **`--enderecamento`**, quando passado na linha de comando. Instrução
   explícita de quem chamou, vence tudo.
2. **O 1º parágrafo do `.txt`**, quando parece endereçamento judicial. É o
   caminho normal: você escreve a peça inteira num texto só, começando pelo
   endereçamento, e o script o reconhece, tira do corpo e o renderiza no topo
   em negrito, sem recuo.
3. **O padrão do `--tipo-peca`** (`MERITÍSSIMO JUÍZO FEDERAL` para `peticao`,
   `TURMA RECURSAL...` para `recurso-inominado`, e assim por diante). É
   **fallback**, só entra quando o texto não traz endereçamento próprio.

Até 12/10/2026 o padrão do tipo era aplicado antes da leitura do texto e
impedia a detecção. O resultado, na inicial do PAJ 2026/056-00731: o genérico
`MERITÍSSIMO JUÍZO FEDERAL` no topo e o endereçamento verdadeiro caído no
corpo, com recuo de parágrafo comum. Nos embargos do PAJ 2026/056-00550 a peça
chegou a sair endereçada à Turma Nacional de Uniformização. Atingia todo tipo
de peça com padrão não vazio — isto é, todos menos o despacho.

Quando o endereçamento vem do texto, o **título do tipo** também é omitido: a
peça já se nomeia pela denominação, e repetir nomearia duas vezes.

### Rótulos de qualificação reconhecidos

As linhas logo abaixo do endereçamento são tratadas como qualificação (saem à
esquerda, sem recuo, com o nome da parte em negrito) quando **todas** têm forma
de rótulo. São aceitos, além de `Processo nº`, `PAJ nº`, `Autos`, `Classe`,
`Valor da causa`, `Juízo`, `Vara`, `Benefício`, `NB`:

- parte no masculino e no feminino: `Autor:`, `Autora:`, `Ré:`, `Réu:`,
  `Requerido:`, `Requerida:`, `Executado:`, `Embargado:`, `Recorrido:`,
  `Agravado:`, `Apelado:`, `Impetrado:`, `Assistido:`, `Interessado:`;
- **rótulo composto**, de quem acumula duas posições, com `/` ou `-`:
  `Réu/Embargante:`, `Autora/Embargada:`, `Executado - Embargante:`.

Basta uma linha não reconhecida para o bloco inteiro cair no corpo, com recuo e
sem negrito nas partes. Se a qualificação sair assim, o rótulo usado não está
na lista: acrescente-o em `_ROTULOS_QUALIFICACAO`, no script.

## Padrão visual do texto (fixo)

Todo o texto da peça sai em **Times New Roman, tamanho 12, cor preta** — corpo,
endereçamento, qualificação, títulos de seção (`##` e `###`), citações longas,
assinatura e seção de citações. Não há tamanho diferenciado para título: **12 em
tudo**, inclusive nos títulos.

Isso é aplicado pelo script, não por você: escreva o `.txt` com os marcadores
normais e a formatação é resolvida na geração. Os valores ficam centralizados no
topo de `formatar_peca.py` (`FONTE_PECA`, `TAM_PECA`, `COR_PECA`) — para mudar o
padrão, altere ali, e não espalhado pelo código.

Os títulos de seção continuam em **negrito** (é o que os distingue, já que o
tamanho é igual ao do corpo).

## Nomes das Partes: Negrito + Caixa Alta

Toda vez que o nome de uma parte (autor, réu, exequente, executado,
impetrante, requerente, requerido, assistido etc.) for citado no CORPO da
petição, ele deve aparecer em **negrito e caixa alta**. Ex.: "...do executado
**WELLINGTON RODRIGUES MOREIRA**, citado por edital...".

Na prática, **você não precisa se preocupar em marcar isso manualmente**: o
script detecta os nomes na qualificação (2º parágrafo — ver seção acima) e
aplica negrito + caixa alta automaticamente em toda ocorrência desse nome, em
qualquer capitalização que você tenha usado — no corpo **e também na própria
linha de qualificação** (o rótulo "Requerente:" fica normal, o nome sai em
negrito e caixa alta). Ainda assim, prefira
escrever o nome completo da parte (não apelidos/abreviações) para que a
detecção funcione — e, se citar alguma parte que NÃO constar da qualificação
(ex.: um terceiro mencionado só no corpo), marque-a você mesmo com
`**NOME EM CAIXA ALTA**`.

Essa regra é exceção à orientação geral de negrito com parcimônia (máx. 2-3
por tópico) — nomes de partes são sempre em negrito, quantas vezes aparecerem.

**Forma curta.** Quando o nome termina em designação genérica (FEDERAL, S.A.,
LTDA, ME, EPP, EIRELI, DO BRASIL), o script negrita também a forma curta usada
no corpo: declarada a ré como "UNIÃO FEDERAL", cada "à União" do texto sai
em negrito. Ele não toca na ocorrência que integra o nome de outra instituição,
de modo que "Defensoria Pública da União" e "Advocacia-Geral da União"
permanecem inteiras e sem marcação.

## Assinatura — centralizada, nome e cargo em linhas separadas

A assinatura sai sempre assim, sem exceção:

```
                 LUCAS RAFAEL GALDINO DE ARAÚJO LUCENA
                       Defensor Público Federal
```

Centralizada, o **nome em negrito** numa linha e o **cargo na linha seguinte**,
também centralizado. Nunca os dois na mesma linha.

**No fim da peça você não precisa escrever nada**: o script acrescenta a
assinatura automaticamente (e remove a que estiver no fim do texto, para não
duplicar).

**Na PÁGINA DE APRESENTAÇÃO** — apelação, contrarrazões, agravo e demais peças
recursais, que assinam a folha de interposição além do fim das razões — a
assinatura faz parte do corpo. Use o marcador:

```
A DEFENSORIA PÚBLICA DA UNIÃO, em favor de MARIA DAS DORES SILVA, vem
interpor APELAÇÃO, requerendo o recebimento e a remessa ao TRF5.

Campina Grande/PB, [data].

[ASSINATURA]

[NOVA PAGINA]
```

> **Por que o marcador.** O processador junta linhas consecutivas num mesmo
> parágrafo. Escrever o nome numa linha e o cargo na seguinte fazia os dois
> saírem **grudados e justificados** — "LUCAS ... LUCENA Defensor Público
> Federal". O marcador evita isso. Como rede de segurança, o script também
> reconhece o nome e o cargo escritos soltos e os centraliza em linhas
> próprias, mas prefira o marcador: é explícito e não depende de grafia.

## Agravo de Instrumento — DUAS folhas + peça complementar

O agravo de instrumento tem estrutura própria, com **dois endereçamentos
distintos em páginas separadas**. Use o marcador `[NOVA PAGINA]` (linha
sozinha) para separá-las — o script insere uma quebra de página real e detecta
o cabeçalho da segunda folha automaticamente.

### Folha 1 — interposição (ao Desembargador Relator)

```
AO EXMO. DESEMBARGADOR RELATOR DO EGRÉGIO TRIBUNAL REGIONAL FEDERAL DA 5ª REGIÃO

Processo Originário nº 0000000-00.0000.4.05.0000
PAJ nº 0000/056-00000

NOME DO AGRAVANTE, qualificado nos autos do processo originário, por
intermédio da DEFENSORIA PÚBLICA DA UNIÃO, presentada pelo Defensor Público
Federal que ao final subscreve, no uso das prerrogativas previstas na LC
80/94, vem interpor AGRAVO DE INSTRUMENTO em face de decisão proferida pelo
Juízo Federal da _ª Vara da Subseção Judiciária de _____ (id. _____).

Salienta-se que o CPC, em seu artigo 1.017, §5º, permite a interposição de
agravo de instrumento em processos virtuais com a dispensa da juntada da
documentação obrigatória referida nos incisos I e II daquele mesmo artigo,
motivo pelo qual a presente petição seguirá desacompanhada dos referidos
documentos, uma vez que notoriamente disponíveis ao acesso do Tribunal.

[NOVA PAGINA]
```

### Folha 2 — razões (endereçada à Corte)

```
EGRÉGIO TRIBUNAL REGIONAL FEDERAL DA 5ª REGIÃO,
EMINENTES DESEMBARGADORES FEDERAIS,
DOUTO RELATOR.

Autos na origem: 0000000-00.0000.4.05.0000
Agravante: Nome do agravante
Agravado: Nome do agravado

## RAZÕES DO AGRAVO
...
```

Seções típicas da folha 2, nesta ordem: `RAZÕES DO AGRAVO` · `PRERROGATIVAS DA
DEFENSORIA PÚBLICA DA UNIÃO` · `TEMPESTIVIDADE DO RECURSO` · `CABIMENTO DO
AGRAVO DE INSTRUMENTO` · `SÍNTESE PROCESSUAL` · `FUNDAMENTOS` · (tese
específica do caso) · `PEDIDOS`.

Nos `PEDIDOS`, lembrar de: conhecimento do recurso independentemente da
juntada de documentos (art. 1.017, §5º); intimação do recorrido para
contrarrazões; o mérito; observância das prerrogativas da DPU, com intimações
remetidas à **DPU/Recife**, onde atua o Defensor com competência perante o
TRF5. Havendo honorários, pedir a condenação do recorrido ao pagamento em favor
da DPU, com reversão ao Fundo de Aparelhamento (art. 4º, XXI, da LC 80/94) —
**sem** transcrever os dados bancários (eles só entram no cumprimento de
sentença; ver a seção "Honorários em favor da DPU" abaixo).

### Peça complementar OBRIGATÓRIA — petição ao juízo de origem

**Todo agravo de instrumento gera DUAS peças.** Além do agravo, produza sempre
uma petição curta dirigida ao **juízo de origem**, informando a interposição e
pugnando pela retratação (art. 1.018, §1º, do CPC). Salve em arquivo separado
(ex.: `peticao_informa_agravo.txt`). Modelo:

```
AO JUÍZO FEDERAL DA _ª VARA DA SUBSEÇÃO JUDICIÁRIA DE _____

Processo nº 0000000-00.0000.4.05.0000
PAJ nº 0000/056-00000

A parte autora, por intermédio da DEFENSORIA PÚBLICA DA UNIÃO, vem,
respeitosamente, à presença de Vossa Excelência, informar que interpôs agravo
de instrumento contra a decisão proferida por esse Juízo que _____.

O recurso foi cadastrado sob o nº _____.

Na oportunidade, pugna-se pela retratação do ato.

Nesses termos, requer deferimento.
```

Se o número do agravo ainda não existir (peça produzida antes do protocolo),
deixe o campo indicado como pendente em vez de inventar número.

## Honorários em favor da DPU — pedido de pagamento e dados da conta

### Onde os dados bancários entram (e onde NÃO entram)

Os dados da conta do Fundo de Aparelhamento só são informados nas **petições de
CUMPRIMENTO DE SENTENÇA** — ou seja, quando já se está executando o crédito.

Nas peças que apenas **pedem a condenação** (agravo, apelação, contestação,
embargos, manifestações em geral), requer-se a condenação em honorários em favor
da DPU, com reversão ao Fundo de Aparelhamento (art. 4º, XXI, da LC 80/94),
**sem transcrever a conta**. Ali o crédito ainda não existe; informar dados
bancários é prematuro e polui a peça.

### O que o pedido de cumprimento precisa conter

Sempre os três elementos, nesta ordem:

**1. Pagamento conforme o rito processual.** Identifique e NOMEIE o rito
aplicável, em vez de pedir genericamente "RPV ou precatório":

- **RPV (Requisição de Pequeno Valor)** — quando o crédito está dentro do limite
  legal do ente devedor;
- **Precatório** — quando excede esse limite;
- **Depósito judicial / intimação para pagamento espontâneo** — quando o
  executado é particular (art. 523 do CPC), não se aplicando RPV nem precatório.

Diga qual se aplica e por quê (valor do crédito frente ao limite). Se o valor
ainda não estiver definido, explicite a condição em vez de escolher no escuro.

**2. Transferência expressa para a conta do Fundo.** Requeira que, **após o
depósito em conta judicial**, os valores sejam TRANSFERIDOS para a conta abaixo.
Esse pedido é indispensável e precisa ser expresso: o depósito judicial, por si,
não faz o crédito chegar ao Fundo de Aparelhamento.

**3. Os dados da conta**, transcritos exatamente assim:

```
DADOS PARA DEPÓSITO

Banco: Caixa Econômica Federal
Operação: 1292
Agência nº 0002
Conta Corrente nº 576952567-0
CNPJ nº 58.053.223/0001-05
```

Não altere, abrevie nem "corrija" esses dados — transcreva literalmente.

## Assets Disponíveis

Os seguintes arquivos estão em `skills/formatacao-docx/assets/`:

| Arquivo | Descrição | Uso |
|---------|-----------|-----|
| `image2.jpg` | Logo DPU horizontal com degradê (colorido) | Cabeçalho (todas as páginas) |
| `image1.png` | Ícone/marca d'água DPU (contorno fino) | Rodapé das páginas internas (marca d'água) |
| `fonts/QuattrocentoSans-*.ttf` | Fontes embutidas pelo template (legado) | NÃO usadas no texto da peça — o corpo é Times New Roman 12 |

## Especificações de Formatação (extraídas do modelo)

> **Escopo.** O que segue descreve a GEOMETRIA do template (margens, barra
> lateral, marca d'água, rodapé). Fonte, tamanho e cor do TEXTO da peça
> seguem a seção "Padrão visual do texto (fixo)" acima — Times New Roman 12
> preto. O rodapé de paginação e a barra lateral são cromo do template e
> mantêm os tamanhos próprios.

### Página
- Papel: A4 (largura 11905 DXA / 21cm, altura 16837 DXA / 29,7cm)
- Orientação: retrato
- Margens:
  - Superior: 1134 DXA (2cm)
  - Inferior: 1134 DXA (2cm)
  - Esquerda: 1134 DXA (2cm)
  - Direita: 3969 DXA (7cm) — margem larga para acomodar a barra lateral
- Cabeçalho: 567 DXA (1cm) de distância do topo
- Rodapé: 567 DXA (1cm) de distância da base
- Primeira página diferente: SIM (`titlePg: true`)

### Barra Lateral Direita
Elemento visual definidor do modelo. É um retângulo posicionado à direita da página, que se estende por toda a altura.

**Na primeira página (header2 / footer2):**
- Posição horizontal: 5403533 EMU a partir da borda da página (~85mm da esquerda)
- Largura: ~1925320 EMU (~30,3mm)
- Altura: 10197525 EMU (altura total da página)
- Preenchimento: cor `#D5DBE5` com opacidade ~35% (alpha 34901/100000)
- Contém caixa de texto com:
  - **"Pedido"** — Quattrocento Sans, negrito, 14pt, cor `#323E4F`
  - Texto resumo do pedido — Palatino Linotype, itálico, 11pt, cor `#323E4F`
  - **"Sumário"** — Quattrocento Sans, negrito, 14pt, cor `#323E4F`
  - Itens do sumário com links

**Nas páginas internas (header1 / footer1):**
- Retângulo sólido cor `#323F4F` (azul-marinho escuro)
- Posição horizontal: ~5048885 EMU
- Largura: ~1825400 EMU (~28,7mm)
- Altura: ~10786059 EMU (toda a página)
- Sem conteúdo textual (apenas bloco de cor)

### Fonte Principal
- **Quattrocento Sans** (fonte embutida no documento, disponível em `assets/fonts/`)
- Cor padrão do texto: `#595959` (cinza escuro)
- Tamanho padrão: 12pt (24 half-points)

### Estilos de Parágrafo (defaults do documento)
- Espaçamento entre linhas: 1,15 (276/240 = lineRule auto, line 276)
- Espaçamento antes: 6pt (120 DXA ÷ 20)
- Espaçamento depois: 6pt (120 DXA ÷ 20)
- Recuo de primeira linha: 1418 DXA (~2,5cm)
- Alinhamento: justificado

### Estilo "Title" (Endereçamento e Título da Peça)
- Baseado em Normal
- Espaçamento antes e depois: 720 DXA (36pt) — ajustável conforme uso
- Sem recuo de primeira linha
- Negrito
- Cor: `#000000` (preto)

### Heading 1 (Tópicos principais — I, II, III...)
- Negrito
- Cor: `#323E4F` (azul-marinho escuro, mesma cor da barra lateral)
- Tamanho: 18pt (36 half-points)
- Borda inferior: linha simples, cor `#BF8F00` (dourado), 0,5pt
- Espaçamento antes: 18pt (360 DXA), depois: 12pt (240 DXA)
- Espaçamento entre linhas: simples (240)
- Sem recuo de primeira linha
- Tab stop em 426 DXA

### Heading 3 (Subtópicos)
- Negrito
- Mesmo tamanho do corpo (12pt)

### Citações Longas (mais de 3 linhas)
- Recuo de 4cm à esquerda (2268 DXA)
- Mesma fonte e tamanho do corpo (Times New Roman 12)
- Espaçamento simples entre linhas
- Sem aspas (o recuo já indica citação)

### Citações Curtas (até 3 linhas)
- Dentro do parágrafo, entre aspas
- Mesma formatação do corpo

### Cabeçalho
**Todas as páginas:**
- Logo DPU (`image2.jpg`) posicionado no canto superior esquerdo
- Dimensões do logo: 1209675 EMU × 539750 EMU (~95mm × 42,5mm)
- Posição: offset horizontal 33656 EMU, vertical -232409 EMU (ligeiramente acima da margem)

**Primeira página (header2):**
- Mesma logo
- Barra lateral com conteúdo (Pedido + Sumário)

### Rodapé
**Páginas internas (footer1 — default):**
- Paginação: campo PAGE + " / " + campo NUMPAGES
- Fonte: Quattrocento Sans, 10pt, cor `#595959`
- Alinhamento: à esquerda
- Marca d'água: `image1.png` (ícone DPU), posicionada atrás do texto (behindDoc=true)
  - Dimensões: 2265903 EMU × 2265903 EMU (~178mm quadrado)
  - Posição: offset horizontal 3110103 EMU, vertical -1172209 EMU (canto inferior direito, parcialmente sob a barra lateral)

**Primeira página (footer2):**
- Texto do PAJ: "PAJ XXXX/XXX-XXXXX/SIGLA"
- Fonte: Quattrocento Sans, 8pt (16 half-points), cor `#595959`
- Barra lateral sólida `#323F4F` no rodapé da primeira página

### Numeração de Páginas
- Formato: "X / Y" (página atual / total de páginas)
- Alinhada à esquerda no rodapé
- Começar na primeira página

## Implementação Técnica

**IMPORTANTE: Usar o script `formatar_peca.py` para todas as formatações.**

O script está em `skills/formatacao-docx/formatar_peca.py` e fornece funções prontas para converter texto estruturado em .docx + PDF formatados.

### Instalação de Dependências

```bash
pip install python-docx lxml docx2pdf
```

### Como Usar

**1. Preparar o texto da peça com marcadores de formatação:**

```python
# ✅ EXEMPLO CORRETO: Texto com marcadores
texto_completo = """## I – INTRODUÇÃO

Este é o primeiro parágrafo com recuo de primeira linha.

Este é o segundo parágrafo. Note a linha em branco separando os parágrafos.

### Subtópico Importante

Texto do subtópico.

> Esta é uma citação longa que será formatada com recuo de 4cm
> e fonte reduzida. Use o prefixo '>' no início de cada linha.

Continuação do texto normal.

## II – CONCLUSÃO

Texto final.
"""

# ✅ CORRETO: Salvar com encoding UTF-8 explícito
with open('saida/peca.txt', 'w', encoding='utf-8') as f:
    f.write(texto_completo)
```

**⚠️ ERROS COMUNS A EVITAR:**

```python
# ❌ INCORRETO: Sem marcadores de formatação
texto_incorreto = """INTRODUÇÃO

Texto sem marcadores. Não será formatado corretamente.
Títulos precisam começar com ## ou ###.
"""

# ❌ INCORRETO: Usando Markdown tradicional
texto_incorreto = """**Título em Negrito**  # NÃO FUNCIONA

Texto com *itálico* não funciona.  # NÃO FUNCIONA
"""

# ❌ INCORRETO: Sem encoding UTF-8
with open('peca.txt', 'w') as f:  # Vai corromper acentos!
    f.write(texto)
```

**2. Chamar o script de formatação:**

```python
import sys
sys.path.append(r'D:\DPU\dpu-workspace\skills\formatacao-docx')
from formatar_peca import criar_documento, salvar_documento

# Criar documento
doc = criar_documento(
    conteudo_txt=texto_completo,
    enderecamento="EXCELENTÍSSIMO SENHOR...",
    titulo_peca="AGRAVO INTERNO",
    subtitulo="REsp nº 1.234.567/SP",  # opcional
    numero_paj="PAJ 2024/040-12345/BVBA",  # opcional
    numero_processo="REsp 1234567",  # usado se não houver PAJ
    texto_pedido="Resumo do pedido para a barra lateral",  # opcional
    itens_sumario=["I – Tópico 1", "II – Tópico 2"]  # opcional
)

# Salvar .docx e converter para PDF automaticamente
caminho_docx, caminho_pdf = salvar_documento(
    doc,
    nome_arquivo="agravo_interno_1234567.docx",
    pasta_saida=r"D:\DPU\dpu-workspace\saida"
)

print(f"✓ DOCX: {caminho_docx}")
print(f"✓ PDF: {caminho_pdf}")
```

### Marcadores de Formatação no Texto

Use estes marcadores no texto para controlar a formatação:

- `## Título Principal` → título de seção (negrito, tamanho 12)
- `### Subtítulo` → subtítulo (negrito, tamanho 12)
- `> Citação longa` → recuo 4cm (fonte e tamanho do corpo)
- Texto normal → Parágrafo com recuo de primeira linha

Exemplo:

```
## I – Introdução

Este é um parágrafo normal com recuo de primeira linha.

### Subtópico importante

Outro parágrafo normal.

> Citação longa de acórdão ou doutrina, formatada com recuo de 4cm.

## II – Conclusão

Texto final.
```

### Implementação: use o script, não reimplemente

O código que gera o DOCX/PDF é o `formatar_peca.py` desta pasta — é ele que
executa, e é a única fonte da verdade sobre a formatação. Chame-o (ou use o
botão DOCX/PDF do painel) em vez de escrever geração de documento na mão.

Os valores de fonte, tamanho e cor ficam centralizados no topo daquele arquivo
(`FONTE_PECA`, `TAM_PECA`, `COR_PECA`). Para saber o padrão vigente, leia a
seção "Padrão visual do texto (fixo)" acima — não deduza do código.

> **Por que não há cópia do script aqui.** Havia, com ~490 linhas, e ela
> envelheceu: descrevia a fonte antiga (Quattrocento, cinza) muito depois de o
> padrão ter virado Times New Roman 12 preto. Instrução que contradiz o código
> é pior que instrução ausente. O trecho antigo está em
> `_modelo-anterior/script-embutido-removido.md`, se for preciso consultar.

## Cores do Modelo Institucional

| Elemento | Cor Hex | Uso |
|----------|---------|-----|
| `#323E4F` / `#323F4F` | Azul-marinho escuro | Barra lateral, títulos H1 |
| `#D5DBE5` | Azul-cinza claro | Fundo da barra lateral (1ª página, 35% opacidade) |
| `#595959` | Cinza escuro | Texto do corpo |
| `#000000` | Preto | Títulos (endereçamento, título da peça) |
| `#BF8F00` | Dourado | Borda inferior dos headings H1 |

## Fontes do Modelo

| Contexto | Fonte | Tamanho | Estilo |
|----------|-------|---------|--------|
| Corpo do texto | Times New Roman | 12pt | Regular, preto |
| Títulos de seção (`##`) | Times New Roman | 12pt | Negrito, preto |
| Subtítulos (`###`) | Times New Roman | 12pt | Negrito, preto |
| Endereçamento | Times New Roman | 12pt | Negrito, preto |
| Qualificação / assinatura | Times New Roman | 12pt | Regular, preto |
| Citações longas | Times New Roman | 12pt | Regular, preto |
| Barra lateral — títulos | Quattrocento Sans | 14pt | Negrito |
| Barra lateral — texto resumo | Palatino Linotype | 11pt | Itálico |
| Rodapé paginação | Quattrocento Sans | 10pt | Regular |
| Rodapé PAJ (1ª página) | Quattrocento Sans | 8pt | Regular |

## Conversão para PDF (OBRIGATÓRIO)

**IMPORTANTE: Após salvar o arquivo .docx, é OBRIGATÓRIO gerar uma versão em PDF idêntica.**

A conversão para PDF deve:
1. Preservar toda a formatação visual do .docx (barra lateral, cores, fontes)
2. Manter a mesma paginação
3. Preservar cabeçalhos, rodapés e marca d'água
4. Gerar arquivo com o mesmo nome base, apenas com extensão `.pdf`

### Implementação da Conversão

Usar a biblioteca `docx2pdf` (Windows) ou LibreOffice (Linux/Mac):

```python
# Windows — requer Microsoft Word instalado
from docx2pdf import convert

def converter_para_pdf(caminho_docx):
    """
    Converte o arquivo .docx para PDF mantendo toda a formatação.

    Args:
        caminho_docx: caminho completo do arquivo .docx

    Returns:
        caminho do arquivo PDF gerado
    """
    caminho_pdf = caminho_docx.replace('.docx', '.pdf')
    convert(caminho_docx, caminho_pdf)
    return caminho_pdf
```

```python
# Linux/Mac — requer LibreOffice instalado
import subprocess
import os

def converter_para_pdf_libreoffice(caminho_docx):
    """
    Converte o arquivo .docx para PDF usando LibreOffice.

    Args:
        caminho_docx: caminho completo do arquivo .docx

    Returns:
        caminho do arquivo PDF gerado
    """
    pasta_saida = os.path.dirname(caminho_docx)
    cmd = [
        'libreoffice',
        '--headless',
        '--convert-to', 'pdf',
        '--outdir', pasta_saida,
        caminho_docx
    ]
    subprocess.run(cmd, check=True)
    caminho_pdf = caminho_docx.replace('.docx', '.pdf')
    return caminho_pdf
```

### Detecção Automática de Plataforma

```python
import platform

def converter_para_pdf(caminho_docx):
    """
    Detecta o sistema operacional e usa o conversor apropriado.
    """
    sistema = platform.system()

    if sistema == 'Windows':
        try:
            from docx2pdf import convert
            caminho_pdf = caminho_docx.replace('.docx', '.pdf')
            convert(caminho_docx, caminho_pdf)
            return caminho_pdf
        except ImportError:
            raise RuntimeError(
                "docx2pdf não instalado. Execute: pip install docx2pdf"
            )
    else:
        # Linux ou Mac — usar LibreOffice
        return converter_para_pdf_libreoffice(caminho_docx)
```

### Instalação de Dependências

**Windows:**
```bash
pip install docx2pdf
```
Requer Microsoft Word instalado no sistema.

**Linux:**
```bash
sudo apt-get install libreoffice
# ou
sudo yum install libreoffice
```

**Mac:**
```bash
brew install libreoffice
```

### Integração no Fluxo de Trabalho

Ao final da geração do documento, chamar obrigatoriamente:

```python
# 1. Salvar o .docx
caminho_docx = salvar_documento(doc, nome_arquivo, pasta_saida="saida")
print(f"✓ Documento DOCX salvo em: {caminho_docx}")

# 2. Converter para PDF (OBRIGATÓRIO)
caminho_pdf = converter_para_pdf(caminho_docx)
print(f"✓ Documento PDF salvo em: {caminho_pdf}")
```

## Saída

Salvar **dois arquivos** em `/saida/` para cada peça:

**Formato .docx:**
- `agravo_interno_tnu_[numero_processo].docx`
- `agravo_interno_stj_[numero_processo].docx`
- `embargos_declaracao_tnu_[numero_processo].docx`
- `embargos_declaracao_stj_[numero_processo].docx`
- `embargos_divergencia_stj_[numero_processo].docx`
- `agravo_resp_stj_[numero_processo].docx`
- `arquivamento_[numero_processo].docx`

**Formato .pdf (idêntico ao .docx):**
- `agravo_interno_tnu_[numero_processo].pdf`
- `agravo_interno_stj_[numero_processo].pdf`
- `embargos_declaracao_tnu_[numero_processo].pdf`
- `embargos_declaracao_stj_[numero_processo].pdf`
- `embargos_divergencia_stj_[numero_processo].pdf`
- `agravo_resp_stj_[numero_processo].pdf`
- `arquivamento_[numero_processo].pdf`
