"""Teor da movimentação legível na tela.

O SISDPU guarda o teor da movimentação numa célula com `<br>`/`<p>`. A
extração antiga usava `textContent`, que descarta esses limites e cola os
parágrafos: `...foi a DPU nomeada curadora especial.A última movimentação de
conteúdo (mov. 5) registra...`. A extração passou a usar `innerText`, então o
que vier de agora em diante já chega quebrado — mas as 11.240 movimentações
que estão na base chegaram coladas, e é nelas que o Defensor trabalha hoje.

Este módulo remonta a quebra no momento de exibir. Só usa um sinal que não
existe em texto bem formado: **ponto final seguido direto de maiúscula, sem
espaço**. Texto com pontuação correta sempre tem o espaço, então a regra não
pode quebrar o que já estava certo.
"""

from __future__ import annotations

import re

# Ponto colado na maiuscula seguinte, sem espaco. Exige MINUSCULA, digito ou
# fechamento antes do ponto, o que deixa intacta sigla pontuada ("S.A.Ltda"):
# ali o caractere anterior ao ponto e' maiuscula. E aceita tanto "especial.A
# ultima" (maiuscula sozinha) quanto "2022.Assim" (palavra capitalizada).
_RE_COLADO = re.compile(
    r"(?<=[a-zà-ÿ0-9\)\]\"»])"
    r"([.!?])"
    r"([A-ZÀ-Ý](?:[a-zà-ÿ]{2,}|(?=\s)))"
)

# Rótulo em caixa alta colado no texto: "RELATÓRIO DO NRTrata-se de ação".
# Exige 2+ palavras em caixa alta antes, para não pegar nome próprio.
_RE_TITULO_COLADO = re.compile(
    r"\b([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{2,}(?:\s+(?:D[AEO]S?\s+)?[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{2,})+)"
    r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][a-záàâãéêíóôõúç]{2,})"
)

# Prefixo que o painel acrescenta ao teor: "MOVIMENTAÇÃO MANUAL: ".
_RE_PREFIXO = re.compile(r"^([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ ]{4,40}):\s*")


def paragrafos(texto: str) -> list[str]:
    """Devolve o teor em parágrafos, remontando o que veio colado."""
    if not texto:
        return []

    t = str(texto).replace("\r\n", "\n").strip()
    t = _RE_PREFIXO.sub("", t)
    t = _RE_TITULO_COLADO.sub(r"\1\n\n\2", t)
    t = _RE_COLADO.sub(r"\1\n\n\2", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)

    return [p.strip() for p in t.split("\n\n") if p.strip()]


def rotulo(texto: str) -> str:
    """O prefixo do teor ("MOVIMENTAÇÃO MANUAL"), para virar etiqueta."""
    m = _RE_PREFIXO.match(str(texto or "").strip())
    return m.group(1).strip().title() if m else ""
