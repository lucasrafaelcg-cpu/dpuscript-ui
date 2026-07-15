"""Testes do fechamento automático da triagem na elaboração (Fase 4).

Ao concluir uma elaboração com peça/despacho/mensagem gravada na pasta do PAJ,
o `evento_triagem` deve sair da Caixa de triagem (status → concluido).
"""

from __future__ import annotations

import json

import pytest

import config
from services import chat_service as cs


@pytest.fixture
def paj_tmp(tmp_path, monkeypatch):
    """PAJS_DIR temporário — chat_service e config (usado por concluir_evento)."""
    monkeypatch.setattr(cs, "PAJS_DIR", tmp_path)
    monkeypatch.setattr(config, "PAJS_DIR", tmp_path)
    pasta = tmp_path / "PAJ-2026-020-00001"
    pasta.mkdir()
    return pasta


def _meta_com_evento_pendente(pasta):
    pasta.joinpath("metadata.json").write_text(json.dumps({
        "paj": "2026/020-00001",
        "evento_triagem": {"tipo": "retorno_assistido", "status": "pendente",
                           "detectado_em": "2026-06-01T00:00:00"},
    }, ensure_ascii=False), encoding="utf-8")


def _status_evento(pasta):
    meta = json.loads(pasta.joinpath("metadata.json").read_text(encoding="utf-8"))
    return meta.get("evento_triagem", {}).get("status")


def test_tem_peca_gerada_distingue_peca_de_arquivo_de_sistema(paj_tmp):
    (paj_tmp / "metadata.json").write_text("{}", encoding="utf-8")
    (paj_tmp / "sisdpu.txt").write_text("x", encoding="utf-8")
    assert cs._tem_peca_gerada(paj_tmp) is False
    (paj_tmp / "peticao.txt").write_text("minuta", encoding="utf-8")
    assert cs._tem_peca_gerada(paj_tmp) is True


def test_persist_conclui_evento_quando_ha_peca(paj_tmp):
    _meta_com_evento_pendente(paj_tmp)
    (paj_tmp / "peticao.txt").write_text("minuta da inicial", encoding="utf-8")
    session = cs.ChatSession("PAJ-2026-020-00001")
    session.status = "done"
    session.summary = "Petição elaborada."
    session._persist()
    assert _status_evento(paj_tmp) == "concluido"


def test_persist_nao_conclui_sem_peca(paj_tmp):
    """Turno concluído sem peça na pasta (só conversa) não fecha a triagem."""
    _meta_com_evento_pendente(paj_tmp)
    session = cs.ChatSession("PAJ-2026-020-00001")
    session.status = "done"
    session.summary = "Pergunta ao defensor, sem produto."
    session._persist()
    assert _status_evento(paj_tmp) == "pendente"


def test_persist_nao_conclui_se_status_erro(paj_tmp):
    _meta_com_evento_pendente(paj_tmp)
    (paj_tmp / "peticao.txt").write_text("minuta", encoding="utf-8")
    session = cs.ChatSession("PAJ-2026-020-00001")
    session.status = "error"
    session._persist()
    assert _status_evento(paj_tmp) == "pendente"
