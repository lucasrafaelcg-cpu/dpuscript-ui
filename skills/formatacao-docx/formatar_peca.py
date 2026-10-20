#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Biblioteca de formatação de peças jurídicas da DPU.
Converte texto estruturado em .docx formatado + PDF.

Versão 2.0: Suporte a notas de rodapé via Banco de Fontes Verificadas.
Marcadores [Fxxx] no texto são convertidos em notas de rodapé reais no DOCX
quando o parâmetro --banco é fornecido.
"""

import os
import sys
import re
import json
import platform
import unicodedata

# Forçar stdout/stderr para UTF-8 no Windows (evita erros de encoding no terminal)
if sys.stdout.encoding != 'utf-8':
    sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
if sys.stderr.encoding != 'utf-8':
    sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)

from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls
from lxml import etree

# Caminhos padrão — relativos à própria skill, para funcionar em qualquer
# workspace onde a pasta formatacao-docx/ for instalada (não hardcoded ao
# dpu-workspace original).
_SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(_SKILL_DIR, "assets", "template_modelo.docx")
SAIDA_DIR = os.path.join(_SKILL_DIR, "saida")

# ---------------------------------------------------------------------------
# Formatacao das pecas (padrao definido pelo Defensor)
#   - fonte Times New Roman
#   - tamanho 12 em TODO o texto, inclusive titulos de secao
#   - cor preta
# Alterar aqui muda o documento inteiro; nao espalhar valores pelo codigo.
# ---------------------------------------------------------------------------
FONTE_PECA = 'Times New Roman'
TAM_PECA = Pt(12)
COR_PECA = RGBColor(0, 0, 0)
TAM_PECA_HALFPT = '24'  # 12pt em half-points, para os trechos montados via XML

# Quem assina. Centralizado aqui porque a assinatura aparece em DOIS lugares:
# no fim (adicionada pelo script) e no CORPO das pecas com pagina de
# apresentacao (agravo, apelacao, contrarrazoes) — nessas, quem escreve a
# assinatura e' o texto da peca, e o processador precisa reconhece-la.
DEFENSOR_NOME = 'LUCAS RAFAEL GALDINO DE ARAÚJO LUCENA'
DEFENSOR_CARGO = 'Defensor Público Federal'


def _e_linha_assinatura(linha):
    """True se a linha e' o NOME ou o CARGO de quem assina.

    Usado para nao deixar essas linhas serem absorvidas pelo paragrafo em
    curso: o processador junta linhas consecutivas com espaco, e isso fazia
    "NOME Defensor Publico Federal" sair grudado numa linha justificada, em vez
    de duas linhas centralizadas.
    """
    t = re.sub(r'\*+', '', (linha or '')).strip().rstrip('.,;')
    if not t:
        return None

    def _sem_acento(s):
        # Comparacao insensivel a acento: a peca pode vir com "ARAUJO" sem
        # acento e ainda assim ser a assinatura. Sem isso a deteccao falhava
        # em silencio e o nome voltava a grudar no cargo.
        nfkd = unicodedata.normalize('NFKD', s)
        return ''.join(c for c in nfkd if not unicodedata.combining(c)).upper()

    alvo = _sem_acento(t)
    if alvo == _sem_acento(DEFENSOR_NOME):
        return 'assinatura_nome'
    if alvo == _sem_acento(DEFENSOR_CARGO):
        return 'assinatura_cargo'
    return None



def atualizar_barra_lateral(doc, texto_pedido, itens_sumario):
    """
    Atualiza o conteúdo da barra lateral na primeira página (header2).
    OBRIGATÓRIO ao usar o template.
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

        # Título "Pedido"
        txbxContent.append(_criar_paragrafo_barra(
            texto="Pedido", fonte=FONTE_PECA, tamanho=28,
            negrito=True, italico=False, cor="323e4f",
            space_before=120, space_after=240, line_spacing="276"))

        # Texto do pedido
        txbxContent.append(_criar_paragrafo_barra(
            texto=texto_pedido, fonte=FONTE_PECA, tamanho=22,
            negrito=False, italico=True, cor="323e4f",
            space_before=120, space_after=0, line_spacing="276"))

        # Título "Sumário"
        txbxContent.append(_criar_paragrafo_barra(
            texto="Sumário", fonte=FONTE_PECA, tamanho=28,
            negrito=True, italico=False, cor="323e4f",
            space_before=240, space_after=0, line_spacing="240"))

        # Itens do sumário
        for item in itens_sumario:
            txbxContent.append(_criar_paragrafo_barra(
                texto=item, fonte=FONTE_PECA, tamanho=18,
                negrito=False, italico=False, cor="323e4f",
                space_before=60, space_after=60, line_spacing="240"))

        break


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


def atualizar_rodape_primeira_pagina(doc, texto_rodape):
    """Substitui o texto do rodapé da primeira página (footer2)."""
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


def carregar_banco_fontes(banco_path):
    """Carrega o Banco de Fontes Verificadas (JSON)."""
    if not banco_path or not os.path.exists(banco_path):
        return None
    try:
        with open(banco_path, 'r', encoding='utf-8') as f:
            banco = json.load(f)
        fontes_map = {}
        for fonte in banco.get('fontes', []):
            fontes_map[fonte['id']] = fonte
        return fontes_map
    except Exception as e:
        print(f"[AVISO] Erro ao carregar Banco de Fontes: {e}")
        return None


def _formatar_texto_nota_rodape(fonte):
    """Formata o texto da nota de rodapé a partir de uma entrada do Banco."""
    citacao = fonte.get('citacao', '')
    verif = fonte.get('verificacao', {})
    metodo = verif.get('metodo', '')

    texto = citacao
    if metodo == 'url':
        texto += f". Disponível em: {verif.get('url', '')}"
    elif metodo == 'documento':
        doc = verif.get('documento', '')
        pag = verif.get('pagina', '')
        texto += f". Fonte: {doc}, p. {pag}"

    return texto


def _criar_nota_rodape_xml(doc, texto_nota, nota_id):
    """
    Cria uma nota de rodapé real no DOCX usando manipulação XML direta.
    Retorna o elemento w:r com a referência à nota.
    """
    # Acessar ou criar a parte de footnotes
    footnotes_part = None
    for rel in doc.part.rels.values():
        if "footnotes" in rel.reltype:
            footnotes_part = rel.target_part
            break

    if footnotes_part is None:
        # Se não existe parte de footnotes, criar nota simples inline
        return None

    # Acessar o XML — Part genérico usa .blob, XmlPart usa ._element
    if hasattr(footnotes_part, '_element'):
        footnotes_xml = footnotes_part._element
    else:
        # Part genérico: parsear o blob XML e reatribuir
        if not hasattr(footnotes_part, '_footnotes_xml_cache'):
            footnotes_part._footnotes_xml_cache = etree.fromstring(footnotes_part.blob)
        footnotes_xml = footnotes_part._footnotes_xml_cache
    ns = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    footnote = etree.SubElement(footnotes_xml, qn('w:footnote'))
    footnote.set(qn('w:id'), str(nota_id))

    # Parágrafo da nota
    p = etree.SubElement(footnote, qn('w:p'))
    pPr = etree.SubElement(p, qn('w:pPr'))
    pStyle = etree.SubElement(pPr, qn('w:pStyle'))
    pStyle.set(qn('w:val'), 'FootnoteText')

    # Run com referência da nota
    r_ref = etree.SubElement(p, qn('w:r'))
    rPr_ref = etree.SubElement(r_ref, qn('w:rPr'))
    rStyle = etree.SubElement(rPr_ref, qn('w:rStyle'))
    rStyle.set(qn('w:val'), 'FootnoteReference')
    fn_ref = etree.SubElement(r_ref, qn('w:footnoteRef'))

    # Run com texto da nota
    r_text = etree.SubElement(p, qn('w:r'))
    rPr_text = etree.SubElement(r_text, qn('w:rPr'))
    rFonts = etree.SubElement(rPr_text, qn('w:rFonts'))
    rFonts.set(qn('w:ascii'), FONTE_PECA)
    rFonts.set(qn('w:hAnsi'), FONTE_PECA)
    sz = etree.SubElement(rPr_text, qn('w:sz'))
    sz.set(qn('w:val'), TAM_PECA_HALFPT)  # 12pt
    t = etree.SubElement(r_text, qn('w:t'))
    t.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    t.text = f" {texto_nota}"

    return nota_id


