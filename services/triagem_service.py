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

import datetime as _dt
import json
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
        r"controle\s+de\s+prazo|decurso\s+de\s+prazo|paj\s+em\s+decurso|"
        r"prazo\s+(de\s+controle\s+)?(encerrad|vencid|expirad)", re.I)),
    (TIPO_INTIMACAO, re.compile(r"intima[çc]|cita[çc][ãa]o|notifica[çc]", re.I)),
    (TIPO_ABERTURA, re.compile(
        r"abertura\s+d[eo]\s+paj|redistribui[çc]|"
        r"distribui[çc][ãa]o\s+d[eo]\s+paj", re.I)),
]

# Decurso com situação "PREVISTO" é a INCLUSÃO/alteração do PAJ no controle de
# prazo (programação futura) — não é envio ao defensor. Só o decurso consumado
# (situação "EFETIVADO") caracteriza o evento `controle_prazo`. Exemplo real a
# ignorar: fase "Decurso de prazo", descrição 'PAJ em decurso alterado de
# "29/11/2026" para "29/05/2028" com situação "PREVISTO" a pedido do Defensor.'
_RE_DECURSO_PREVISTO = re.compile(r"situa[çc][ãa]o\s*\"?\s*previsto", re.I)


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
            if tipo == TIPO_CONTROLE_PRAZO and _RE_DECURSO_PREVISTO.search(texto):
                return None  # programação de decurso futuro — não é evento
            return tipo
    return None


# Tipos exibidos na coluna "Última movimentação" da caixa. controle_prazo
# fica FORA de propósito: decurso automático é ruído de sistema, e o Defensor
# pediu para não considerar movimentação-fantasma de controle de prazo.
TIPOS_MOVIMENTACAO_CAIXA = (
    TIPO_RETORNO, TIPO_ABERTURA, TIPO_INTIMACAO, TIPO_RESPOSTA_OFICIO,
)

# Rótulos curtos para a coluna da caixa (os nomes exatos pedidos pelo Defensor).
# LABELS (mais descritivos) seguem para a fila de triagem/PROMPT_MAX.
LABELS_CAIXA = {
    TIPO_RETORNO: "Retorno do assistido",
    TIPO_ABERTURA: "Abertura de PAJ",
    TIPO_INTIMACAO: "Intimação",
    TIPO_RESPOSTA_OFICIO: "Resposta de ofício",
}


def classificar_ultima_movimentacao(movs: list[dict], max_janela: int = 10) -> dict | None:
    """Última movimentação substantiva do PAJ para a coluna da caixa.

    Mesma varredura da triagem (mais recente para trás, janela `max_janela`),
    mas restrita aos 4 fluxos que o Defensor quer ver: retorno do assistido,
    abertura de PAJ, intimação e resposta de ofício. Movimentações de controle
    de prazo automático são PULADAS — quando o decurso está por cima do evento
    real (ex. intimação), mostramos o evento real, não o decurso. Conclusões e
    juntadas genéricas, duplicidade e decurso "PREVISTO" já não classificam em
    `classificar_movimentacao`, então também são ignorados aqui.
    """
    movs_ord = sorted(movs or [], key=lambda m: int(m.get("seq", 0) or 0), reverse=True)
    for mov in movs_ord[:max_janela]:
        tipo = classificar_movimentacao(mov)
        if tipo in TIPOS_MOVIMENTACAO_CAIXA:
            return {
                "tipo": tipo,
                "label": LABELS_CAIXA[tipo],
                "seq": mov.get("seq"),
                "data": mov.get("data_original") or mov.get("data") or "",
            }
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


# --- Persistência do evento (Fase 2 — gancho no sincronizador + fila da UI) ---

