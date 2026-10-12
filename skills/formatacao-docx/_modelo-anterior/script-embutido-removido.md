# Trecho removido da SKILL.md em 2026-09-09

Era uma cópia do script de geração dentro das instruções da skill (~19,5 KB, ~5 mil tokens carregados a cada uso). Foi retirado por três motivos: (1) o script real é `formatar_peca.py`, que é o que executa; (2) esta cópia estava DESATUALIZADA — falava da fonte Quattrocento e de cinza, quando o padrão vigente é Times New Roman 12 preto; (3) dobrava o peso da skill sem acrescentar regra alguma.

Guardado aqui apenas para resgate, a pedido do Defensor.

---

### Script Base de Geração

```python
from docx import Document
from docx.shared import Pt, Cm, Emu, RGBColor, Twips
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml
import os

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "image2.jpg")
WATERMARK_PATH = os.path.join(ASSETS_DIR, "image1.png")
FONT_DIR = os.path.join(ASSETS_DIR, "fonts")

def criar_documento(conteudo_paragrafos, titulo_enderecamento, titulo_peca,
                    numero_paj, numero_processo, resumo_pedido=None, sumario=None):
    """
    Cria documento .docx no modelo institucional da DPU.

    Args:
        conteudo_paragrafos: lista de dicts com keys:
            - 'texto': str ou lista de dicts {'texto': str, 'negrito': bool, 'italico': bool}
            - 'tipo': 'normal' | 'titulo' | 'heading1' | 'heading3' | 'citacao_longa' | 'citacao_curta'
        titulo_enderecamento: str — "A Sua Excelência o(a) Senhor(a)..."
        titulo_peca: str — ex: "Recurso Extraordinário com Agravo nº 1.446.634"
        numero_paj: str — "PAJ 2023/040-06077/BVBA"
        numero_processo: str — para nome do arquivo
        resumo_pedido: str (opcional) — texto do resumo para a barra lateral
        sumario: list de str (opcional) — itens do sumário para a barra lateral
    """
    doc = Document()

    # ============================================================
    # 1. CONFIGURAR ESTILOS PADRÃO
    # ============================================================
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Quattrocento Sans'
    font.size = Pt(12)
    font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    pf = style.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.space_before = Pt(6)
    pf.space_after = Pt(6)
    pf.line_spacing = 1.15
    pf.first_line_indent = Cm(2.5)

    # ============================================================
    # 2. CONFIGURAR PÁGINA
    # ============================================================
    section = doc.sections[0]
    section.page_width = Emu(7560310)    # A4 width
    section.page_height = Emu(10692130)  # A4 height
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2)
    section.right_margin = Cm(7)  # Margem larga para barra lateral
    section.header_distance = Cm(1)
    section.footer_distance = Cm(1)
    section.different_first_page_header_footer = True

    # ============================================================
    # 3. CABEÇALHO (todas as páginas) — Logo DPU
    # ============================================================
    # Cabeçalho padrão (páginas 2+)
    header = section.header
    header.is_linked_to_previous = False
    hp = header.paragraphs[0]
    hp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = hp.add_run()
    run.add_picture(LOGO_PATH, width=Emu(1209675), height=Emu(539750))

    # Cabeçalho da primeira página
    first_header = section.first_page_header
    first_header.is_linked_to_previous = False
    fhp = first_header.paragraphs[0]
    fhp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    frun = fhp.add_run()
    frun.add_picture(LOGO_PATH, width=Emu(1209675), height=Emu(539750))

    # ============================================================
    # 4. RODAPÉ
    # ============================================================
    # Rodapé padrão (páginas 2+): paginação X / Y
    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    fp.style.font.size = Pt(10)
    fp.style.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    # Campo PAGE
    run_page = fp.add_run()
    fldChar1 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
    run_page._r.append(fldChar1)
    run_instr = fp.add_run()
    instrText = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> PAGE </w:instrText>')
    run_instr._r.append(instrText)
    run_sep = fp.add_run()
    fldChar2 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="separate"/>')
    run_sep._r.append(fldChar2)
    run_end = fp.add_run()
    fldChar3 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
    run_end._r.append(fldChar3)

    run_div = fp.add_run(" / ")
    run_div.font.size = Pt(10)
    run_div.font.name = 'Quattrocento Sans'
    run_div.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    # Campo NUMPAGES
    run_np = fp.add_run()
    fldChar4 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="begin"/>')
    run_np._r.append(fldChar4)
    run_instr2 = fp.add_run()
    instrText2 = parse_xml(f'<w:instrText {nsdecls("w")} xml:space="preserve"> NUMPAGES </w:instrText>')
    run_instr2._r.append(instrText2)
    run_sep2 = fp.add_run()
    fldChar5 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="separate"/>')
    run_sep2._r.append(fldChar5)
    run_end2 = fp.add_run()
    fldChar6 = parse_xml(f'<w:fldChar {nsdecls("w")} w:fldCharType="end"/>')
    run_end2._r.append(fldChar6)

    # Rodapé da primeira página: número do PAJ
    first_footer = section.first_page_footer
    first_footer.is_linked_to_previous = False
    ffp = first_footer.paragraphs[0]
    ffp.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run_paj = ffp.add_run(numero_paj)
    run_paj.font.size = Pt(8)
    run_paj.font.name = 'Quattrocento Sans'
    run_paj.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    # ============================================================
    # 5. INSERIR BARRA LATERAL VIA XML
    # ============================================================
    # A barra lateral é inserida como shape ancorado no cabeçalho.
    # Como python-docx não tem suporte nativo para shapes ancorados,
    # a barra lateral deve ser injetada via manipulação direta do XML
    # do cabeçalho após a geração do documento.
    #
    # Alternativa simplificada: usar o modelo .docx original como
    # template e apenas preencher o conteúdo. Ver seção "Abordagem
    # com Template" abaixo.

    # ============================================================
    # 6. CONTEÚDO DO DOCUMENTO
    # ============================================================

    # Endereçamento (estilo Title)
    p_end = doc.add_paragraph()
    p_end.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_end.paragraph_format.space_before = Pt(0)
    p_end.paragraph_format.space_after = Pt(30)
    p_end.paragraph_format.first_line_indent = Pt(0)
    run = p_end.add_run(titulo_enderecamento)
    run.bold = True
    run.font.name = 'Quattrocento Sans'
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0, 0, 0)

    # Título da peça (estilo Title)
    p_tit = doc.add_paragraph()
    p_tit.alignment = WD_ALIGN_PARAGRAPH.LEFT
    p_tit.paragraph_format.space_before = Pt(0)
    p_tit.paragraph_format.space_after = Pt(30)
    p_tit.paragraph_format.first_line_indent = Pt(0)
    run = p_tit.add_run(titulo_peca)
    run.bold = True
    run.font.name = 'Quattrocento Sans'
    run.font.size = Pt(12)
    run.font.color.rgb = RGBColor(0, 0, 0)

    # Parágrafos do conteúdo
    for item in conteudo_paragrafos:
        tipo = item.get('tipo', 'normal')
        texto = item.get('texto', '')

        if tipo == 'heading1':
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(18)
            p.paragraph_format.space_after = Pt(12)
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.first_line_indent = Pt(0)
            # Borda inferior dourada
            pPr = p._p.get_or_add_pPr()
            pBdr = parse_xml(
                f'<w:pBdr {nsdecls("w")}>'
                '  <w:bottom w:val="single" w:sz="4" w:space="1" w:color="BF8F00"/>'
                '</w:pBdr>'
            )
            pPr.append(pBdr)
            run = p.add_run(texto)
            run.bold = True
            run.font.name = 'Quattrocento Sans'
            run.font.size = Pt(18)
            run.font.color.rgb = RGBColor(0x32, 0x3E, 0x4F)

        elif tipo == 'heading3':
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(texto)
            run.bold = True
            run.font.name = 'Quattrocento Sans'
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

        elif tipo == 'citacao_longa':
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.left_indent = Cm(4)
            p.paragraph_format.first_line_indent = Pt(0)
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_after = Pt(6)
            if isinstance(texto, str):
                run = p.add_run(texto)
                run.font.name = 'Quattrocento Sans'
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
            else:
                for segmento in texto:
                    run = p.add_run(segmento.get('texto', ''))
                    run.font.name = 'Quattrocento Sans'
                    run.font.size = Pt(10)
                    run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
                    if segmento.get('negrito'):
                        run.bold = True
                    if segmento.get('italico'):
                        run.italic = True

        elif tipo == 'titulo':
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_before = Pt(36)
            p.paragraph_format.space_after = Pt(36)
            p.paragraph_format.first_line_indent = Pt(0)
            run = p.add_run(texto)
            run.bold = True
            run.font.name = 'Quattrocento Sans'
            run.font.size = Pt(12)
            run.font.color.rgb = RGBColor(0, 0, 0)

        else:  # normal
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.line_spacing = 1.15
            p.paragraph_format.first_line_indent = Cm(2.5)

            if isinstance(texto, str):
                run = p.add_run(texto)
                run.font.name = 'Quattrocento Sans'
                run.font.size = Pt(12)
                run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
            else:
                for segmento in texto:
                    run = p.add_run(segmento.get('texto', ''))
                    run.font.name = 'Quattrocento Sans'
                    run.font.size = Pt(12)
                    run.font.color.rgb = RGBColor(0x59, 0x59, 0x59)
                    if segmento.get('negrito'):
                        run.bold = True
                    if segmento.get('italico'):
                        run.italic = True

    return doc


def salvar_documento(doc, nome_arquivo, pasta_saida="saida"):
    """Salva o documento na pasta de saída."""
    os.makedirs(pasta_saida, exist_ok=True)
    caminho = os.path.join(pasta_saida, nome_arquivo)
    doc.save(caminho)
    return caminho
```