def _inserir_referencia_nota(paragrafo_element, nota_id, posicao_run=None):
    """
    Insere referência de nota de rodapé (número sobrescrito) no parágrafo.
    Retorna o run XML criado.
    """
    r = etree.SubElement(paragrafo_element, qn('w:r'))
    rPr = etree.SubElement(r, qn('w:rPr'))
    rStyle = etree.SubElement(rPr, qn('w:rStyle'))
    rStyle.set(qn('w:val'), 'FootnoteReference')
    fn_ref = etree.SubElement(r, qn('w:footnoteReference'))
    fn_ref.set(qn('w:id'), str(nota_id))
    return r


def _numero_sobrescrito(n):
    """Converte número inteiro em string Unicode sobrescrita."""
    superscripts = {'0': '\u2070', '1': '\u00b9', '2': '\u00b2', '3': '\u00b3',
                    '4': '\u2074', '5': '\u2075', '6': '\u2076', '7': '\u2077',
                    '8': '\u2078', '9': '\u2079'}
    return ''.join(superscripts[d] for d in str(n))


def processar_notas_rodape(doc, texto, banco_fontes):
    """
    Processa marcadores [Fxxx] no texto e prepara mapeamento para notas de rodapé.
    Substitui marcadores por números sobrescritos Unicode e gera seção de notas ao final.
    Retorna: (texto_com_notas, lista_notas)
    """
    if not banco_fontes:
        return texto, []

    pattern = r'\[F(\d{3})\]'
    notas = []
    contador_nota = 1

    # Encontrar todos os marcadores e suas fontes
    for match in re.finditer(pattern, texto):
        id_fonte = f"F{match.group(1)}"
        if id_fonte in banco_fontes:
            fonte = banco_fontes[id_fonte]
            texto_nota = _formatar_texto_nota_rodape(fonte)

            notas.append({
                'id_fonte': id_fonte,
                'nota_id': contador_nota,
                'texto_nota': texto_nota,
                'marcador': match.group(0),
            })
            contador_nota += 1

    # Substituir marcadores por números sobrescritos Unicode
    nota_idx = [0]  # usar lista para closure mutável
    def _substituir(match):
        id_fonte = f"F{match.group(1)}"
        if id_fonte in banco_fontes:
            # Encontrar a nota correspondente
            for nota in notas:
                if nota['id_fonte'] == id_fonte:
                    return _numero_sobrescrito(nota['nota_id'])
        return ''
    texto_com_notas = re.sub(pattern, _substituir, texto)

    # Notas serão adicionadas APÓS a assinatura pelo criar_documento
    return texto_com_notas, notas


_PALAVRAS_ENDERECAMENTO = (
    # Judiciais
    "EXCELENT", "SENHOR", "SENHORA", "DOUTOR", "DOUTORA", "JUIZ", "JUÍZO",
    "DESEMBARGADOR", "MINISTRO", "TURMA", "VARA", "TRIBUNAL", "JUIZADO",
    # Administrativos. A DPU também peticiona fora do Judiciário — defesa em
    # processo de apuração do INSS, recurso à JR/CRPS, requerimento a órgão —
    # e a lista só judicial não reconhecia nada disso. Foi o que aconteceu na
    # defesa administrativa do PAJ 2026/056-00747, endereçada "AO INSTITUTO
    # NACIONAL DO SEGURO SOCIAL": o endereçamento caiu no corpo, com recuo de
    # parágrafo comum, e a qualificação foi junto.
    "INSTITUTO NACIONAL DO SEGURO SOCIAL", "INSS", "PROCESSO ADMINISTRATIVO",
    "SUPERINTEND", "GERÊNCIA EXECUTIVA", "AGÊNCIA DA PREVIDÊNCIA",
    "JUNTA DE RECURSOS", "CÂMARA DE JULGAMENTO", "CONSELHO DE RECURSOS",
    "PROCURADORIA", "MINISTÉRIO", "SECRETARIA", "DELEGAD", "OUVIDORIA",
    "PRESIDENTE", "DIRETOR", "COORDENADOR", "CHEFE", "COMISSÃO",
)

# Endereçamento que não cita nenhum órgão conhecido ainda assim se reconhece
# pela FORMA: primeira linha, aberta por "AO/À/AOS/ÀS", em caixa alta e curta.
# Regra estrutural, para não depender de a lista acima cobrir todo órgão do
# Brasil.
_RE_ENDERECAMENTO_FORMA = re.compile(
    r"^\s*(?:AOS?|ÀS?|EXCELENT|ILUSTR|MERIT[ÍI]SSIM)\b", re.IGNORECASE)

_PALAVRAS_QUALIFICACAO = (
    "PROCESSO", "AUTOR", "RÉU", "REU", "REQUERENTE", "REQUERIDO",
    "EXEQUENTE", "EXECUTADO", "IMPETRANTE", "IMPETRADO", "RECORRENTE",
    "RECORRIDO", "AGRAVANTE", "AGRAVADO", "EMBARGANTE", "EMBARGADO",
    "APELANTE", "APELADO", "PAJ", "PARTES",
)


def _parece_enderecamento(paragrafo):
    """O parágrafo é o endereçamento da peça?

    Dois caminhos. O primeiro cita um órgão conhecido ('EXCELENTÍSSIMO...',
    'AO INSTITUTO NACIONAL DO SEGURO SOCIAL...'). O segundo vale pela FORMA:
    linha única, aberta por AO/À, em caixa alta e curta — é assim que se
    endereça a órgão que a lista não prevê.
    """
    if not paragrafo:
        return False
    texto = paragrafo.strip()

    # A FORMA vem primeiro, e é ela que barra a prosa. Antes bastava a palavra
    # em qualquer posição, e "JUIZ" casava dentro de "ajuizada": a frase
    # "Trata-se de ação monitória ajuizada por..." passava por endereçamento.
    if "\n" in texto or len(texto) > 300:
        return False
    letras = [c for c in texto if c.isalpha()]
    if len(letras) < 10:
        return False
    caixa_alta = sum(1 for c in letras if c.isupper()) / len(letras) >= 0.8
    abre_como = bool(_RE_ENDERECAMENTO_FORMA.match(texto))
    if not (caixa_alta or abre_como):
        return False

    alto = texto.upper()
    tem_palavra = any(re.search(r"\b" + re.escape(p), alto)
                      for p in _PALAVRAS_ENDERECAMENTO)
    # Órgão conhecido, ou o desenho inconfundível: "AO/À <ÓRGÃO EM CAIXA ALTA>".
    return tem_palavra or (abre_como and caixa_alta)


# Linha de qualificação: "Rótulo: valor" ou "Rótulo nº valor", ANCORADA no
# início da linha. A checagem anterior era por substring em qualquer posição
# do parágrafo, o que impedia incluir rótulos curtos: "RÉ" casaria dentro de
# "RÉPLICA", e "AUTOR" dentro de "AUTORIDADE". Ancorando no rótulo, os
# femininos entram sem risco — e era justamente "Ré: UNIÃO FEDERAL" que não
# era reconhecido na petição do PAJ 2026/056-00562.
# Os rótulos de parte terminam em -o no masculino e -a no feminino
# ("Requerido:" / "Requerida:"), e o padrão anterior só previa o feminino
# (`requerida?s?` = requerid + a? + s?). Com isso, TODA linha de rótulo
# masculino era reprovada — "Requerido:", "Executado:", "Embargado:",
# "Recorrido:", "Agravado:", "Apelado:", "Impetrado:" — e o bloco inteiro de
# qualificação caía no corpo da peça. Defeito anterior a 12/10/2026,
# encontrado ao corrigir o endereçamento.
_ROTULOS_QUALIFICACAO = (
    r'processos?|autos|paj|proc\.?|classe|assunto|valor(?: da causa)?|'
    r'ju[íi]zo|vara|se[cç][ãa]o|decis[ãa]o(?: agravada| recorrida)?|origem|'
    r'autor(?:a|es|as)?|r[ée]|r[ée]u|r[ée]s|requerentes?|requerid[oa]s?|'
    r'exequentes?|executad[oa]s?|impetrantes?|impetrad[oa]s?|'
    r'recorrentes?|recorrid[oa]s?|agravantes?|agravad[oa]s?|'
    r'embargantes?|embargad[oa]s?|apelantes?|apelad[oa]s?|'
    r'assistid[oa]s?|curatelad[oa]|interessad[oa]s?|litisconsortes?|terceiros?|'
    r'partes|benef[íi]cio|nb|esp[ée]cie|der'
)

