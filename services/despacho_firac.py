"""Despacho sugerido pela análise FIRAC — extrai da SITUACAO.md e vira arquivo.

A análise FIRAC (`services/situacao_service`) fecha o relatório com a seção 4,
"Sugestão de despacho no PAJ": o texto pronto para o DPU Digital. Até aqui esse
texto só existia dentro do relatório, para copiar à mão. Este módulo o recorta
e grava como `despacho-firac-<data>.txt` na RAIZ do PAJ, onde a aba Despachos
já o lista (paj_service classifica por prefixo "despacho") e o modal de texto
já o edita.

Duas regras governam a gravação:

  1. **Não sobrescreve.** O nome carrega a data/hora da análise que o gerou,
     então reexecutar a mesma análise não duplica nada e uma análise nova cria
     outro arquivo. Despacho que o Defensor editou nunca é tocado.
  2. **Texto puro.** A seção 4 já é pedida sem marcação ao Claude, mas o
     relatório às vezes volta com `**` ou `#` residual. Aqui some: o editor do
     SISDPU não interpreta marcação e os caracteres apareceriam literalmente.
"""

from __future__ import annotations

import datetime
import logging
import re
import unicodedata
from pathlib import Path

_log = logging.getLogger(__name__)

# Cabeçalho da seção 4, nas três formas que a análise produz:
#   "## 4. Sugestão de despacho no PAJ"
#   "4. **Sugestão de despacho no PAJ**"
#   "4. Sugiro o seguinte despacho no PAJ:"
_RE_SECAO_4 = re.compile(
    r"^\s{0,3}(?:#{1,4}\s*)?4[\.\)]?\s*\**\s*"
    r"(?:sugest[aã]o\s+de\s+despacho|sugiro\s+o\s+seguinte\s+despacho)"
    r"[^\n]*\n",
    re.IGNORECASE | re.MULTILINE,
)

# Rodapé que o painel às vezes acrescenta ao relatório.
_RE_RODAPE = re.compile(
    r"\n+_?(?:An[aá]lise FIRAC gerada|Gerado pelo painel|Relat[oó]rio gerado)[^\n]*$",
    re.IGNORECASE,
)


def _limpar_marcacao(texto: str) -> str:
    """Tira a marcação markdown que sobra, preservando a quebra de parágrafo."""
    t = texto.replace("\r\n", "\n")
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.MULTILINE)   # títulos
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", t, flags=re.DOTALL)        # negrito
    t = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"\1", t)   # itálico
    t = re.sub(r"`([^`]*)`", r"\1", t)                             # código
    t = re.sub(r"^\s{0,3}>\s?", "", t, flags=re.MULTILINE)         # citação
    t = re.sub(r"^\s{0,3}[-*+]\s+", "", t, flags=re.MULTILINE)     # marcador
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def extrair_sugestao(situacao_md: str) -> str | None:
    """Devolve o texto da seção 4 em texto puro, ou None se ela não existir."""
    if not situacao_md:
        return None
    m = _RE_SECAO_4.search(situacao_md)
    if not m:
        return None
    corpo = situacao_md[m.end():]
    corpo = _RE_RODAPE.sub("", corpo)
    corpo = _limpar_marcacao(corpo)
    # Seção vazia ou com uma linha solta não é despacho.
    return corpo if len(corpo) >= 60 else None


def _carimbo(pasta: Path, situacao: Path) -> str:
    """Data/hora da análise, para o nome do arquivo.

    Vem do cabeçalho `_Análise FIRAC gerada em dd/mm/aaaa HH:MM_`, que é
    estável; o mtime muda se o arquivo for copiado entre máquinas.
    """
    try:
        cab = situacao.read_text(encoding="utf-8", errors="replace")[:300]
        m = re.search(r"gerada em (\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})", cab)
        if m:
            d, mes, a, h, mi = m.groups()
            return f"{a}{mes}{d}-{h}{mi}"
    except Exception:
        pass
    ts = datetime.datetime.fromtimestamp(situacao.stat().st_mtime)
    return ts.strftime("%Y%m%d-%H%M")


