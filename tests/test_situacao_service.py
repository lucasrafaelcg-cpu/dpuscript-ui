"""Testes da análise FIRAC executada (situacao_service) — sem chamar o CLI real."""

from __future__ import annotations

import asyncio
import json
import subprocess
import types

import pytest

from services import situacao_service as ss
from services import prompt_builder as pb


@pytest.fixture
def paj_tmp(tmp_path, monkeypatch):
    """PAJS_DIR temporário compartilhado por situacao_service e prompt_builder."""
    monkeypatch.setattr(ss, "PAJS_DIR", tmp_path)
    monkeypatch.setattr(pb, "PAJS_DIR", tmp_path)
    pasta = tmp_path / "PAJ-2026-020-00001"
    pasta.mkdir()
    (pasta / "metadata.json").write_text(json.dumps({
        "paj": "2026/020-00001",
        "assistido_caixa": "",
        "detalhes_sisdpu": {"movimentacoes": [
            {"seq": 5, "data": "2026-06-01", "data_original": "01/06/2026",
             "descricao": "Atendimento de retorno com juntada de documentos.",
             "fases": "Concluso ao defensor", "movimentacao": ""},
        ]},
    }, ensure_ascii=False), encoding="utf-8")
    return pasta


def test_prompt_situacao_contem_molde_e_contexto(paj_tmp):
    prompt = ss._montar_prompt_situacao("PAJ-2026-020-00001")
    assert prompt is not None
    # contexto do PAJ presente
    assert "# PAJ 2026/020-00001" in prompt
    assert "Atendimento de retorno com juntada" in prompt
    # molde de 4 seções do Defensor
    assert "MOLDE DA RESPOSTA" in prompt
    assert "Resumo da demanda" in prompt
    assert "Razão do encaminhamento e situação atual" in prompt
    assert "Sugestão de despacho no PAJ" in prompt
    # regras de ruído
    assert "PREVISTO" in prompt
    assert "duplicidade" in prompt


def test_prompt_situacao_paj_inexistente(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "PAJS_DIR", tmp_path)
    monkeypatch.setattr(pb, "PAJS_DIR", tmp_path)
    assert ss._montar_prompt_situacao("PAJ-9999-999-99999") is None


def test_gerar_situacao_grava_arquivo_e_promptmax(paj_tmp, monkeypatch):
    """Ciclo completo com o subprocess mockado: SITUACAO.md gravado e
    PROMPT_MAX regenerado abrindo com a análise."""
    relatorio = ("1. **Resumo da demanda** — assistido busca BPC.\n"
                 "2. PAJ encaminhado ao defensor em razão de atendimento de retorno...\n"
                 "3. Sugestão: skill de mensagem ao assistido.\n"
                 "4. Sugiro o seguinte despacho no PAJ: ciência e aguardar.")

    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout=relatorio, stderr="")

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    res = asyncio.run(ss.gerar_situacao("PAJ-2026-020-00001"))
    assert res["ok"] is True

    situacao = (paj_tmp / "SITUACAO.md").read_text(encoding="utf-8")
    assert "Análise FIRAC gerada em" in situacao
    assert "Sugiro o seguinte despacho" in situacao

    prompt_max = (paj_tmp / "PROMPT_MAX.md").read_text(encoding="utf-8")
    assert prompt_max.startswith("# Situacao do PAJ — analise FIRAC ja realizada")
    assert "Sugiro o seguinte despacho" in prompt_max
    # o contexto continua presente depois da análise
    assert "## Ultimas movimentacoes" in prompt_max


def test_gerar_situacao_resposta_curta_e_erro(paj_tmp, monkeypatch):
    def fake_run(cmd, **kwargs):
        return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    res = asyncio.run(ss.gerar_situacao("PAJ-2026-020-00001"))
    assert res["ok"] is False
    assert not (paj_tmp / "SITUACAO.md").exists()


def test_gerar_situacao_timeout(paj_tmp, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=300)

    monkeypatch.setattr(ss.subprocess, "run", fake_run)
    res = asyncio.run(ss.gerar_situacao("PAJ-2026-020-00001"))
    assert res["ok"] is False
    assert "Timeout" in res["erro"]