# Rótulo COMPOSTO, que é como a peça nomeia quem acumula duas posições:
# "Réu/Embargante:", "Autor/Embargado:", "Executado - Embargante:". Sem isso,
# `_parece_qualificacao` reprovava o bloco inteiro (ela exige que TODAS as
# linhas tenham forma de rótulo) e a qualificação caía no corpo, com recuo de
# parágrafo comum e sem negrito no nome das partes — foi o que aconteceu nos
# embargos monitórios do PAJ 2026/056-00550.
_RE_LINHA_QUALIFICACAO = re.compile(
    r'(?i)^\s*(?:' + _ROTULOS_QUALIFICACAO + r')'
    r'(?:\s*[/\-–]\s*(?:' + _ROTULOS_QUALIFICACAO + r')){0,2}'
    r'\s*(?::|n?[ºo°.]\s*\d|\s+n[ºo°])'
)

# Linha que é só o número do processo/PAJ, sem rótulo.
_RE_LINHA_SO_NUMERO = re.compile(r'^\s*[\d.\-/]{10,}\s*$')


def _parece_qualificacao(paragrafo):
    """Heurística: o parágrafo é um bloco de qualificação processual (número
    do processo, partes, juízo — uma por linha), e não prosa corrida.

    Exige que TODAS as linhas tenham forma de rótulo. Antes bastava UMA
    palavra-chave em qualquer lugar do parágrafo, o que tornava arriscado
    percorrer vários parágrafos seguidos: um trecho de prosa com a palavra
    "requerido" seria absorvido no cabeçalho.
    """
    if not paragrafo:
        return False
    linhas = [l.strip() for l in paragrafo.strip().split('\n') if l.strip()]
    if not linhas or any(len(l) > 220 for l in linhas):
        return False
    return all(
        _RE_LINHA_QUALIFICACAO.match(l) or _RE_LINHA_SO_NUMERO.match(l)
        for l in linhas
    )


def _detectar_cabecalho(texto):
    """Detecta, no início do texto, o bloco de endereçamento + qualificação
    processual que antecede a apresentação da peça.

    Convenção (ver SKILL.md): 1º parágrafo = endereçamento formal; 2º
    parágrafo, se parecer qualificação (nº do processo + partes, uma linha
    cada), é tratado como tal.

    Retorna (enderecamento, linhas_qualificacao, resto_do_texto). Se não
    detectar o padrão, retorna (None, [], texto) — texto inalterado.
    """
    partes = texto.strip().split('\n\n')
    if not partes or not _parece_enderecamento(partes[0]):
        return None, [], texto

    enderecamento = partes[0].strip()
    resto_partes = partes[1:]
    linhas_qualif = []

    # Consome TODOS os paragrafos seguidos que pareçam qualificação, e não
    # apenas o primeiro. O bloco costuma vir escrito com linha em branco entre
    # cada item:
    #
    #     Processo nº 0025467-29.2026.4.05.8201
    #
    #     Autor: JOSE FERREIRA DE AMARANTE
    #
    #     Ré: UNIÃO FEDERAL
    #
    # Lendo só o primeiro, as demais linhas caíam no corpo da peça: saíam COM
    # RECUO e, pior, `_extrair_nomes_partes` não via nome nenhum, de modo que
    # nenhuma parte era negritada em todo o texto. Foi o defeito apontado na
    # petição do PAJ 2026/056-00562.
    #
    # O limite de 8 evita que um texto atípico engula o corpo da peça; a prosa
    # de apresentação já é rejeitada por `_parece_qualificacao`, que recusa
    # linha com mais de 220 caracteres.
    while resto_partes and len(linhas_qualif) < 8 and _parece_qualificacao(resto_partes[0]):
        linhas_qualif += [
            l.strip() for l in resto_partes[0].strip().split('\n') if l.strip()
        ]
        resto_partes = resto_partes[1:]

    resto = '\n\n'.join(resto_partes)
    return enderecamento, linhas_qualif, resto


# Marcador de quebra de pagina no .txt. Usado principalmente pelo AGRAVO DE
# INSTRUMENTO, que tem folha de interposição (ao Desembargador Relator) e, em
# pagina nova, as razões (endereçadas à Corte).
_RE_QUEBRA_PAGINA = re.compile(
    r'^[ \t]*(?:\[(?:NOVA[ _]*P[ÁA]GINA|QUEBRA(?:[ _]*DE)?[ _]*P[ÁA]GINA)\]|\f)[ \t]*$',
    re.I | re.M,
)


def _inserir_quebra_pagina(doc):
    """Insere uma quebra de pagina real no documento."""
    from docx.enum.text import WD_BREAK

    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.first_line_indent = Pt(0)
    p.add_run().add_break(WD_BREAK.PAGE)


def _render_enderecamento(doc, enderecamento):
    """Endereçamento em negrito, justificado, sem recuo. Cada linha do texto
    vira um parágrafo."""
    if not enderecamento:
        return
    linhas = enderecamento.split('\n')
    for i, linha in enumerate(linhas):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(12) if i == len(linhas) - 1 else Pt(2)
        p.paragraph_format.first_line_indent = Pt(0)
        run = p.add_run(linha)
        run.bold = True
        run.font.name = FONTE_PECA
        run.font.size = TAM_PECA
        run.font.color.rgb = COR_PECA


def _render_qualificacao(doc, linhas_qualif, pular_linhas=0):
    """Qualificação processual: uma linha por parágrafo, sem negrito nem recuo.
    `pular_linhas` insere N parágrafos vazios depois (espaço antes da
    apresentação da peça)."""
    if not linhas_qualif:
        return
    for linha in linhas_qualif:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.first_line_indent = Pt(0)
        # Interpreta **negrito** inline: o nome da parte pode ter sido marcado
        # por _negritar_partes. Sem isso os asteriscos vazariam literalmente.
        _adicionar_runs_com_negrito(
            p, linha, FONTE_PECA, TAM_PECA, COR_PECA
        )
    for _ in range(pular_linhas):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.first_line_indent = Pt(0)


def _extrair_nomes_partes(linhas_qualif):
    """Extrai os nomes das partes das linhas de qualificação (ex.:
    'Executado: WELLINGTON RODRIGUES MOREIRA (citado por edital)' ->
    'WELLINGTON RODRIGUES MOREIRA'). Ignora a linha do número do processo."""
    # Rotulos que NAO designam parte (numero de processo/PAJ, valores, prazos).
    # Sem isso, "Autos na origem: 0802152-10.2024.4.05.8200" faria o numero do
    # processo ser tratado como nome de parte e sair em negrito/caixa alta.
    # Rotulos de CONTEXTO, nao de parte. Os quatro ultimos grupos entraram em
    # 20/10/2026: "Beneficio: NB 32/640.501.368-9 - aposentadoria por
    # incapacidade permanente" tem duas palavras longas e passava por nome,
    # saindo em CAIXA ALTA e negrito no cabecalho da defesa administrativa do
    # PAJ 2026/056-00747.
    rotulo_nao_parte = re.compile(
        r'(?i)^\s*(processo|autos|paj|proc\.?|n[uú]mero|valor|prazo|classe|'
        r'assunto|pretens|of[íi]cio|origem|'
        r'benef[íi]cio|nb|esp[ée]cie|der|'
        r'ju[íi]zo|vara|se[cç][ãa]o|decis[ãa]o)'
    )
    nomes = []
    for linha in linhas_qualif:
        if rotulo_nao_parte.match(linha):
            continue
        m = re.match(r'^[^:]+:\s*(.+)$', linha)
        if not m:
            continue
        nome = re.sub(r'\s*\([^)]*\)\s*$', '', m.group(1)).strip().rstrip('.,;')
        nome = nome.replace('*', '').strip()
        # Corta o documento colado no nome: "WELLITON DANTAS DA SILVA - CPF
        # 797.577.404-97". Mantido, o nome so' casaria na propria linha de
        # qualificacao e NAO no corpo da peca, onde ele aparece sozinho — a
        # parte ficava sem negrito em todas as demais mencoes.
        nome = re.sub(
            r'(?i)\s*[-–—,;]?\s*\b(?:CPF|CNPJ|RG|NB|OAB|MATR[ÍI]CULA|'
            r'INSCRI[ÇC][ÃA]O)\b.*$', '', nome).strip().rstrip('.,;-–—')
        # Precisa parecer NOME: ao menos duas palavras de 3+ letras. Isso
        # descarta numeros de processo, siglas isoladas e datas.
        palavras = re.findall(r'[^\W\d_]{3,}', nome)
        if len(nome) >= 4 and len(palavras) >= 2:
            nomes.append(nome)
    return nomes