def atualizar_evento_triagem(metadata: dict, movs_antigas: list[dict],
                             paj_novo: bool = False) -> bool:
    """Grava/atualiza `evento_triagem` na metadata (mutável). True se mudou.

    Chamada pelo sincronizador a cada sync de PAJ. Só sinaliza evento NOVO:
    - PAJ novo na pasta → sempre entra na fila (fallback: abertura_paj);
    - PAJ existente → só se o evento veio de movimentação que NÃO existia na
      sync anterior (seq maior que o maior seq antigo). Assim, re-sincronizar
      não reabre evento já triado nem re-enfileira evento antigo.
    """
    det = metadata.get("detalhes_sisdpu", {}) or {}
    movs = det.get("movimentacoes", []) or []
    agora = _dt.datetime.now().isoformat(timespec="seconds")

    evento = detectar_evento_recente(movs)

    if paj_novo:
        if not evento:
            evento = {
                "tipo": TIPO_ABERTURA, "label": LABELS[TIPO_ABERTURA],
                "seq": None, "data": "",
                "descricao": "PAJ novo na caixa (sem movimentação classificável)",
            }
        metadata["evento_triagem"] = {**evento, "status": "pendente",
                                      "detectado_em": agora}
        return True

    if not evento:
        return False
    max_seq_antiga = max(
        (int(m.get("seq", 0) or 0) for m in movs_antigas or []), default=0)
    if int(evento.get("seq") or 0) <= max_seq_antiga:
        return False  # evento já existia na sync anterior — não reabrir
    existente = metadata.get("evento_triagem") or {}
    if existente.get("seq") == evento.get("seq") and existente.get("status") == "pendente":
        return False  # mesmo evento já pendente — preserva detectado_em original
    metadata["evento_triagem"] = {**evento, "status": "pendente",
                                  "detectado_em": agora}
    return True


def listar_fila() -> list[dict]:
    """Itens pendentes da Caixa de triagem (varre metadata.json dos PAJs)."""
    from config import PAJS_DIR
    from services.pje_service import eh_trf3_1g

    itens: list[dict] = []
    if not PAJS_DIR.exists():
        return itens
    for pasta in PAJS_DIR.iterdir():
        meta_path = pasta / "metadata.json"
        if not pasta.is_dir() or not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        ev = meta.get("evento_triagem") or {}
        if ev.get("status") != "pendente":
            continue
        # Análise FIRAC pronta = SITUACAO.md mais novo que a detecção do
        # evento (gerado pela fila automática ou pelo botão). Strings ISO
        # do mesmo formato — comparação lexicográfica funciona.
        situacao_pronta = False
        sit = pasta / "SITUACAO.md"
        if sit.exists():
            gerada_em = _dt.datetime.fromtimestamp(
                sit.stat().st_mtime).isoformat(timespec="seconds")
            situacao_pronta = gerada_em >= (ev.get("detectado_em") or "")
        itens.append({
            "paj_norm": pasta.name,
            "paj": meta.get("paj", pasta.name),
            "assistido": meta.get("assistido_caixa", "") or "",
            "tipo": ev.get("tipo", ""),
            "label": ev.get("label", ""),
            "data": ev.get("data", ""),
            "descricao": ev.get("descricao", ""),
            "detectado_em": ev.get("detectado_em", ""),
            "trf3": eh_trf3_1g(meta.get("processo_judicial", "")),
            "situacao_pronta": situacao_pronta,
        })
    itens.sort(key=lambda i: i.get("detectado_em") or "", reverse=True)
    return itens


def concluir_evento(paj_norm: str) -> bool:
    """Marca o evento de triagem do PAJ como concluído (sai da fila)."""
    from config import PAJS_DIR

    meta_path = PAJS_DIR / paj_norm / "metadata.json"
    if not meta_path.exists():
        return False
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    ev = meta.get("evento_triagem") or {}
    if not ev:
        return False
    ev["status"] = "concluido"
    ev["concluido_em"] = _dt.datetime.now().isoformat(timespec="seconds")
    meta["evento_triagem"] = ev
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return True