def caminho_do_despacho(paj_norm: str) -> Path | None:
    """Caminho que o despacho desta análise teria, exista ele ou não."""
    from config import PAJS_DIR
    from services.prompt_builder import SITUACAO_FILE

    pasta = PAJS_DIR / paj_norm
    situacao = pasta / SITUACAO_FILE
    if not situacao.exists():
        return None
    return pasta / f"despacho-firac-{_carimbo(pasta, situacao)}.txt"


def criar_do_firac(paj_norm: str) -> dict:
    """Grava o despacho sugerido como .txt na raiz do PAJ.

    Retorna {ok, arquivo, motivo}. Nunca levanta: é chamado como efeito
    colateral da análise e uma falha aqui não pode derrubar a análise.
    """
    from config import PAJS_DIR
    from services.prompt_builder import SITUACAO_FILE

    try:
        pasta = PAJS_DIR / paj_norm
        situacao = pasta / SITUACAO_FILE
        if not situacao.exists():
            return {"ok": False, "motivo": "sem SITUACAO.md"}

        destino = caminho_do_despacho(paj_norm)
        if destino is None:
            return {"ok": False, "motivo": "sem SITUACAO.md"}
        if destino.exists():
            # Regra 1: análise já convertida. O que o Defensor editou fica.
            return {"ok": True, "arquivo": destino.name, "motivo": "ja existia"}

        texto = extrair_sugestao(
            situacao.read_text(encoding="utf-8", errors="replace"))
        if not texto:
            return {"ok": False, "motivo": "analise sem secao de despacho"}

        destino.write_text(texto + "\n", encoding="utf-8")
        _log.info("despacho do FIRAC criado: %s/%s", paj_norm, destino.name)
        return {"ok": True, "arquivo": destino.name, "motivo": "criado"}
    except Exception as e:
        _log.warning("falha ao criar despacho do FIRAC em %s: %s", paj_norm, e)
        return {"ok": False, "motivo": f"{type(e).__name__}: {e}"}


def texto_para_html(texto: str) -> str:
    """Converte o despacho em HTML de parágrafos para o editor do SISDPU.

    O campo da movimentação é um CKEditor: texto cru entra como uma linha só.
    Cada parágrafo vira um `<p>`, e o conteúdo é escapado — um `<` solto no
    despacho não pode virar marcação na tela do PAJ.
    """
    from html import escape

    blocos = [b.strip() for b in re.split(r"\n\s*\n", (texto or "").strip()) if b.strip()]
    if not blocos:
        return ""
    return "".join(
        "<p>" + escape(b).replace("\n", "<br/>") + "</p>" for b in blocos
    )


# Particulas que nao identificam ninguem.
_PARTICULAS = {"de", "da", "do", "das", "dos", "e"}


def _desacentuar(t: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", t or "") if not unicodedata.combining(c)
    ).lower()


def mesmo_assistido(esperado: str, encontrado: str) -> bool:
    """Os dois nomes designam a mesma pessoa?

    Trava contra o erro que nao tem volta: gravar no PAJ de outro assistido.
    O painel guarda o nome na fila; antes de gravar, o SISDPU devolve o nome
    que esta na tela do PAJ aberto. Divergiu, aborta.

    Tolerante ao que varia sem mudar a pessoa (acento, caixa, espaco dobrado,
    nome do meio que um lado traz e o outro nao) e intolerante ao que importa:
    exige o PRIMEIRO e o ULTIMO nome significativo iguais nos dois lados.
    """
    def tokens(t: str) -> list[str]:
        return [x for x in re.findall(r"[a-z]{2,}", _desacentuar(t))
                if x not in _PARTICULAS]

    a, b = tokens(esperado), tokens(encontrado)
    if not a or not b:
        return False
    return a[0] == b[0] and a[-1] == b[-1]
