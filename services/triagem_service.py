"""Classificação heurística do evento que encaminhou o PAJ ao defensor.

Implementa a Fase 1 do fluxo de trabalho (docs/FLUXO_DE_TRABALHO.md): regras
determinísticas (sem IA, auditáveis) que identificam, nas movimentações do
SISDPU, qual evento trouxe o PAJ à caixa — um dos 5 fluxos de entrada:

    1. abertura_paj      — abertura ou redistribuição à unidade de Osasco
    2. retorno_assistido — atendimento de retorno (docs/requerimento do assistido)
    3. intimacao         — intimação/citação/notificação judicial
    4. resposta_oficio   — resposta de órgão externo a ofício expedido
    5. controle_prazo    — envio automático pelo sistema ao encerrar prazo de controle

A heurística é um PALPITE para orientar a análise (vai como dica no
PROMPT_MAX) — a confirmação é da análise FIRAC e, em última instância, do
Defensor. Por isso os padrões são conservadores: melhor "não classificado"
que classificado errado.

Ruídos conhecidos do SISDPU (motivo de olhar VÁRIAS movimentações, não só a última):
- PAJ encaminhado em duplicidade: a última movimentação é uma "conclusão"
  genérica posterior ao evento real.
- Descrição "Fase incluída automaticamente, verificar fase anterior": o sinal
  está no campo FASE da própria movimentação (ex. real: fase "Atendimento de
  retorno") ou na movimentação anterior.
"""

from __future__ import annotations

import re

TIPO_ABERTURA = "abertura_paj"
TIPO_RETORNO = "retorno_assistido"
TIPO_INTIMACAO = "intimacao"
TIPO_RESPOSTA_OFICIO = "resposta_oficio"
TIPO_CONTROLE_PRAZO = "controle_prazo"

LABELS = {
    TIPO_ABERTURA: "Abertura de PAJ (ou redistribuição a Osasco)",
    TIPO_RETORNO: "Retorno do Assistido",
    TIPO_INTIMACAO: "Intimação judicial",
    TIPO_RESPOSTA_OFICIO: "Resposta de ofício",
    TIPO_CONTROLE_PRAZO: "Controle de prazo",
}

# Ordem importa: do mais específico para o mais genérico. "Atendimento de
# retorno com juntada de documentos" não pode cair em "juntada" genérica, e
# "resposta de ofício" vem antes de "intimação" porque ofícios respondidos
# costumam citar a intimação original.
_PADROES: list[tuple[str, re.Pattern]] = [
    (TIPO_RETORNO, re.compile(r"atendimento\s+de\s+retorno", re.I)),
    (TIPO_RESPOSTA_OFICIO, re.compile(
        r"resposta\s+(de\s+|a[o]?\s+)?of[íi]cio|of[íi]cio\s+resposta|"
        r"resposta\s+do\s+[óo]rg[ãa]o", re.I)),
    (TIPO_CONTROLE_PRAZO, re.compile(
        r"controle\s+de\s+prazo|decurso\s+de\s+prazo|"
        r"prazo\s+(de\s+controle\s+)?(encerrad|vencid|expirad)", re.I)),
    (TIPO_INTIMACAO, re.compile(r"intima[çc]|cita[çc][ãa]o|notifica[çc]", re.I)),
    (TIPO_ABERTURA, re.compile(
        r"abertura\s+d[eo]\s+paj|redistribui[çc]|"
        r"distribui[çc][ãa]o\s+d[eo]\s+paj", re.I)),
]


def classificar_movimentacao(mov: dict) -> str | None:
    """Tipo de evento de UMA movimentação, ou None se não caracteriza evento.

    Considera fase + descrição + movimentação juntas: nos exemplos reais, o
    sinal ora vem na descrição ("Concluso ao defensor" / "Atendimento de
    retorno."), ora na própria fase ("Atendimento de retorno" / "Fase incluída
    automaticamente, verificar fase anterior").
    """
    texto = " ".join(
        str(mov.get(k) or "") for k in ("fases", "descricao", "movimentacao")
    )
    if not texto.strip():
        return None
    for tipo, rgx in _PADROES:
        if rgx.search(texto):
            return tipo
    return None


def detectar_evento_recente(movs: list[dict], max_janela: int = 10) -> dict | None:
    """Evento mais recente que caracteriza encaminhamento ao defensor.

    Percorre as movimentações da mais recente para trás (janela de
    `max_janela`), pulando as que não classificam — é assim que conclusões
    genéricas e encaminhamentos em duplicidade posteriores ao evento real
    deixam de mascarar o motivo verdadeiro.
    """
    movs_ord = sorted(movs or [], key=lambda m: int(m.get("seq", 0) or 0), reverse=True)
    for mov in movs_ord[:max_janela]:
        tipo = classificar_movimentacao(mov)
        if tipo:
            return {
                "tipo": tipo,
                "label": LABELS[tipo],
                "seq": mov.get("seq"),
                "data": mov.get("data_original") or mov.get("data") or "",
                "descricao": (mov.get("descricao") or "").strip()[:300],
            }
    return None
