# Exemplo de Uso da Biblioteca de Formatação

## Problema que Resolve

Antes, ao elaborar peças longas na conversa, o sistema travava e você precisava escrever "continue" várias vezes. Isso ocorria porque o texto era gerado diretamente na conversa, excedendo limites internos.

## Solução

A biblioteca `formatar_peca.py` gera os documentos via script Python, eliminando os travamentos.

## Workflow Completo

### 1. Elaboração do Texto (na conversa)

O Claude elabora o texto completo da peça normalmente, usando marcadores de formatação:

```
## I – Introdução

Este é o primeiro parágrafo da peça, com recuo de primeira linha.

O segundo parágrafo segue o mesmo padrão.

### Subtópico Importante

Texto do subtópico.

> Citação longa de acórdão ou doutrina, que será formatada com recuo de 4cm à esquerda e fonte 10pt.

## II – Conclusão

Texto final antes da assinatura.
```

### 2. Salvamento do Texto

O Claude salva o texto em arquivo temporário:

```python
texto_completo = """
## I – Introdução
...
"""

with open('D:/DPU/dpu-workspace/saida/temp_agravo.txt', 'w', encoding='utf-8') as f:
    f.write(texto_completo)
```

### 3. Formatação Automática

O Claude chama o script de formatação:

```python
import sys
sys.path.append(r'D:\DPU\dpu-workspace\skills\formatacao-docx')
from formatar_peca import criar_documento, salvar_documento

# Ler o texto salvo
with open('D:/DPU/dpu-workspace/saida/temp_agravo.txt', 'r', encoding='utf-8') as f:
    texto = f.read()

# Criar documento formatado
doc = criar_documento(
    conteudo_txt=texto,
    enderecamento="EXCELENTÍSSIMO SENHOR MINISTRO RELATOR DO SUPERIOR TRIBUNAL DE JUSTIÇA",
    titulo_peca="AGRAVO INTERNO",
    subtitulo="REsp nº 1.234.567/SP",
    numero_paj="PAJ 2024/040-12345/BVBA",
    texto_pedido="Reforma da decisão monocrática que negou seguimento ao recurso especial",
    itens_sumario=[
        "I – Introdução",
        "II – Conclusão"
    ]
)

# Salvar .docx e converter para PDF
caminho_docx, caminho_pdf = salvar_documento(
    doc,
    nome_arquivo="agravo_interno_1234567.docx"
)

print(f"[OK] DOCX: {caminho_docx}")
print(f"[OK] PDF: {caminho_pdf}")
```

### 4. Limpeza

Remover o arquivo temporário:

```python
import os
os.remove('D:/DPU/dpu-workspace/saida/temp_agravo.txt')
```

## Vantagens

1. **Sem travamentos** — o texto não precisa ser exibido na conversa
2. **Formatação automática** — .docx e .pdf gerados automaticamente
3. **Barra lateral e rodapé atualizados** — sem risco de esquecer
4. **Assinatura automática** — sempre com o nome e cargo corretos
5. **Data automática** — pega a data do sistema

## Marcadores de Formatação

| Marcador | Resultado |
|----------|-----------|
| `## Título` | Heading 1 (fonte 14pt, borda dourada) |
| `### Subtítulo` | Heading 3 (fonte 12pt, negrito) |
| `> Citação` | Citação longa (recuo 4cm, fonte 10pt) |
| Texto normal | Parágrafo justificado com recuo de primeira linha |

## Parâmetros Opcionais

- `subtitulo`: Subtítulo abaixo do título principal (ex: número do processo)
- `numero_paj`: Se fornecido, aparece no rodapé da 1ª página
- `numero_processo`: Usado no rodapé se não houver PAJ
- `texto_pedido`: Resumo do pedido para a barra lateral (se omitido, barra lateral fica vazia)
- `itens_sumario`: Lista de tópicos para o sumário da barra lateral

## Exemplo Real: Agravo Interno no STJ

```python
texto = """
## I – Questão Controvertida

A decisão monocrática aplicou entendimento superado pela jurisprudência recente desta Corte Superior.

### Precedentes recentes

> O Superior Tribunal de Justiça consolidou o entendimento de que o marco inicial dos efeitos financeiros deve observar a data do requerimento administrativo, e não a data da concessão do benefício.

## II – Pedido

Requer-se a reforma da decisão monocrática para que o recurso especial seja conhecido e provido.
"""

doc = criar_documento(
    conteudo_txt=texto,
    enderecamento="EXCELENTÍSSIMO SENHOR MINISTRO RELATOR DO SUPERIOR TRIBUNAL DE JUSTIÇA",
    titulo_peca="AGRAVO INTERNO",
    subtitulo="REsp nº 1.987.654/SC",
    numero_paj="PAJ 2024/040-98765/BVBA",
    texto_pedido="Reforma da decisão monocrática para que o REsp seja conhecido e provido",
    itens_sumario=[
        "I – Questão Controvertida",
        "II – Pedido"
    ]
)

salvar_documento(doc, "agravo_interno_1987654.docx")
```

## Resultado

Após a execução, você terá:

- `D:\DPU\dpu-workspace\saida\agravo_interno_1987654.docx` — formatado conforme o modelo DPU
- `D:\DPU\dpu-workspace\saida\agravo_interno_1987654.pdf` — idêntico ao .docx

Ambos com:
- Cabeçalho com logo DPU
- Barra lateral com pedido e sumário personalizados
- Rodapé com número do PAJ
- Formatação institucional completa
- Assinatura padrão do Defensor
