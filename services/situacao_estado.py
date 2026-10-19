"""Estado da análise FIRAC: está velha? a última tentativa falhou?

Problema que este módulo resolve. A análise automática é agendada quando o
PAJ entra na caixa, roda em fila de fundo e grava `SITUACAO.md`. Quando ela
FALHA — sessão do Claude CLI expirada, timeout —, o erro ia só para o log:
o painel continuava exibindo a análise antiga, sem nenhum sinal de que a
atualização tinha sido tentada e não deu certo. Em 14 e 18/10/2026 foram 30
falhas de autenticação em 27 PAJs, e a tela não dizia uma palavra.

Dois sinais, guardados aqui:

  * **falha** — a última tentativa de análise deu erro. Fica em
    `PAJS_DIR/.situacao_falhas.json`, FORA do `metadata.json`, porque a
    sincronização reescreve o metadata (mesma razão de `concluidos_service`).
  * **atraso** — o `SITUACAO.md` é mais antigo que a movimentação mais nova.
    Esse não precisa ser guardado: é calculado comparando as datas.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import threading

_log = logging.getLogger(__name__)
_LOCK = threading.Lock()

ARQUIVO = ".situacao_falhas.json"

_RE_BR = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _caminho():
    from config import PAJS_DIR

    return PAJS_DIR / ARQUIVO


def _ler() -> dict:
    p = _caminho()
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception as e:
        _log.warning("registro de falhas ilegivel (%s); comecando vazio", e)
        return {}


def _gravar(dados: dict) -> None:
    p = _caminho()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def registrar_falha(paj_norm: str, erro: str) -> None:
    """Guarda que a análise deste PAJ falhou, com o motivo."""
    with _LOCK:
        d = _ler()
        anterior = d.get(paj_norm) or {}
        d[paj_norm] = {
            "erro": (erro or "")[:400],
            "em": datetime.datetime.now().isoformat(timespec="seconds"),
            "tentativas": int(anterior.get("tentativas") or 0) + 1,
        }
        _gravar(d)


def limpar_falha(paj_norm: str) -> None:
    """Análise deu certo: some o registro de falha."""
    with _LOCK:
        d = _ler()
        if d.pop(paj_norm, None) is not None:
            _gravar(d)


def falha(paj_norm: str) -> dict | None:
    return _ler().get(paj_norm)


def _data(texto: str):
    m = _RE_BR.match(texto or "")
    if m:
        return datetime.date(int(m[3]), int(m[2]), int(m[1]))
    m = _RE_ISO.match(texto or "")
    if m:
        return datetime.date(int(m[1]), int(m[2]), int(m[3]))
    return None


def estado(paj_norm: str, metadata: dict | None = None) -> dict:
    """Situação da análise deste PAJ.

    Devolve {tem_analise, gerada_em, ultima_mov, atrasada, dias_atraso,
    n_movs_depois, falha}. `atrasada` compara a DATA da análise com a data da
    movimentação mais nova — não o número de movimentações, porque a
    sincronização pode trazer movimentação antiga que não torna a análise
    velha.
    """
    from config import PAJS_DIR
    from services.prompt_builder import SITUACAO_FILE

    pasta = PAJS_DIR / paj_norm
    sit = pasta / SITUACAO_FILE
    out = {
        "tem_analise": sit.exists(),
        "gerada_em": "",
        "ultima_mov": "",
        "atrasada": False,
        "dias_atraso": 0,
        "n_movs_depois": 0,
        "falha": falha(paj_norm),
    }
    if metadata is None:
        try:
            metadata = json.loads((pasta / "metadata.json").read_text(encoding="utf-8"))
        except Exception:
            metadata = {}

    movs = (metadata.get("detalhes_sisdpu") or {}).get("movimentacoes") or []
    datas = [d for d in (_data(m.get("data_original") or m.get("data") or "")
                         for m in movs) if d]
    if not datas:
        return out
    ultima = max(datas)
    out["ultima_mov"] = ultima.isoformat()

    if not sit.exists():
        return out

    gerada = datetime.date.fromtimestamp(sit.stat().st_mtime)
    out["gerada_em"] = gerada.isoformat()
    if gerada < ultima:
        out["atrasada"] = True
        out["dias_atraso"] = (ultima - gerada).days
        out["n_movs_depois"] = sum(1 for d in datas if d > gerada)
    return out


def listar_pendencias() -> list[dict]:
    """PAJs cuja análise está atrasada ou cuja última tentativa falhou."""
    from config import PAJS_DIR

    falhas = _ler()
    saida = []
    for pasta in sorted(PAJS_DIR.glob("PAJ-*")):
        mp = pasta / "metadata.json"
        if not mp.is_dir() and not mp.exists():
            continue
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        est = estado(pasta.name, meta)
        if est["atrasada"] or est["falha"] or not est["tem_analise"]:
            saida.append({
                "paj_norm": pasta.name,
                "paj": meta.get("paj") or pasta.name,
                "assistido": meta.get("assistido_caixa") or "",
                **est,
            })
    # Mais atrasado primeiro; sem análise no fim, que é caso de PAJ novo.
    saida.sort(key=lambda i: (not i["tem_analise"], -i["dias_atraso"]))
    _ = falhas
    return saida
