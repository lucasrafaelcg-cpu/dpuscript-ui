"""Marcacao "concluido" do painel — controle pessoal do Defensor.

Serve SO' para tirar o PAJ da listagem do dashboard, de modo que sobre na tela
o que ainda falta analisar. NAO tem efeito nenhum no SIS-DPU, nao arquiva nada
e nao impede o PAJ de voltar.

Por que um arquivo proprio, e nao um campo no metadata.json: o sincronizador
reescreve o metadata a cada passagem, carregando adiante apenas os campos que
ele conhece. Um campo novo ali seria apagado na primeira sincronizacao. Aqui a
marca fica em `<PAJS_DIR>/.concluidos.json`, fora do alcance do sync.

Como o PAJ reaparece: a marca guarda o `max_seq_mov` do momento em que foi
feita. O dashboard esconde o PAJ enquanto a maior sequencia de movimentacao
continuar a mesma. Chegando movimentacao nova, a sequencia cresce, a marca
deixa de valer e o PAJ volta sozinho para a lista — que e' o comportamento
pedido: concluir nao impede o PAJ de reaparecer numa nova sincronizacao.
"""

from __future__ import annotations

import json
from datetime import datetime

from config import PAJS_DIR

CONCLUIDOS_FILE = PAJS_DIR / ".concluidos.json"


def _carregar() -> dict:
    if not CONCLUIDOS_FILE.exists():
        return {"itens": {}, "atualizado_em": None}
    try:
        d = json.loads(CONCLUIDOS_FILE.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not isinstance(d.get("itens"), dict):
            return {"itens": {}, "atualizado_em": None}
        return d
    except Exception:
        # Arquivo corrompido nao pode derrubar o dashboard inteiro: sem marca,
        # o pior que acontece e' o PAJ continuar aparecendo.
        return {"itens": {}, "atualizado_em": None}


def _salvar(d: dict) -> None:
    d["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    PAJS_DIR.mkdir(parents=True, exist_ok=True)
    CONCLUIDOS_FILE.write_text(
        json.dumps(d, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def concluir(paj_norm: str, max_seq_mov: int = 0) -> dict:
    """Marca o PAJ como concluido no painel, no estado de movimentacao atual."""
    d = _carregar()
    d["itens"][paj_norm] = {
        "concluido_em": datetime.now().isoformat(timespec="seconds"),
        "seq_na_conclusao": int(max_seq_mov or 0),
    }
    _salvar(d)
    return {"ok": True, "paj_norm": paj_norm, "seq_na_conclusao": int(max_seq_mov or 0)}


def reabrir(paj_norm: str) -> dict:
    """Desfaz a marca — o PAJ volta imediatamente para a listagem."""
    d = _carregar()
    existia = d["itens"].pop(paj_norm, None) is not None
    _salvar(d)
    return {"ok": True, "paj_norm": paj_norm, "existia": existia}


def esta_concluido(paj_norm: str, max_seq_mov: int = 0) -> bool:
    """True se o PAJ foi concluido e NADA se moveu desde entao."""
    item = _carregar()["itens"].get(paj_norm)
    if not item:
        return False
    return int(max_seq_mov or 0) <= int(item.get("seq_na_conclusao", 0) or 0)


def mapa() -> dict[str, dict]:
    """Todas as marcas, para o dashboard filtrar numa leitura so'."""
    return _carregar()["itens"]
