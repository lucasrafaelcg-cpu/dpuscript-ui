"""Extracao de texto de PDFs via fitz (PyMuPDF) + Tesseract fallback.

Funcoes publicas:
  - `extrair_texto(pdf_path, ...)` — PDFs (texto nativo, com OCR de fallback).
  - `extrair_texto_docx(path)` — DOCX (paragrafos + tabelas), via python-docx.
  - `extrair_texto_arquivo(path, ...)` — despachante por extensao.

DOCX importa porque as MINUTAS da assessoria chegam nesse formato: sem
extrair o texto delas, a analise do PAJ nao tem como ler nem revisar a minuta.

Se o PDF tem texto nativo (>200 chars totais), usa fitz direto. Caso contrario,
renderiza cada pagina como imagem e roda Tesseract (lang="por"). Se o Tesseract
nao estiver instalado, devolve placeholder indicando OCR indisponivel.

Suporta cancelamento cooperativo entre paginas (`deve_cancelar` e' consultado antes
de processar cada pagina) e timeout por pagina no Tesseract (evita travar em PDFs
gigantes/corrompidos).
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from collections.abc import Callable

_log = logging.getLogger(__name__)

_MIN_NATIVE_CHARS = 200


def _ocr_pagina(pagina, timeout_seg: int) -> tuple[str, bool]:
    """Renderiza pagina e roda Tesseract com timeout.

    Retorna (texto, tesseract_presente). `texto` pode ser "" se der timeout ou
    erro. `tesseract_presente` vira False so quando Tesseract nao esta instalado
    (pra sinalizar pro chamador que nao vale tentar as proximas paginas).
    """
    try:
        import io

        import pytesseract
        from PIL import Image
    except ImportError:
        return ("", False)

    try:
        pix = pagina.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        # pytesseract aceita timeout (em segundos) — aborta o subprocess se
        # estourar, levantando RuntimeError("Tesseract process timeout").
        txt = pytesseract.image_to_string(img, lang="por", timeout=timeout_seg)
        return (txt, True)
    except pytesseract.TesseractNotFoundError:  # type: ignore[attr-defined]
        return ("", False)
    except RuntimeError as e:
        # Timeout do Tesseract — pagina pulada, mas OCR continua disponivel.
        if "timeout" in str(e).lower():
            return ("[pagina ilegivel — timeout OCR]", True)
        return ("", True)
    except Exception:
        return ("", True)


def extrair_texto(
    pdf_path: Path,
    *,
    deve_cancelar: Callable[[], bool] | None = None,
    timeout_por_pagina_seg: int = 30,
) -> str:
    """Extrai texto do PDF. Usa OCR so se texto nativo for insuficiente.

    Retorna texto concatenado com marcadores `=== pagina N ===`. Se nenhuma
    pagina produzir texto, devolve string com `[OCR indisponivel]`.

    `deve_cancelar`: callable que, se retornar True, aborta o loop e devolve
    o parcial + marcador `[OCR abortado pelo usuario na pagina X/N]`.
    `timeout_por_pagina_seg`: limite por pagina no Tesseract (default 30s).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "[PyMuPDF nao instalado — instale 'pymupdf' para habilitar OCR]\n"

    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        return f"[erro abrindo PDF: {type(e).__name__}: {e}]\n"

    paginas_texto: list[str] = []
    total_paginas = 0
    abortado_em = 0
    try:
        nativos: list[str] = []
        for pagina in doc:
            t = pagina.get_text() or ""
            nativos.append(t)
        total_nativo = sum(len(t.strip()) for t in nativos)
        total_paginas = len(nativos)

        usar_ocr = total_nativo < _MIN_NATIVE_CHARS
        ocr_disponivel = True
        for i, pagina in enumerate(doc, start=1):
            # Cancelamento cooperativo — checado antes de cada pagina.
            if deve_cancelar is not None and deve_cancelar():
                abortado_em = i
                break

            if usar_ocr:
                texto, tesseract_presente = _ocr_pagina(pagina, timeout_por_pagina_seg)
                if not tesseract_presente and i == 1:
                    ocr_disponivel = False
            else:
                texto = nativos[i - 1]
            paginas_texto.append(f"=== pagina {i} ===\n{texto.strip()}\n")

        if usar_ocr and not ocr_disponivel:
            return (
                "[OCR indisponivel: Tesseract nao instalado ou idioma 'por' ausente. "
                "PDF parece escaneado — texto nativo insuficiente.]\n"
            )
    finally:
        doc.close()

    resultado = "\n".join(paginas_texto)
    if abortado_em > 0:
        resultado += (
            f"\n[OCR abortado pelo usuario na pagina {abortado_em}/{total_paginas}]\n"
        )
    return resultado