# Sufixos genéricos: "UNIÃO FEDERAL" também aparece no corpo como "União",
# e "BANCO DO BRASIL S.A." como "Banco do Brasil". Sem a forma curta, a parte
# ficava sem negrito na maioria das mençőes.
_SUFIXOS_GENERICOS = (
    'FEDERAL', 'S.A.', 'S/A', 'SA', 'LTDA', 'ME', 'EPP', 'EIRELI',
    'DO BRASIL', 'BRASIL',
)

# Palavras que, aparecendo pouco antes, indicam que a ocorrência faz parte do
# nome de OUTRA instituição: "Defensoria Pública da União", "Advocacia-Geral
# da União", "Procuradoria da União". Ali a palavra não designa a parte e não
# pode ser negritada, ou o nome alheio sairia partido ao meio.
_RE_CONTEXTO_INSTITUCIONAL = re.compile(
    r'(?i)(?:defensoria|advocacia|procuradoria|minist[ée]rio|secretaria|'
    r'tribunal|conselho|ag[êe]ncia|instituto|banco)\b[^.;:\n]{0,40}$'
)


def _formas_do_nome(nome):
    """Nome completo e, quando houver sufixo genérico, a forma curta."""
    formas = [nome]
    alto = nome.upper().strip()
    for suf in _SUFIXOS_GENERICOS:
        if alto.endswith(' ' + suf):
            curto = nome[: len(nome) - len(suf) - 1].strip().rstrip(',')
            # Só vale como forma curta se ainda for palavra de verdade.
            if len(curto) >= 4 and re.search(r'[^\W\d_]{4,}', curto):
                formas.append(curto)
            break
    return formas


def _negritar_partes(texto, nomes):
    """Coloca em negrito e CAIXA ALTA toda ocorrência do nome de cada parte
    no texto, em qualquer capitalização (inclusive se o texto já trouxer o
    nome parcialmente marcado com `**`) — ver SKILL.md, seção de partes.

    Cobre também a forma curta ("UNIÃO FEDERAL" -> "União" no corpo), pulando
    as ocorrências que integram o nome de outra instituição.
    """
    candidatos = []
    for nome in nomes:
        candidatos += _formas_do_nome(nome)
    candidatos = sorted(set(c for c in candidatos if c.strip()), key=len, reverse=True)
    if not candidatos:
        return texto

    # UMA passagem só, com alternação do mais longo para o mais curto.
    #
    # Substituir forma por forma, em laços, corrompia o texto: a longa marcava
    # "**UNIÃO FEDERAL**" e em seguida a curta casava o "**UNIÃO" de dentro,
    # devolvendo "**UNIÃO** FEDERAL**" — asterisco solto no documento e só
    # metade do nome em negrito. Numa passagem única, cada trecho é consumido
    # uma vez e a forma longa sempre vence.
    padrao = re.compile(
        r'\*{0,2}(' + '|'.join(re.escape(c) for c in candidatos) + r')\*{0,2}',
        re.IGNORECASE,
    )

    def _troca(m):
        if _RE_CONTEXTO_INSTITUCIONAL.search(m.string[: m.start()]):
            return m.group(0)   # integra o nome de outra instituição: não mexe
        return f'**{m.group(1).upper()}**'

    return padrao.sub(_troca, texto)