### Abordagem com Template (Recomendada)

Para preservar fielmente a barra lateral, marca d'água e todos os elementos visuais complexos do modelo, a abordagem mais robusta é usar o próprio documento modelo como template:

1. O documento modelo original está disponível em `D:\DPU\MODELO ARE 1446634 - agravo interno hanseníase - PAJ 2023.040.06077.docx`
2. Copiar o modelo, limpar o conteúdo do corpo (mantendo cabeçalhos, rodapés, seções)
3. **OBRIGATÓRIO: Atualizar o conteúdo da barra lateral** (ver seção abaixo)
4. Preencher com o novo conteúdo

```python
import copy
from docx import Document

def criar_documento_via_template(template_path, conteudo_paragrafos,
                                  titulo_enderecamento, titulo_peca,
                                  numero_paj):
    """
    Usa o modelo original como template, preservando toda a
    identidade visual (barra lateral, logo, marca d'água).
    """
    doc = Document(template_path)

    # Limpar todo o conteúdo existente do corpo
    body = doc.element.body
    for child in list(body):
        if child.tag != qn('w:sectPr'):  # Preservar configurações de seção
            body.remove(child)

    # OBRIGATÓRIO: Atualizar a barra lateral com o conteúdo da peça atual
    atualizar_barra_lateral(doc, texto_pedido="...", itens_sumario=["..."])

    # Inserir novo conteúdo seguindo a mesma lógica da função
    # criar_documento() acima
    # ...

    return doc
```