def extrair_texto_docx(path: Path) -> str:
    """Extrai texto de um .docx (paragrafos + celulas de tabela), na ordem.

    Usado principalmente para MINUTAS da assessoria. Sem isso o arquivo fica
    sem `.txt` companion e a analise do PAJ nao consegue ler a minuta.
    """
    try:
        from docx import Document
    except ImportError:
        return "[python-docx nao instalado — instale 'python-docx' para ler .docx]\n"

    try:
        doc = Document(str(path))
    except Exception as e:
        return f"[erro abrindo DOCX: {type(e).__name__}: {e}]\n"

    partes: list[str] = []
    for p in doc.paragraphs:
        t = (p.text or "").strip()
        if t:
            partes.append(t)

    for tabela in doc.tables:
        for linha in tabela.rows:
            celulas = [(c.text or "").strip() for c in linha.cells]
            celulas = [c for c in celulas if c]
            if celulas:
                partes.append(" | ".join(celulas))

    if not partes:
        return "[DOCX sem texto extraivel — pode conter apenas imagens]\n"
    return "\n\n".join(partes) + "\n"


def extrair_texto_doc(path: Path) -> str:
    """Extrai texto de um .doc ANTIGO (OLE2, Word 97-2003), via Word.

    `python-docx` nao le esse formato — ele e' um conteiner OLE2, nao um zip
    de XML. Sem isto, a minuta chegava sem texto: no PAJ 2023/056-01080 o
    arquivo `01_05_11_2026_MINUTA.doc` ficou sem `.txt` e o painel acabou
    apresentando OUTRA peca, de agosto, como "a minuta a revisar".

    Usa o Word por COM, que ja' e' dependencia do painel (o docx2pdf converte
    as pecas por ele). Falhando, devolve texto vazio — e quem chama trata a
    ausencia explicitamente, em vez de cair noutro arquivo.
    """
    try:
        import pythoncom  # noqa: F401  (inicializa o COM nesta thread)
        import win32com.client
    except Exception:
        _log.warning("pywin32 ausente — nao da' para ler .doc")
        return ""

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        # ReadOnly e AddToRecentFiles=False para nao mexer no ambiente do
        # Defensor; ConfirmConversions=False evita caixa de dialogo travando
        # o processo sem ninguem para clicar.
        doc = word.Documents.Open(
            str(path.resolve()),
            ConfirmConversions=False, ReadOnly=True,
            AddToRecentFiles=False, Visible=False,
        )
        texto = doc.Content.Text or ""
        # O Word usa CR puro como fim de paragrafo.
        return texto.replace("\r\n", "\n").replace("\r", "\n").strip()
    except Exception as e:
        _log.warning("falha ao ler %s pelo Word: %s", path.name, e)
        return ""
    finally:
        with contextlib.suppress(Exception):
            if doc is not None:
                doc.Close(SaveChanges=False)
        with contextlib.suppress(Exception):
            if word is not None:
                word.Quit()
        with contextlib.suppress(Exception):
            pythoncom.CoUninitialize()


def extrair_texto_arquivo(
    path: Path,
    *,
    deve_cancelar: Callable[[], bool] | None = None,
    timeout_por_pagina_seg: int = 30,
) -> str | None:
    """Despacha a extracao conforme a extensao. None se o tipo nao e' suportado."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return extrair_texto(
            path,
            deve_cancelar=deve_cancelar,
            timeout_por_pagina_seg=timeout_por_pagina_seg,
        )
    if ext == ".docx":
        return extrair_texto_docx(path)
    if ext == ".doc":
        return extrair_texto_doc(path)
    return None