def criar_documento(
    conteudo_txt,
    enderecamento,
    titulo_peca,
    subtitulo=None,
    numero_paj=None,
    numero_processo=None,
    texto_pedido=None,
    itens_sumario=None,
    template_path=None,
    banco_path=None,
    enderecamento_padrao='',
    titulo_padrao='',
):
    """
    Cria documento .docx formatado a partir de texto estruturado.

    Args:
        conteudo_txt: str - Texto completo da peça com marcadores:
            ## Título Principal (Heading 1)
            ### Subtítulo (Heading 3)
            > Citação longa (recuo 4cm, fonte 10pt)
            [Fxxx] Marcador de fonte (convertido em nota de rodapé se banco fornecido)
            Texto normal (parágrafo com recuo de primeira linha)

        enderecamento: str - "EXCELENTÍSSIMO SENHOR..."
        titulo_peca: str - "AGRAVO INTERNO"
        subtitulo: str (opcional) - Subtítulo abaixo do título
        numero_paj: str (opcional) - "PAJ 2023/040-06077/BVBA"
        numero_processo: str (opcional) - Usado no rodapé se não houver PAJ
        texto_pedido: str (opcional) - Resumo para barra lateral
        itens_sumario: list (opcional) - Itens do sumário para barra lateral
        template_path: str (opcional) - Caminho customizado do template
        banco_path: str (opcional) - Caminho do Banco de Fontes Verificadas (JSON).
            Se fornecido, marcadores [Fxxx] são convertidos em notas de rodapé.

    Returns:
        Document - Documento python-docx pronto para salvar
    """
    if template_path is None:
        template_path = TEMPLATE_PATH

    print("Carregando template...")
    doc = Document(template_path)

    # Estilo Normal do documento: o template vem com outra fonte/cor, e qualquer
    # texto que nao receba formatacao explicita herdaria dali. Fixar aqui garante
    # Times New Roman 12 preto em todo o documento.
    _estilo = doc.styles['Normal']
    _estilo.font.name = FONTE_PECA
    _estilo.font.size = TAM_PECA
    _estilo.font.color.rgb = COR_PECA
    # rFonts precisa ser setado tambem no XML para valer em textos non-ASCII
    _rpr = _estilo.element.get_or_add_rPr()
    _rfonts = _rpr.get_or_add_rFonts()
    for _attr in ('w:ascii', 'w:hAnsi', 'w:cs', 'w:eastAsia'):
        _rfonts.set(qn(_attr), FONTE_PECA)

    # Carregar Banco de Fontes e processar notas de rodapé
    banco_fontes = None
    notas_rodape = []
    if banco_path:
        banco_fontes = carregar_banco_fontes(banco_path)
        if banco_fontes:
            print(f"[OK] Banco de Fontes carregado: {len(banco_fontes)} fontes")
            conteudo_txt, notas_rodape = processar_notas_rodape(doc, conteudo_txt, banco_fontes)
            if notas_rodape:
                print(f"[OK] {len(notas_rodape)} notas de verificação inseridas no texto")

    # Limpar conteúdo do corpo, preservando seção
    body = doc.element.body
    for child in list(body):
        if child.tag != qn('w:sectPr'):
            body.remove(child)

    # OBRIGATÓRIO: Atualizar barra lateral — SEMPRE, para não deixar texto do modelo
    print("Atualizando barra lateral...")
    texto_pedido_barra = texto_pedido or _extrair_texto_pedido(conteudo_txt)
    itens_sumario_barra = itens_sumario or _extrair_sumario(conteudo_txt) or ['(sem sumário)']
    atualizar_barra_lateral(doc, texto_pedido_barra, itens_sumario_barra)

    # OBRIGATÓRIO: Atualizar rodapé
    print("Atualizando rodapé...")
    texto_rodape = numero_paj if numero_paj else numero_processo
    if texto_rodape:
        atualizar_rodape_primeira_pagina(doc, texto_rodape)

    # Processar conteúdo
    print("Processando conteúdo...")
    # Remove assinatura que ja venha no texto, para nao duplicar com a
    # assinatura institucional adicionada por _adicionar_assinatura.
    conteudo_txt = _remover_assinatura_existente(conteudo_txt)

    # Detecta bloco de endereçamento + qualificação processual no início do
    # texto. So' nao entra em acao quando o chamador passou enderecamento ou
    # titulo EXPLICITOS — o padrao do tipo de peca nao conta, porque e'
    # fallback, nao instrucao.
    #
    # Ate 12/10/2026 o padrao do tipo chegava aqui ja' dentro de
    # `enderecamento`, e a deteccao era pulada. O resultado, na inicial do PAJ
    # 2026/056-00731: o generico "MERITISSIMO JUIZO FEDERAL" no topo e o
    # enderecamento de verdade ("AO JUIZO DA ___a VARA DO JUIZADO ESPECIAL
    # FEDERAL...") caido no corpo, com recuo de 2,5 cm de paragrafo comum.
    # Atingia todo tipo de peca com padrao nao vazio, ou seja, todos menos o
    # despacho.
    linhas_qualif = []
    cabecalho_detectado = False
    if not enderecamento and not titulo_peca:
        detectado, linhas_qualif, resto = _detectar_cabecalho(conteudo_txt)
        if detectado:
            enderecamento = detectado
            conteudo_txt = resto
            cabecalho_detectado = True

    # Nada detectado e nada explicito: ai' sim valem os padroes do tipo. Com
    # cabecalho detectado o titulo continua omitido, para nao nomear a peca
    # duas vezes — o texto ja' traz a denominacao.
    if not enderecamento:
        enderecamento = enderecamento_padrao
    if not titulo_peca and not cabecalho_detectado:
        titulo_peca = titulo_padrao

    # Nomes das partes (extraidos da qualificacao) sempre em NEGRITO e
    # CAIXA ALTA no corpo da peca, onde quer que sejam citados (ver SKILL.md).
    # Varre a qualificacao de TODOS os blocos: no agravo, Agravante/Agravado
    # aparecem na folha de razoes (2o bloco), nao na folha de interposicao.
    qualif_todas = list(linhas_qualif)
    for _bloco in _RE_QUEBRA_PAGINA.split(conteudo_txt)[1:]:
        _e, _q, _r = _detectar_cabecalho(_bloco)
        if _e:
            qualif_todas.extend(_q)
    nomes_partes = _extrair_nomes_partes(qualif_todas)
    if nomes_partes:
        conteudo_txt = _negritar_partes(conteudo_txt, nomes_partes)
        # "Sempre" inclui a propria linha de qualificacao: o rotulo continua
        # normal ("Requerente:") e o NOME sai em negrito e caixa alta.
        # `_render_qualificacao` interpreta os `**`.
        linhas_qualif = [_negritar_partes(l, nomes_partes) for l in linhas_qualif]

    _render_enderecamento(doc, enderecamento)
    _render_qualificacao(doc, linhas_qualif, pular_linhas=6)

    # Título da peça (opcional — omitido quando o cabeçalho acima foi
    # detectado automaticamente, para não nomear a peça no corpo do documento).
    if titulo_peca:
        p_tit = doc.add_paragraph()
        p_tit.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_tit.paragraph_format.space_before = Pt(12)
        p_tit.paragraph_format.space_after = Pt(24) if not subtitulo else Pt(6)
        p_tit.paragraph_format.first_line_indent = Pt(0)
        run = p_tit.add_run(titulo_peca)
        run.bold = True
        run.font.name = FONTE_PECA
        run.font.size = TAM_PECA
        run.font.color.rgb = COR_PECA

    # Subtítulo (se houver)
    if subtitulo:
        p_sub = doc.add_paragraph()
        p_sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_sub.paragraph_format.space_before = Pt(0)
        p_sub.paragraph_format.space_after = Pt(36)
        p_sub.paragraph_format.first_line_indent = Pt(0)
        run = p_sub.add_run(subtitulo)
        run.font.name = FONTE_PECA
        run.font.size = TAM_PECA
        run.font.color.rgb = COR_PECA

    # Corpo — dividido em BLOCOS pelo marcador de quebra de pagina. Cada bloco
    # apos o primeiro comeca em nova pagina e tem o proprio cabecalho detectado
    # (endereçamento + qualificação), porque o AGRAVO DE INSTRUMENTO tem duas
    # folhas com endereçamentos distintos: a 1a ao Desembargador Relator
    # (interposição) e a 2a à Corte (razões). Ver SKILL.md.
    print("Inserindo conteúdo...")
    blocos = _RE_QUEBRA_PAGINA.split(conteudo_txt)
    for i, bloco in enumerate(blocos):
        if i > 0:
            _inserir_quebra_pagina(doc)
            end_b, qualif_b, resto_b = _detectar_cabecalho(bloco)
            if end_b:
                _render_enderecamento(doc, end_b)
                # Sem as 6 linhas em branco aqui: elas separam qualificação e
                # apresentação na 1a folha; na folha de razões o texto segue logo.
                _render_qualificacao(doc, qualif_b, pular_linhas=0)
                bloco = resto_b
        for item in _processar_texto(bloco):
            _adicionar_paragrafo(doc, item)

    # Assinatura
    print("Adicionando assinatura...")
    _adicionar_assinatura(doc)

    # Seção de citações (após assinatura, em nova página)
    if notas_rodape:
        print("Adicionando seção de citações...")
        _adicionar_secao_citacoes(doc, notas_rodape)

    return doc


def _processar_texto(texto):
    """
    Processa texto com marcadores e retorna lista de parágrafos estruturados.

    Marcadores suportados:
        ## Título Principal → heading1
        ### Subtítulo → heading3
        > Citação longa → citacao_longa
        **texto** → negrito inline (dentro de parágrafos normais e citações)
        Texto normal → normal

    IMPORTANTE:
        - O texto de entrada DEVE usar estes marcadores específicos
        - **negrito** funciona inline em parágrafos normais e citações longas
        - *itálico* NÃO é suportado
        - Salve o arquivo .txt com encoding='utf-8' para evitar corrupção de acentos
        - Use linhas em branco para separar parágrafos

    Exemplo de texto correto:
        ## I – INTRODUÇÃO

        Primeiro parágrafo.

        Segundo parágrafo.

        ### Subtópico

        Texto do subtópico.

        > Citação longa com recuo.

        Texto normal.
    """
    linhas = texto.split('\n')
    paragrafos = []
    buffer = []
    tipo_atual = 'normal'

    for linha in linhas:
        linha_stripped = linha.strip()

        if linha_stripped.startswith('## '):
            # Heading 1
            if buffer:
                paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})
                buffer = []
            texto = linha_stripped[3:].strip()
            paragrafos.append({'texto': texto, 'tipo': 'heading1'})
            tipo_atual = 'normal'

        elif linha_stripped.startswith('### '):
            # Heading 3
            if buffer:
                paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})
                buffer = []
            texto = linha_stripped[4:].strip()
            paragrafos.append({'texto': texto, 'tipo': 'heading3'})
            tipo_atual = 'normal'

        elif _e_linha_assinatura(linha_stripped):
            # Nome ou cargo de quem assina: paragrafo PROPRIO e centralizado.
            # Fecha o paragrafo em curso para nao grudar na linha anterior.
            if buffer:
                paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})
                buffer = []
            paragrafos.append({
                'texto': re.sub(r'\*+', '', linha_stripped).strip(),
                'tipo': _e_linha_assinatura(linha_stripped),
            })
            tipo_atual = 'normal'

        elif linha_stripped.upper().startswith('[ASSINATURA]'):
            # Bloco de assinatura completo (nome + cargo), util na pagina de
            # apresentacao das pecas recursais.
            if buffer:
                paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})
                buffer = []
            paragrafos.append({'texto': DEFENSOR_NOME, 'tipo': 'assinatura_nome'})
            paragrafos.append({'texto': DEFENSOR_CARGO, 'tipo': 'assinatura_cargo'})
            tipo_atual = 'normal'

        elif linha_stripped.upper().startswith('[DENOMINACAO]') \
                or linha_stripped.upper().startswith('[DENOMINAÇÃO]'):
            # Denominacao da acao/peca — vai em caixa destacada (ver
            # `_render_denominacao`). Fecha o paragrafo em curso antes.
            if buffer:
                paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})
                buffer = []
            texto = linha_stripped[linha_stripped.index(']') + 1:].strip()
            paragrafos.append({'texto': texto, 'tipo': 'denominacao'})
            tipo_atual = 'normal'

        elif linha_stripped.startswith('>'):
            # Citação longa
            if buffer and tipo_atual != 'citacao_longa':
                paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})
                buffer = []
            texto = linha_stripped[1:].strip()
            if texto:
                buffer.append(texto)
            tipo_atual = 'citacao_longa'

        elif linha_stripped == '':
            # Linha vazia - finalizar parágrafo
            if buffer:
                paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})
                buffer = []
            tipo_atual = 'normal'

        else:
            # Linha de texto normal
            buffer.append(linha.rstrip())

    # Finalizar último parágrafo
    if buffer:
        paragrafos.append({'texto': ' '.join(buffer), 'tipo': tipo_atual})

    return paragrafos