def test_gerar_situacao_rejeita_concorrencia(paj_tmp):
    ss._em_andamento.add("PAJ-2026-020-00001")
    try:
        res = asyncio.run(ss.gerar_situacao("PAJ-2026-020-00001"))
        assert res["ok"] is False
        assert "em andamento" in res["erro"]
    finally:
        ss._em_andamento.discard("PAJ-2026-020-00001")


# --- analise_cega_intimacao_trf3 (Fase 3b × 3c) ---------------------------------

def test_intimacao_trf3_pendente_adia_analise_auto():
    """Intimação TRF3 com peças pendentes → análise do sync seria cega → adia."""
    meta = {
        "evento_triagem": {"tipo": "intimacao"},
        "pje_intimacao_pendente": {"numero": "5001234-00.2026.4.03.6130"},
    }
    assert ss.analise_cega_intimacao_trf3(meta) is True


def test_intimacao_sem_pje_pendente_analisa_normal():
    """Intimação não-TRF3 (sem peças a puxar) → análise automática roda normal."""
    meta = {"evento_triagem": {"tipo": "intimacao"}}
    assert ss.analise_cega_intimacao_trf3(meta) is False


def test_retorno_com_pje_pendente_ainda_analisa():
    """Evento não é intimação → não adia, mesmo com flag PJe remanescente."""
    meta = {
        "evento_triagem": {"tipo": "retorno_assistido"},
        "pje_intimacao_pendente": {"numero": "x"},
    }
    assert ss.analise_cega_intimacao_trf3(meta) is False


def test_sem_evento_nao_adia():
    assert ss.analise_cega_intimacao_trf3({}) is False


def test_intimacao_com_pecas_ja_puxadas_adia():
    """Peças já baixadas (pje_pecas_puxadas_em) → sync NÃO pode sobrescrever a
    FIRAC informada pelas peças com uma releitura cega."""
    meta = {
        "evento_triagem": {"tipo": "intimacao"},
        "pje_pecas_puxadas_em": "2026-07-06T17:26:00",
    }
    assert ss.analise_cega_intimacao_trf3(meta) is True


def test_intimacao_com_ultima_intimacao_arquivada_adia():
    """pje_ultima_intimacao (flag arquivado após puxar peças) também adia."""
    meta = {
        "evento_triagem": {"tipo": "intimacao"},
        "pje_ultima_intimacao": {"numero": "5001234-00.2026.4.03.6130"},
    }
    assert ss.analise_cega_intimacao_trf3(meta) is True


# --- Fila automática (análise sem botão) ----------------------------------------

@pytest.fixture
def fila_limpa():
    """Reseta o estado global da fila entre testes."""
    ss._fila_auto = None
    ss._worker_task = None
    ss._na_fila.clear()
    yield
    ss._fila_auto = None
    ss._worker_task = None
    ss._na_fila.clear()


def test_agendar_fora_de_loop_nao_quebra(fila_limpa):
    """Sem event loop (pipeline standalone), agendar é no-op seguro."""
    assert ss.agendar_analise("PAJ-2026-020-00001") is False


def test_fila_automatica_processa_e_dedupa(paj_tmp, monkeypatch, fila_limpa):
    relatorio = ("1. **Resumo da demanda** — teste da fila automática.\n"
                 "2. PAJ encaminhado ao defensor em razão de retorno.\n"
                 "3. Sugestão: skill mensagem.\n"
                 "4. Sugiro o seguinte despacho no PAJ: ciência.")
    chamadas = []

    def fake_run(cmd, **kwargs):
        chamadas.append(1)
        return types.SimpleNamespace(returncode=0, stdout=relatorio, stderr="")

    monkeypatch.setattr(ss.subprocess, "run", fake_run)

    async def cenario():
        assert ss.agendar_analise("PAJ-2026-020-00001") is True
        # dedup: mesmo PAJ na fila não entra duas vezes
        assert ss.agendar_analise("PAJ-2026-020-00001") is False
        await ss._worker_task

    asyncio.run(cenario())
    assert len(chamadas) == 1
    assert (paj_tmp / "SITUACAO.md").exists()
    assert ss.fila_status() == {"na_fila": [], "em_analise": []}
