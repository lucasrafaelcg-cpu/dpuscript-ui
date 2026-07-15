"""Regressão: o sync NÃO pode apagar o estado do fluxo (PJe/triagem).

O metadata.json é reconstruído do zero pelo parser a cada sincronização (só a
partir do sisdpu.txt). Sem preservação, cada sync da caixa apagava os campos
gravados pelos serviços DEPOIS do sync (peças do PJe puxadas, intimação
tratada, evento de triagem) — fazendo as ações de sessões anteriores "sumirem"
do PAJ. Este teste fixa o contrato de preservação.
"""

from __future__ import annotations

import asyncio
import json

import config
from ingestao import sincronizador as sinc


def _det_intimacao():
    """Detalhamento com UMA intimação (seq=5) — reusado como estado anterior."""
    return {
        "paj": "2026/020-08893",
        "assistido": "MOISES ALVES DOS SANTOS",
        "status_paj": "ATIVO",
        "pretensao": "Indenização por danos morais",
        "data_abertura": "22/05/2026",
        "oficio": "",
        "processo_judicial": "5000095-33.2018.4.03.6130",
        "juizo": "2ª Vara Federal de Osasco",
        "foro_detalhado": "2ª Vara Federal de Osasco",
        "decurso": "",
        "movimentacoes": [
            {
                "seq": "5",
                "data": "01/06/2026",
                "movimentacao": "Intimação",
                "descricao": "Intimação da parte para manifestação (citação por edital).",
            }
        ],
    }


def test_sync_preserva_estado_do_fluxo(tmp_path, monkeypatch):
    monkeypatch.setattr(sinc, "PAJS_DIR", tmp_path)
    # Sem FIRAC automática no teste (não invocar o Claude CLI).
    monkeypatch.setattr(config, "SITUACAO_AUTO", False, raising=False)

    paj_norm = "PAJ-2026-020-08893"
    pasta = tmp_path / paj_norm
    pasta.mkdir(parents=True)

    # Estado ANTERIOR: peças do PJe já puxadas + intimação arquivada + evento de
    # triagem pendente. As mesmas movimentações (seq=5) → sync sem mov nova.
    det = _det_intimacao()
    meta_antiga = {
        "paj": "2026/020-08893",
        "paj_norm": paj_norm,
        "processo_judicial": det["processo_judicial"],
        "pje_pecas_puxadas_em": "2026-07-06T17:26:00",
        "pje_ultima_intimacao": {"numero": det["processo_judicial"], "data": "2026-06-01"},
        "evento_triagem": {
            "tipo": "intimacao", "label": "Intimação judicial", "seq": 5,
            "data": "01/06/2026", "descricao": "Intimação da parte",
            "status": "pendente", "detectado_em": "2026-07-05T10:00:00",
        },
        "detalhes_sisdpu": {"status_paj": "ATIVO", "movimentacoes": det["movimentacoes"]},
    }
    (pasta / "metadata.json").write_text(
        json.dumps(meta_antiga, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    item = {"paj": "2026/020-08893", "oficio": "( A. 03º OFÍCIO GERAL )", "etiqueta": ""}

    logs: list[str] = []
    paj_ret, ok = asyncio.run(
        sinc._processar_paj_pos_detalhamento(
            item, det, logs.append, baixar_anexos=False, via_busca_global=False,
        )
    )
    assert ok is True
    assert paj_ret == paj_norm

    meta_nova = json.loads((pasta / "metadata.json").read_text(encoding="utf-8"))

    # Campos de estado do fluxo sobreviveram ao rebuild do parser.
    assert meta_nova.get("pje_pecas_puxadas_em") == "2026-07-06T17:26:00"
    assert meta_nova.get("pje_ultima_intimacao", {}).get("numero") == det["processo_judicial"]
    # Sem movimentação nova (seq=5 já era o máximo), o evento pendente permanece.
    assert (meta_nova.get("evento_triagem") or {}).get("status") == "pendente"
    assert (meta_nova.get("evento_triagem") or {}).get("seq") == 5