def _adicionar_runs_com_negrito(p, texto, font_name, font_size, font_color, bold_base=False):
    """
    Adiciona runs ao parágrafo interpretando marcadores **texto** como negrito inline.
    Segmentos fora de ** herdam bold_base; segmentos dentro de ** ficam em negrito.
    """
    partes = re.split(r'(\*\*.*?\*\*)', texto)
    for parte in partes:
        if parte.startswith('**') and parte.endswith('**') and len(parte) > 4:
            conteudo = parte[2:-2]
            run = p.add_run(conteudo)
            run.bold = True
        else:
            run = p.add_run(parte)
            run.bold = bold_base
        run.font.name = font_name
        run.font.size = font_size
        run.font.color.rgb = font_color


COR_SOMBRA_DENOMINACAO = 'D9D9D9'  # cinza claro do sombreamento da caixa
COR_BORDA_DENOMINACAO = '000000'


def _render_denominacao(doc, texto):
    """Denominacao da acao/peca numa CAIXA destacada.

    Padrao definido pelo Defensor: centralizada, em negrito, com as quatro
    bordas externas marcadas e sombreamento cinza. E' o nome da acao na
    peticao inicial (ex.: "ACAO DE RESTABELECIMENTO DE BPC/LOAS"), que fica
    entre a qualificacao do autor e o "em face de ...".

    Bordas e sombreamento nao tem API no python-docx: e' preciso montar
    `w:pBdr` e `w:shd` no XML do paragrafo.
    """
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    pf = p.paragraph_format
    pf.space_before = Pt(12)
    pf.space_after = Pt(12)
    pf.line_spacing = 1.0
    pf.first_line_indent = Cm(0)
    pf.left_indent = Cm(0)
    pf.right_indent = Cm(0)

    pPr = p._p.get_or_add_pPr()

    # Sombreamento cinza do paragrafo inteiro
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), COR_SOMBRA_DENOMINACAO)
    pPr.append(shd)

    # As quatro bordas externas
    pBdr = OxmlElement('w:pBdr')
    for lado in ('top', 'left', 'bottom', 'right'):
        b = OxmlElement(f'w:{lado}')
        b.set(qn('w:val'), 'single')
        b.set(qn('w:sz'), '8')        # 8 oitavos de ponto = 1pt
        b.set(qn('w:space'), '4')     # respiro entre borda e texto
        b.set(qn('w:color'), COR_BORDA_DENOMINACAO)
        pBdr.append(b)
    pPr.append(pBdr)

    # Texto em negrito (aceita **...** interno sem quebrar)
    _adicionar_runs_com_negrito(
        p, texto, FONTE_PECA, TAM_PECA, COR_PECA, bold_base=True
    )
    return p


def _adicionar_paragrafo(doc, item):
    """Adiciona parágrafo ao documento conforme o tipo."""
    tipo = item['tipo']
    texto = item['texto']

    if not texto.strip():
        return

    if tipo == 'denominacao':
        _render_denominacao(doc, texto)
        return

    if tipo in ('assinatura_nome', 'assinatura_cargo'):
        # Centralizado, sem recuo de primeira linha, nome em negrito e o cargo
        # imediatamente abaixo (por isso o nome fecha com space_after=0).
        nome = tipo == 'assinatura_nome'
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pf = p.paragraph_format
        pf.space_before = Pt(36) if nome else Pt(0)
        pf.space_after = Pt(0)
        pf.first_line_indent = Pt(0)
        pf.left_indent = Cm(0)
        pf.right_indent = Cm(0)
        run = p.add_run(texto)
        run.bold = nome
        run.font.name = FONTE_PECA
        run.font.size = TAM_PECA
        run.font.color.rgb = COR_PECA
        return

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
        run.font.name = FONTE_PECA
        run.font.size = TAM_PECA
        run.font.color.rgb = COR_PECA

    elif tipo == 'heading3':
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.first_line_indent = Pt(0)
        run = p.add_run(texto)
        run.bold = True
        run.font.name = FONTE_PECA
        run.font.size = TAM_PECA
        run.font.color.rgb = COR_PECA

    elif tipo == 'citacao_longa':
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.left_indent = Cm(4)
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(6)
        _adicionar_runs_com_negrito(p, texto, FONTE_PECA, TAM_PECA, COR_PECA)

    else:  # normal
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15
        p.paragraph_format.first_line_indent = Cm(2.5)
        _adicionar_runs_com_negrito(p, texto, FONTE_PECA, TAM_PECA, COR_PECA)


def _remover_assinatura_existente(texto):
    """Remove um bloco de assinatura ja presente no FIM do texto.

    Evita assinatura duplicada: o texto vindo do Claude costuma terminar com
    'Cidade/UF, <data>.' + nome + 'Defensor(a) Publico(a) Federal', e o
    formatador adiciona a assinatura institucional logo depois. Aqui detectamos
    e removemos o bloco pre-existente, deixando apenas a assinatura oficial.

    So atua quando o texto TERMINA com a linha do cargo, e sobe no maximo
    algumas linhas (ate a linha de local/data) — para nunca apagar conteudo do
    corpo da peca (ex.: datas citadas no meio do texto).
    """
    import re as _re

    linhas = texto.rstrip().split("\n")
    if not linhas:
        return texto

    cargo_re = _re.compile(
        r"^\s*\**\s*Defensora?\s+P[úu]blic[oa]\s+Federal\s*\**\s*\.?\s*$",
        _re.IGNORECASE,
    )
    data_re = _re.compile(
        r",.*(?:\d{1,2}\s+de\s+\S+\s+de\s+\d{4}|\[data por extenso\])",
        _re.IGNORECASE,
    )

    # A ultima linha nao-vazia precisa ser o cargo
    idx_cargo = len(linhas) - 1
    while idx_cargo >= 0 and linhas[idx_cargo].strip() == "":
        idx_cargo -= 1
    if idx_cargo < 0 or not cargo_re.match(linhas[idx_cargo]):
        return texto  # nao termina em assinatura — nada a remover

    # Sobe ate a linha de local/data (no maximo ~6 linhas acima do cargo)
    inicio = idx_cargo
    limite = max(-1, idx_cargo - 6)
    j = idx_cargo - 1
    achou_data = False
    while j > limite:
        if data_re.search(linhas[j]):
            inicio = j
            achou_data = True
            break
        j -= 1

    if not achou_data:
        # Sem linha de data por perto: remove apenas o nome (ultima linha
        # nao-vazia antes do cargo) + o cargo.
        k = idx_cargo - 1
        while k >= 0 and linhas[k].strip() == "":
            k -= 1
        inicio = k if k >= 0 else idx_cargo

    return "\n".join(linhas[:inicio]).rstrip()


