"""Testes da orquestração do botão 1 clique (routes/pje._job_intimacao).

Encadeia puxar peças (PJe/OCR) → análise FIRAC sem tocar Chrome nem Claude CLI:
os dois serviços são substituídos por fakes. Verifica a ordem das etapas, o
aborto quando as peças falham e o formato do resultado.

Rodar: .venv\\Scripts\\python.exe -m pytest tests/test_pje_routes.py -q
"""

from __future__ import annotations

import asyncio

import pytest

from routes import pje as pje_routes


def _run_job(monkeypatch, *, pecas_res, firac_res):
    """Roda _job_intimacao com puxar_pecas/gerar_situacao fakes. Devolve
    (resultado, logs, chamadas) — `chamadas` registra a ordem das etapas."""
    chamadas: list[str] = []

    def fake_puxar(paj_norm, emit):
        chamadas.append("pecas")
        emit("baixando...")
        return pecas_res

    async def fake_gerar(paj_norm):
        chamadas.append("firac")
        return firac_res

    monkeypatch.setattr(pje_routes.pje_service, "puxar_pecas", fake_puxar)
    monkeypatch.setattr(pje_routes.situacao_service, "gerar_situacao", fake_gerar)

    logs: list[str] = []
    res = asyncio.run(pje_routes._job_intimacao("PAJ-2026-020-00001", logs.append))
    return res, logs, chamadas


def test_encadeia_pecas_e_firac_em_ordem(monkeypatch):
    res, _logs, chamadas = _run_job(
        monkeypatch,
        pecas_res={"ok": True, "arquivo": "autos.pdf", "chars_ocr": 1234},
        firac_res={"ok": True, "gerada_em": "2026-07-04T10:00:00"},
    )
    assert chamadas == ["pecas", "firac"]  # peças ANTES da análise
    assert res["ok"] is True
    assert res["etapa"] == "firac"
    assert res["arquivo"] == "autos.pdf"
    assert res["chars_ocr"] == 1234
    assert res["gerada_em"] == "2026-07-04T10:00:00"


def test_aborta_quando_pecas_falham(monkeypatch):
    res, _logs, chamadas = _run_job(
        monkeypatch,
        pecas_res={"ok": False, "erro": "Falha no login", "sem_habilitacao": True},
        firac_res={"ok": True},
    )
    assert chamadas == ["pecas"]  # FIRAC NÃO roda sem peças
    assert res["ok"] is False
    assert res["etapa"] == "pecas"
    assert res["erro"] == "Falha no login"
    assert res["sem_habilitacao"] is True


def test_pecas_ok_mas_firac_falha(monkeypatch):
    res, _logs, chamadas = _run_job(
        monkeypatch,
        pecas_res={"ok": True, "arquivo": "autos.pdf", "chars_ocr": 10},
        firac_res={"ok": False, "erro": "Timeout (300s) na análise"},
    )
    assert chamadas == ["pecas", "firac"]
    assert res["ok"] is False
    assert res["etapa"] == "firac"
    assert res["arquivo"] == "autos.pdf"  # peças preservadas p/ mensagem da UI
    assert "Timeout" in res["erro"]