Esta abordagem garante que:
- A barra lateral com gradiente e conteúdo (Pedido/Sumário) é preservada
- O logo DPU no cabeçalho é mantido exatamente como no modelo
- A marca d'água no rodapé é preservada
- As fontes embutidas (Quattrocento Sans) permanecem no documento
- A barra lateral sólida das páginas internas é mantida

### Atualização do Conteúdo da Barra Lateral (OBRIGATÓRIO)

**ATENÇÃO: O template contém conteúdo fixo (Pedido + Sumário) de outro caso na barra lateral da primeira página. É OBRIGATÓRIO substituir esse conteúdo pelo resumo e sumário da peça atual. Se essa etapa for omitida, a peça será gerada com texto de outro processo na barra lateral.**

A barra lateral fica no `header2.xml` (header da primeira página), dentro de um shape `wps:wsp` com preenchimento `#D5DBE5` (azul-cinza claro, 35% opacidade). O conteúdo está em `<wps:txbx><w:txbxContent>`.

O namespace `wps` não está registrado no `qn()` do python-docx, então deve ser usado diretamente via lxml:

```python
from lxml import etree
from docx.oxml.ns import qn

def atualizar_barra_lateral(doc, texto_pedido, itens_sumario):
    """
    Atualiza o conteúdo da barra lateral na primeira página (header2).

    OBRIGATÓRIO ao usar o template. O template contém conteúdo de outro
    caso que DEVE ser substituído.

    Args:
        doc: Document do python-docx já carregado a partir do template
        texto_pedido: str - resumo do pedido/tese para exibir na barra lateral
        itens_sumario: list de str - títulos das seções (sumário da peça)
    """
    section = doc.sections[0]
    first_header = section.first_page_header
    header_element = first_header._element

    wps_ns = 'http://schemas.microsoft.com/office/word/2010/wordprocessingShape'
    for txbx in header_element.iter('{%s}txbx' % wps_ns):
        txbxContent = txbx.find(qn('w:txbxContent'))
        if txbxContent is None:
            continue

        # Verificar se é a textbox da barra lateral
        full_text = ''.join(t.text or '' for t in txbxContent.iter(qn('w:t')))
        if 'Pedido' not in full_text and 'Sum' not in full_text:
            continue

        # Limpar todo o conteúdo existente
        for child in list(txbxContent):
            txbxContent.remove(child)

        # Título "Pedido" — Quattrocento Sans, negrito, 14pt, cor #323E4F
        txbxContent.append(_criar_paragrafo_barra(
            texto="Pedido", fonte="Quattrocento Sans", tamanho=28,
            negrito=True, italico=False, cor="323e4f",
            space_before=120, space_after=240, line_spacing="276"))

        # Texto do pedido — Palatino Linotype, itálico, 11pt, cor #323E4F
        txbxContent.append(_criar_paragrafo_barra(
            texto=texto_pedido, fonte="Palatino Linotype", tamanho=22,
            negrito=False, italico=True, cor="323e4f",
            space_before=120, space_after=0, line_spacing="276"))

        # Título "Sumário" — Quattrocento Sans, negrito, 14pt, cor #323E4F
        txbxContent.append(_criar_paragrafo_barra(
            texto="Sumário", fonte="Quattrocento Sans", tamanho=28,
            negrito=True, italico=False, cor="323e4f",
            space_before=240, space_after=0, line_spacing="240"))

        # Itens do sumário — Quattrocento Sans, 9pt, cor #323E4F
        for item in itens_sumario:
            txbxContent.append(_criar_paragrafo_barra(
                texto=item, fonte="Quattrocento Sans", tamanho=18,
                negrito=False, italico=False, cor="323e4f",
                space_before=60, space_after=60, line_spacing="240"))

        break  # Encontramos a textbox correta


def _criar_paragrafo_barra(texto, fonte, tamanho, negrito, italico, cor,
                           space_before, space_after, line_spacing):
    """Cria elemento w:p para inserir na textbox da barra lateral."""
    p = etree.SubElement(etree.Element('dummy'), qn('w:p'))
    p.getparent().remove(p)

    pPr = etree.SubElement(p, qn('w:pPr'))
    spacing = etree.SubElement(pPr, qn('w:spacing'))
    spacing.set(qn('w:after'), str(space_after))
    spacing.set(qn('w:before'), str(space_before))
    spacing.set(qn('w:line'), str(line_spacing))
    ind = etree.SubElement(pPr, qn('w:ind'))
    ind.set(qn('w:left'), '0')
    ind.set(qn('w:right'), '0')
    ind.set(qn('w:firstLine'), '0')
    jc = etree.SubElement(pPr, qn('w:jc'))
    jc.set(qn('w:val'), 'both')
    td = etree.SubElement(pPr, qn('w:textDirection'))
    td.set(qn('w:val'), 'btLr')

    r = etree.SubElement(p, qn('w:r'))
    rPr = etree.SubElement(r, qn('w:rPr'))
    rFonts = etree.SubElement(rPr, qn('w:rFonts'))
    rFonts.set(qn('w:ascii'), fonte)
    rFonts.set(qn('w:cs'), fonte)
    rFonts.set(qn('w:eastAsia'), fonte)
    rFonts.set(qn('w:hAnsi'), fonte)
    b = etree.SubElement(rPr, qn('w:b'))
    b.set(qn('w:val'), '1' if negrito else '0')
    i = etree.SubElement(rPr, qn('w:i'))
    i.set(qn('w:val'), '1' if italico else '0')
    smallCaps = etree.SubElement(rPr, qn('w:smallCaps'))
    smallCaps.set(qn('w:val'), '0')
    strike = etree.SubElement(rPr, qn('w:strike'))
    strike.set(qn('w:val'), '0')
    color = etree.SubElement(rPr, qn('w:color'))
    color.set(qn('w:val'), cor)
    sz = etree.SubElement(rPr, qn('w:sz'))
    sz.set(qn('w:val'), str(tamanho))
    vertAlign = etree.SubElement(rPr, qn('w:vertAlign'))
    vertAlign.set(qn('w:val'), 'baseline')
    t = etree.SubElement(r, qn('w:t'))
    t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    t.text = texto

    return p
```