def _adicionar_assinatura(doc):
    """Adiciona assinatura padrão ao documento."""
    from datetime import datetime

    # Local e data
    p_local = doc.add_paragraph()
    p_local.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_local.paragraph_format.space_before = Pt(36)
    p_local.paragraph_format.space_after = Pt(12)
    p_local.paragraph_format.first_line_indent = Pt(0)
    data_hoje = datetime.now().strftime("%d de %B de %Y")
    # Traduzir mês para português
    meses = {
        'January': 'janeiro', 'February': 'fevereiro', 'March': 'março',
        'April': 'abril', 'May': 'maio', 'June': 'junho',
        'July': 'julho', 'August': 'agosto', 'September': 'setembro',
        'October': 'outubro', 'November': 'novembro', 'December': 'dezembro'
    }
    for en, pt in meses.items():
        data_hoje = data_hoje.replace(en, pt)
    run = p_local.add_run(f"Campina Grande/PB, {data_hoje}.")
    run.font.name = FONTE_PECA
    run.font.size = TAM_PECA
    run.font.color.rgb = COR_PECA

    # Nome
    p_assin = doc.add_paragraph()
    p_assin.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_assin.paragraph_format.space_before = Pt(48)
    p_assin.paragraph_format.space_after = Pt(0)
    p_assin.paragraph_format.first_line_indent = Pt(0)
    run = p_assin.add_run("LUCAS RAFAEL GALDINO DE ARAÚJO LUCENA")
    run.bold = True
    run.font.name = FONTE_PECA
    run.font.size = TAM_PECA
    run.font.color.rgb = COR_PECA

    # Cargo
    p_cargo = doc.add_paragraph()
    p_cargo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_cargo.paragraph_format.space_before = Pt(0)
    p_cargo.paragraph_format.space_after = Pt(0)
    p_cargo.paragraph_format.first_line_indent = Pt(0)
    run = p_cargo.add_run("Defensor Público Federal")
    run.font.name = FONTE_PECA
    run.font.size = TAM_PECA
    run.font.color.rgb = COR_PECA


def _adicionar_secao_citacoes(doc, notas):
    """Adiciona seção CITAÇÕES após a assinatura, em nova página."""
    from docx.enum.text import WD_BREAK

    # Quebra de página
    p_break = doc.add_paragraph()
    p_break.paragraph_format.space_before = Pt(0)
    p_break.paragraph_format.space_after = Pt(0)
    run_break = p_break.add_run()
    run_break.add_break(WD_BREAK.PAGE)

    # Título "CITAÇÕES"
    p_titulo = doc.add_paragraph()
    p_titulo.paragraph_format.space_before = Pt(18)
    p_titulo.paragraph_format.space_after = Pt(12)
    p_titulo.paragraph_format.line_spacing = 1.0
    p_titulo.paragraph_format.first_line_indent = Pt(0)
    # Borda inferior dourada (mesmo estilo dos headings)
    pPr = p_titulo._p.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        '  <w:bottom w:val="single" w:sz="4" w:space="1" w:color="BF8F00"/>'
        '</w:pBdr>'
    )
    pPr.append(pBdr)
    run_titulo = p_titulo.add_run("CITAÇÕES")
    run_titulo.bold = True
    run_titulo.font.name = FONTE_PECA
    run_titulo.font.size = TAM_PECA
    run_titulo.font.color.rgb = COR_PECA

    # Cada nota como parágrafo
    for nota in notas:
        num = _numero_sobrescrito(nota['nota_id'])
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.first_line_indent = Pt(0)

        # Número sobrescrito
        run_num = p.add_run(f"{num} ")
        run_num.font.name = FONTE_PECA
        run_num.font.size = TAM_PECA
        run_num.font.color.rgb = COR_PECA

        # Texto da nota
        run_texto = p.add_run(nota['texto_nota'])
        run_texto.font.name = FONTE_PECA
        run_texto.font.size = TAM_PECA
        run_texto.font.color.rgb = COR_PECA


def converter_para_pdf(caminho_docx):
    """
    Converte o .docx para PDF.
    Windows: usa docx2pdf (requer MS Word)
    Linux/Mac: usa LibreOffice
    """
    sistema = platform.system()
    caminho_pdf = caminho_docx.replace('.docx', '.pdf')

    if sistema == 'Windows':
        try:
            from docx2pdf import convert
            print("Convertendo para PDF (Windows)...")
            convert(caminho_docx, caminho_pdf)
            return caminho_pdf
        except ImportError:
            print("[AVISO] docx2pdf não instalado. Execute: pip install docx2pdf")
            print("[AVISO] Pulando conversão para PDF.")
            return None
    else:
        # Linux ou Mac - usar LibreOffice
        import subprocess
        print("Convertendo para PDF (LibreOffice)...")
        pasta_saida = os.path.dirname(caminho_docx)
        cmd = [
            'libreoffice',
            '--headless',
            '--convert-to', 'pdf',
            '--outdir', pasta_saida,
            caminho_docx
        ]
        try:
            subprocess.run(cmd, check=True)
            return caminho_pdf
        except Exception as e:
            print(f"[AVISO] Erro ao converter para PDF: {e}")
            print("[AVISO] Certifique-se de que o LibreOffice está instalado.")
            return None


def salvar_documento(doc, nome_arquivo, pasta_saida=None):
    """
    Salva o documento em .docx e converte para PDF.

    Args:
        doc: Document do python-docx
        nome_arquivo: str - Nome do arquivo (ex: "agravo_interno_123456.docx")
        pasta_saida: str (opcional) - Caminho da pasta de saída

    Returns:
        tuple: (caminho_docx, caminho_pdf)
    """
    if pasta_saida is None:
        pasta_saida = SAIDA_DIR

    os.makedirs(pasta_saida, exist_ok=True)

    # Salvar .docx
    caminho_docx = os.path.join(pasta_saida, nome_arquivo)
    doc.save(caminho_docx)
    print(f"[OK] Documento DOCX salvo em: {caminho_docx}")

    # Converter para PDF
    caminho_pdf = converter_para_pdf(caminho_docx)
    if caminho_pdf:
        print(f"[OK] Documento PDF salvo em: {caminho_pdf}")

    return caminho_docx, caminho_pdf


# Mapeamento de tipo de peça para endereçamento e título
TIPOS_PECA = {
    'agravo': {
        'enderecamento_tnu': 'EXCELENTÍSSIMA TURMA NACIONAL DE UNIFORMIZAÇÃO DOS JUIZADOS ESPECIAIS FEDERAIS',
        'enderecamento_stj': 'EXCELENTÍSSIMO SENHOR MINISTRO RELATOR DO SUPERIOR TRIBUNAL DE JUSTIÇA',
        'titulo': 'AGRAVO INTERNO',
    },
    'embargos': {
        'enderecamento_tnu': 'EXCELENTÍSSIMA TURMA NACIONAL DE UNIFORMIZAÇÃO DOS JUIZADOS ESPECIAIS FEDERAIS',
        'enderecamento_stj': 'EXCELENTÍSSIMO SENHOR MINISTRO RELATOR DO SUPERIOR TRIBUNAL DE JUSTIÇA',
        'titulo': 'EMBARGOS DE DECLARAÇÃO',
    },
    'memoriais': {
        'enderecamento_tnu': 'EXCELENTÍSSIMA TURMA NACIONAL DE UNIFORMIZAÇÃO DOS JUIZADOS ESPECIAIS FEDERAIS',
        'enderecamento_stj': 'EXCELENTÍSSIMO SENHOR MINISTRO RELATOR DO SUPERIOR TRIBUNAL DE JUSTIÇA',
        'titulo': 'MEMORIAIS',
    },
    'despacho': {
        'enderecamento_tnu': '',
        'enderecamento_stj': '',
        'titulo': 'DESPACHO DE ARQUIVAMENTO',
    },
    'peticao': {
        'enderecamento_tnu': 'MERITÍSSIMO JUÍZO FEDERAL',
        'enderecamento_stj': 'MERITÍSSIMO JUÍZO FEDERAL',
        'titulo': '',
    },
    'recurso-inominado': {
        'enderecamento_tnu': 'TURMA RECURSAL FEDERAL DA 5ª REGIÃO — SEÇÃO JUDICIÁRIA DA PARAÍBA',
        'enderecamento_stj': 'TURMA RECURSAL FEDERAL DA 5ª REGIÃO — SEÇÃO JUDICIÁRIA DA PARAÍBA',
        'titulo': 'RECURSO INOMINADO',
    },
    'embargos-declaracao': {
        'enderecamento_tnu': 'TURMA RECURSAL FEDERAL DA 5ª REGIÃO — SEÇÃO JUDICIÁRIA DA PARAÍBA',
        'enderecamento_stj': 'TURMA RECURSAL FEDERAL DA 5ª REGIÃO — SEÇÃO JUDICIÁRIA DA PARAÍBA',
        'titulo': 'EMBARGOS DE DECLARAÇÃO',
    },
}


def _extrair_sumario(texto):
    """Extrai itens de sumário a partir dos headings ## do texto."""
    import re
    itens = []
    for match in re.finditer(r'^## (.+)$', texto, re.MULTILINE):
        itens.append(match.group(1).strip())
    return itens


