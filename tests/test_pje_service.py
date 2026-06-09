"""Testes da lógica pura de services/pje_service.py (sem rede, sem Chrome).

Rodar: .venv\\Scripts\\python.exe -m pytest tests/ -q
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from services import pje_service


# --- eh_trf3_1g ---------------------------------------------------------------

@pytest.mark.parametrize("numero", [
    "5001690-86.2026.4.03.6130",        # formatado, TRF3 1g
    "50016908620264036130",             # só dígitos
    "0001234-56.2024.4.03.6100",
])
def test_eh_trf3_1g_aceita(numero):
    assert pje_service.eh_trf3_1g(numero)


@pytest.mark.parametrize("numero", [
    "",                                  # vazio
    None,                                # ausente
    "5001690-86.2026.4.02.6130",         # TRF2
    "5001690-86.2026.8.26.0100",         # justiça estadual
    "12345",                             # curto demais
    "5001690-86.2026.4.03.61301",        # 21 dígitos
])
def test_eh_trf3_1g_rejeita(numero):
    assert not pje_service.eh_trf3_1g(numero)


# --- numero_trf3_do_paj --------------------------------------------------------

@pytest.fixture
def paj_tmp(tmp_path, monkeypatch):
    """PAJS_DIR temporário com um PAJ e metadata configurável."""
    monkeypatch.setattr(pje_service, "PAJS_DIR", tmp_path)
    pasta = tmp_path / "PAJ-2026-020-00001"
    pasta.mkdir()

    def escrever(meta: dict) -> str:
        (pasta / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return "PAJ-2026-020-00001"

    return escrever


def test_numero_trf3_do_paj_com_processo(paj_tmp):
    paj = paj_tmp({"processo_judicial": "5001690-86.2026.4.03.6130"})
    assert pje_service.numero_trf3_do_paj(paj) == "5001690-86.2026.4.03.6130"


def test_numero_trf3_do_paj_outro_tribunal(paj_tmp):
    paj = paj_tmp({"processo_judicial": "5001690-86.2026.8.26.0100"})
    assert pje_service.numero_trf3_do_paj(paj) is None


def test_numero_trf3_do_paj_sem_processo(paj_tmp):
    paj = paj_tmp({})
    assert pje_service.numero_trf3_do_paj(paj) is None


def test_numero_trf3_do_paj_inexistente(tmp_path, monkeypatch):
    monkeypatch.setattr(pje_service, "PAJS_DIR", tmp_path)
    assert pje_service.numero_trf3_do_paj("PAJ-9999-999-99999") is None


# --- _intervalo_recente ---------------------------------------------------------

def _parse_br(s: str) -> dt.date:
    d, m, a = s.split("/")
    return dt.date(int(a), int(m), int(d))


def test_intervalo_sem_flag_usa_janela_padrao(paj_tmp):
    paj = paj_tmp({})
    ini, fim = pje_service._intervalo_recente(paj)
    hoje = dt.date.today()
    assert _parse_br(fim) == hoje
    assert _parse_br(ini) == hoje - dt.timedelta(days=45)


def test_intervalo_com_intimacao(paj_tmp):
    data_int = dt.date.today() - dt.timedelta(days=10)
    paj = paj_tmp({"pje_intimacao_pendente": {"data": data_int.isoformat()}})
    ini, fim = pje_service._intervalo_recente(paj)
    assert _parse_br(ini) == data_int - dt.timedelta(days=5)
    assert _parse_br(fim) == dt.date.today()


def test_intervalo_data_futura_nao_inverte(paj_tmp):
    """Metadata corrompido com data futura não pode gerar inicio > fim."""
    futuro = dt.date.today() + dt.timedelta(days=30)
    paj = paj_tmp({"pje_intimacao_pendente": {"data": futuro.isoformat()}})
    ini, fim = pje_service._intervalo_recente(paj)
    assert _parse_br(ini) <= _parse_br(fim)


# --- _limpar_flag_intimacao ------------------------------------------------------

def test_limpar_flag_intimacao(paj_tmp, tmp_path):
    paj = paj_tmp({
        "processo_judicial": "5001690-86.2026.4.03.6130",
        "pje_intimacao_pendente": {"data": "2026-06-01", "prazo_dias": 15},
    })
    pje_service._limpar_flag_intimacao(paj)
    meta = json.loads((tmp_path / paj / "metadata.json").read_text(encoding="utf-8"))
    assert "pje_intimacao_pendente" not in meta
    assert meta["pje_ultima_intimacao"]["prazo_dias"] == 15
    assert meta["pje_pecas_puxadas_em"]


# --- _extrair_expedientes ---------------------------------------------------------

def test_extrair_expedientes_filtra_linhas_relevantes():
    html = """
    <table>
      <tr><td>Intimação eletrônica — prazo de 15 dias</td></tr>
      <tr><td>linha irrelevante sem nada</td></tr>
      <tr><td>Ciência em 01/06/2026</td></tr>
      <tr><td>Intimação eletrônica — prazo de 15 dias</td></tr>
    </table>
    """
    linhas = pje_service._extrair_expedientes(html)
    assert "Intimação eletrônica — prazo de 15 dias" in linhas
    assert "Ciência em 01/06/2026" in linhas
    # dedup: a intimação repetida aparece uma vez só
    assert len([ln for ln in linhas if "Intimação" in ln]) == 1
    assert all("irrelevante" not in ln for ln in linhas)


# --- trava de concorrência ---------------------------------------------------------

def test_lock_rejeita_operacao_concorrente(paj_tmp, monkeypatch):
    paj = paj_tmp({"processo_judicial": "5001690-86.2026.4.03.6130"})
    # Simula operação em andamento segurando o lock
    assert pje_service._PJE_LOCK.acquire(blocking=False)
    try:
        res = pje_service.situacao_processual(paj, emit=lambda _l: None)
        assert res["ok"] is False
        assert "em andamento" in res["erro"]
        res2 = pje_service.puxar_pecas(paj, emit=lambda _l: None)
        assert res2["ok"] is False
    finally:
        pje_service._PJE_LOCK.release()
