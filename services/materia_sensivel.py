"""Trava de matéria sensível: o painel NÃO analisa material de abuso sexual
infantil.

Razão. O Defensor recebeu aviso institucional de que colaboradores usaram IA
para analisar processo de pornografia infantil, a ferramenta reportou às
autoridades e houve busca e apreensão na casa da pessoa. Independentemente do
mérito disso, o fato é que esse material não pode ser enviado a serviço
externo a partir daqui — e a defesa desses casos é trabalho legítimo da
Defensoria, que simplesmente tem de ser feito fora do painel.

Desenho. A verificação roda ANTES de montar o prompt e antes de qualquer
chamada ao Claude CLI: é uma varredura de texto que já está em disco, sobre
poucos quilobytes, e custa milissegundos. A análise, que leva de um a três
minutos, nem começa. Não há caminho de contorno na interface: PAJ marcado é
PAJ que se trabalha à mão.

Precisão. Os marcadores sao ANCORAS LEGAIS (artigos do ECA e do Código Penal)
e termos tecnicos do tipo penal. Palavra solta como "crianca", "adolescente"
ou "ECA" NAO entra: metade dos PAJs previdenciarios fala de menor de idade,
e bloquear por isso tornaria a trava inutil.
"""

from __future__ import annotations

import json
import re
import unicodedata

# Âncoras legais. São o sinal mais confiável: quem cita 241-A do ECA está
# tratando do tipo penal, não de guarda ou de benefício assistencial.
_ARTIGOS = (
    r"art(?:igo)?s?\.?\s*24[01]\s*[-–]?\s*[ABCDE]?\b[^.\n]{0,40}"
    r"(?:eca|8\.?069|estatuto da crian[çc]a)",
    r"(?:eca|8\.?069|estatuto da crian[çc]a)[^.\n]{0,40}"
    r"art(?:igo)?s?\.?\s*24[01]\s*[-–]?\s*[ABCDE]?\b",
    r"\b24[01]\s*-\s*[ABCD]\b",                      # "241-A", "241-B"
    r"art(?:igo)?s?\.?\s*217\s*-\s*A\b",             # estupro de vulnerável
    r"art(?:igo)?s?\.?\s*218\s*-?\s*[ABC]?\b[^.\n]{0,30}"
    r"(?:lasc[íi]via|sat[ií]sfa|v[ui]lner)",
)

# Termos do tipo penal. Exigem a combinação criança/adolescente + conteúdo
# sexual explícito, ou são expressões unívocas.
_TERMOS = (
    r"pornografia\s+infanto?[\s-]*(?:juvenil)?",
    r"pornogr[áa]fic[ao]s?[^.\n]{0,60}(?:crian[çc]a|adolescente|menor)",
    r"(?:crian[çc]a|adolescente|menor)[^.\n]{0,60}pornogr[áa]fic[ao]s?",
    r"cena\s+de\s+sexo\s+expl[íi]cito",
    r"abuso\s+sexual\s+(?:infantil|de\s+crian[çc]a|de\s+menor)",
    r"explora[çc][ãa]o\s+sexual\s+(?:infantil|de\s+crian[çc]a|de\s+adolescente|de\s+menor)",
    r"estupro\s+de\s+vulner[áa]vel",
    r"\bcsam\b",
    r"material\s+de\s+abuso\s+sexual",
    r"armazenar?[^.\n]{0,40}(?:fotografia|v[íi]deo|imagem)[^.\n]{0,40}"
    r"(?:sexo\s+expl[íi]cito|pornogr[áa]f)",
)

_RX = [re.compile(p, re.IGNORECASE) for p in _ARTIGOS + _TERMOS]

# Onde procurar. São os campos que o painel já tem em disco; não se abre
# anexo nem PDF, porque a trava precisa ser barata.
_CAMPOS_META = (
    "narrativa", "pretensao", "assunto", "classe", "area",
    "assistido_caixa", "observacoes", "qualificacao",
)


def _normalizar(t: str) -> str:
    """Sem acento e em minúscula, para o padrão casar com qualquer grafia."""
    t = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in t if not unicodedata.combining(c)).lower()


def _trechos(paj_norm: str, metadata: dict | None) -> list[tuple[str, str]]:
    from config import PAJS_DIR

    pasta = PAJS_DIR / paj_norm
    if metadata is None:
        try:
            metadata = json.loads(
                (pasta / "metadata.json").read_text(encoding="utf-8"))
        except Exception:
            metadata = {}

    partes: list[tuple[str, str]] = []
    det = metadata.get("detalhes_sisdpu") or {}
    for origem in (metadata, det):
        for campo in _CAMPOS_META:
            v = origem.get(campo)
            if isinstance(v, str) and v.strip():
                partes.append((f"metadata.{campo}", v))

    for mv in (det.get("movimentacoes") or []):
        d = mv.get("descricao")
        if isinstance(d, str) and d.strip():
            partes.append((f"movimentacao seq {mv.get('seq', '?')}", d))

    # sisdpu.txt: o texto da tela do PAJ, que traz narrativa e pretensão
    # mesmo quando a metadata veio incompleta.
    f = pasta / "sisdpu.txt"
    if f.is_file():
        try:
            partes.append(("sisdpu.txt", f.read_text(encoding="utf-8",
                                                     errors="replace")))
        except OSError:
            pass
    return partes


def verificar(paj_norm: str, metadata: dict | None = None) -> dict:
    """O PAJ aparenta tratar de abuso sexual infantil?

    Devolve {bloqueado, achados}, em que cada achado é {onde, termo, trecho}.
    Nunca levanta: uma falha aqui não pode liberar o que deveria barrar, então
    o erro inesperado também bloqueia.
    """
    try:
        achados = []
        for onde, texto in _trechos(paj_norm, metadata):
            alvo = _normalizar(texto)
            for rx in _RX:
                m = rx.search(alvo)
                if not m:
                    continue
                ini = max(0, m.start() - 50)
                achados.append({
                    "onde": onde,
                    "termo": m.group(0)[:80],
                    "trecho": alvo[ini:m.end() + 50].strip(),
                })
                break          # um achado por trecho basta
        return {"bloqueado": bool(achados), "achados": achados[:6]}
    except Exception as e:
        return {"bloqueado": True, "achados": [
            {"onde": "verificacao", "termo": f"falha ao verificar: {e}",
             "trecho": ""}]}


MOTIVO = (
    "PAJ bloqueado para análise automática: há indício de matéria de abuso "
    "sexual infantil. Por decisão institucional, esse material não é enviado "
    "a ferramenta de IA. Trabalhe este caso manualmente, fora do painel."
)


def erro_bloqueio(resultado: dict) -> str:
    """Mensagem de bloqueio com o que casou, para o Defensor poder conferir."""
    linhas = [MOTIVO]
    for a in resultado.get("achados") or []:
        linhas.append(f"  • {a['onde']}: {a['termo']}")
    return "\n".join(linhas)