def _extrair_texto_pedido(texto):
    """
    Extrai automaticamente o texto do pedido a partir do conteúdo da peça.
    Tenta: (1) parágrafo após SÍNTESE ARGUMENTATIVA, (2) último parágrafo antes de CONCLUSÃO,
    (3) primeiro parágrafo do texto. Retorna string de até 400 caracteres.
    """
    import re

    # Tentar extrair da seção SÍNTESE ARGUMENTATIVA
    m = re.search(r'SÍNTESE ARGUMENTATIVA\s*\n+(.+?)(?:\n\n|\Z)', texto, re.DOTALL)
    if m:
        trecho = m.group(1).strip()
        # Pegar apenas o primeiro parágrafo
        primeiro = trecho.split('\n\n')[0].strip()
        if len(primeiro) > 40:
            return primeiro[:400]

    # Tentar extrair do bloco CONCLUSÃO E PEDIDOS
    m = re.search(r'##[^#].*?(?:CONCLUS|PEDIDO)[^\n]*\n+(.+?)(?:\n\n|\Z)', texto, re.DOTALL | re.IGNORECASE)
    if m:
        trecho = m.group(1).strip()
        primeiro = trecho.split('\n\n')[0].strip()
        if len(primeiro) > 40:
            return primeiro[:400]

    # Fallback: primeiro parágrafo de texto normal (não título)
    for linha in texto.split('\n'):
        linha = linha.strip()
        if linha and not linha.startswith('#') and not linha.startswith('>') and len(linha) > 60:
            return linha[:400]

    return 'Recurso interposto pela Defensoria Pública da União.'


def _inferir_tribunal(processo):
    """Infere TNU ou STJ a partir do número do processo (heurística simples)."""
    if not processo:
        return 'tnu'
    # Processos STJ costumam ter segmento .3.00. ou padrão diferente
    # Por padrão, assume TNU (JEFs)
    return 'tnu'


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Formata peça jurídica da DPU em DOCX/PDF.',
        epilog='Exemplo: python formatar_peca.py --entrada saida/agravo_VALIDADO.txt --tipo-peca agravo --numero-processo 5011388-22.2022.4.04.7200 --paj "PAJ 2026/002-10369/DPU-TNU"'
    )
    parser.add_argument('--entrada', type=str, help='Caminho do arquivo .txt validado')
    parser.add_argument('--tipo-peca', type=str, choices=list(TIPOS_PECA.keys()),
                        help='Tipo da peça: agravo, embargos, embargos-declaracao, memoriais, despacho, peticao, recurso-inominado')
    parser.add_argument('--numero-processo', type=str, default=None,
                        help='Número do processo (ex: 5011388-22.2022.4.04.7200)')
    parser.add_argument('--paj', type=str, default=None,
                        help='Número do PAJ (ex: PAJ 2026/002-10369/DPU-TNU)')
    parser.add_argument('--tribunal', type=str, choices=['tnu', 'stj'], default=None,
                        help='Tribunal (tnu ou stj). Se omitido, infere do processo.')
    parser.add_argument('--banco', type=str, default=None,
                        help='Caminho do Banco de Fontes Verificadas (JSON) para gerar notas de rodapé')
    parser.add_argument('--texto-pedido', type=str, default=None,
                        help='Resumo do pedido para barra lateral (opcional)')
    parser.add_argument('--titulo', type=str, default=None,
                        help='Título da peça (substitui o título padrão do tipo). Ex: "PETIÇÃO"')
    parser.add_argument('--enderecamento', type=str, default=None,
                        help='Endereçamento completo (substitui o padrão do tipo). Suporta \\n para quebras de linha.')
    parser.add_argument('--saida', type=str, default=None,
                        help='Nome do arquivo de saída (sem extensão). Se omitido, deriva do arquivo de entrada.')
    parser.add_argument('--demo', action='store_true',
                        help='Executa formatação de demonstração com texto de exemplo')

    args = parser.parse_args()

    # Modo demo (mantém comportamento original para testes)
    if args.demo:
        conteudo = """
## I – Introdução

Este é um parágrafo normal com recuo de primeira linha. O texto segue formatado conforme o modelo institucional da DPU.

### Subtópico importante

Outro parágrafo normal. Quando citamos jurisprudência, podemos usar citações longas:

> Este é um trecho de citação longa que será formatado com recuo de 4cm à esquerda e fonte menor. Ideal para acórdãos e trechos extensos de doutrina.

## II – Conclusão

Texto final da peça antes da assinatura.
        """
        doc = criar_documento(
            conteudo_txt=conteudo,
            enderecamento="EXCELENTÍSSIMO SENHOR MINISTRO RELATOR DO SUPERIOR TRIBUNAL DE JUSTIÇA",
            titulo_peca="AGRAVO INTERNO",
            subtitulo="REsp nº 1.234.567/SP",
            numero_paj="PAJ 2024/040-12345/BVBA",
            texto_pedido="Reforma da decisão monocrática que negou seguimento ao recurso especial",
            itens_sumario=["I – Introdução", "II – Conclusão"]
        )
        salvar_documento(doc, "teste_formatacao.docx")
        print("\n[OK] Teste de demonstração concluído!")
        sys.exit(0)

    # Modo CLI normal — requer --entrada e --tipo-peca
    if not args.entrada or not args.tipo_peca:
        parser.error('Os argumentos --entrada e --tipo-peca são obrigatórios (ou use --demo para teste).')

    # Ler arquivo de entrada
    if not os.path.exists(args.entrada):
        print(f"[ERRO] Arquivo não encontrado: {args.entrada}")
        sys.exit(1)

    with open(args.entrada, 'r', encoding='utf-8') as f:
        conteudo = f.read()

    if not conteudo.strip():
        print(f"[ERRO] Arquivo vazio: {args.entrada}")
        sys.exit(1)

    # Configurar tipo de peça
    tipo = TIPOS_PECA[args.tipo_peca]
    tribunal = args.tribunal or _inferir_tribunal(args.numero_processo)
    enderecamento_key = f'enderecamento_{tribunal}'

    # O padrao do tipo de peca vai como FALLBACK, nao como valor. Quem manda,
    # na ordem: --enderecamento, depois o endereçamento que o proprio texto
    # traz, e so' entao o padrao. Passar o padrao em `enderecamento` fazia
    # `criar_documento` pular a deteccao e empurrar o endereçamento do texto
    # para o corpo (PAJ 2026/056-00731).
    enderecamento_padrao = tipo.get(enderecamento_key, '')
    titulo_padrao = tipo['titulo']

    enderecamento = ''
    titulo = args.titulo or ''
    if args.enderecamento:
        enderecamento = args.enderecamento.replace('\\n', '\n')
    elif args.tipo_peca == 'despacho' and args.numero_processo:
        enderecamento = f'Processo n. {args.numero_processo}'

    # Subtítulo
    subtitulo = args.paj if args.paj else None

    # Sumário automático
    itens_sumario = _extrair_sumario(conteudo)

    # Texto do pedido para barra lateral
    texto_pedido = args.texto_pedido

    # Nome do arquivo de saída
    if args.saida:
        nome_saida = args.saida if args.saida.endswith('.docx') else f"{args.saida}.docx"
    else:
        base = os.path.splitext(os.path.basename(args.entrada))[0]
        # Remover sufixo _VALIDADO se presente
        base = base.replace('_VALIDADO', '')
        nome_saida = f"{base}.docx"

    print(f"[INFO] Entrada: {args.entrada}")
    print(f"[INFO] Tipo: {args.tipo_peca} | Tribunal: {tribunal}")
    print(f"[INFO] Saída: {nome_saida}")

    # Criar documento
    doc = criar_documento(
        conteudo_txt=conteudo,
        enderecamento=enderecamento,
        titulo_peca=titulo,
        subtitulo=subtitulo,
        numero_paj=args.paj,
        numero_processo=args.numero_processo,
        texto_pedido=texto_pedido,
        itens_sumario=itens_sumario if itens_sumario else None,
        banco_path=args.banco,
        enderecamento_padrao=enderecamento_padrao,
        titulo_padrao=titulo_padrao,
    )

    # Salvar
    salvar_documento(doc, nome_saida)
    print("\n[OK] Formatação concluída!")