### Atualização do Rodapé da Primeira Página (OBRIGATÓRIO)

**O template contém o número do PAJ de outro processo no rodapé da primeira página (footer2.xml). É OBRIGATÓRIO substituí-lo.**

- Se o Defensor fornecer o número do PAJ, usar o formato: `PAJ XXXX/XXX-XXXXX/SIGLA`
- Se não houver número de PAJ, usar o número do processo: `PUIL 5003886-26.2022.4.04.7202/SC — Tema 384/TNU`

```python
def atualizar_rodape_primeira_pagina(doc, texto_rodape):
    """
    Substitui o texto do rodapé da primeira página (footer2).
    """
    section = doc.sections[0]
    first_footer = section.first_page_footer
    footer_element = first_footer._element

    for t_elem in footer_element.iter(qn('w:t')):
        if t_elem.text and 'PAJ' in t_elem.text:
            t_elem.text = texto_rodape
            return

    # Fallback: substituir primeiro texto encontrado
    for t_elem in footer_element.iter(qn('w:t')):
        if t_elem.text and t_elem.text.strip():
            t_elem.text = texto_rodape
            return
```

### Assinatura Padrão

As peças devem ser assinadas com o nome do Defensor responsável:

```
[cidade]/[UF], [data por extenso].

**[NOME DO DEFENSOR]**
Defensor Público Federal
```

O nome vem em negrito, centralizado, com espaçamento antes de 48pt. O cargo "Defensor Público Federal" vem logo abaixo, sem negrito. A cidade e data vêm um parágrafo acima, alinhadas à esquerda, sem negrito.

### Barra Lateral das Páginas Internas (Opcional)

A barra lateral sólida (`#323F4F`) que aparece nas páginas 2+ pode, eventualmente, ser utilizada para destacar trechos relevantes do texto daquela página (citações importantes, dados-chave, etc.). Essa funcionalidade é opcional e deve ser implementada caso a caso, conforme orientação do Defensor.

