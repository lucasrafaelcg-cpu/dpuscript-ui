"""Testes do PROMPT_MAX ("Situação do PAJ") — estrutura e instrução FIRAC."""

from __future__ import annotations

import json

import pytest

from services import prompt_builder


@pytest.fixture
def paj_workspace(tmp_path, monkeypatch):
    """PAJS_DIR temporário com um PAJ mínimo; retorna função para gravar metadata."""
    monkeypatch.setattr(prompt_builder, "PAJS_DIR", tmp_path)
    pasta = tmp_path / "PAJ-2026-020-00001"
    pasta.mkdir()

    def escrever(meta: dict) -> str:
        (pasta / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return "PAJ-2026-020-00001"

    return escrever


def _meta_com_retorno():
    return {
        "paj": "2026/020-00001",
        "assistido_caixa": "",
        "detalhes_sisdpu": {
            "movimentacoes": [
                {"seq": 5, "data": "2026-06-01", "data_original": "01/06/2026",
                 "descricao": "Atendimento de retorno com juntada de documentos.",
                 "fases": "Concluso ao defensor", "movimentacao": ""},
                {"seq": 6, "data": "2026-06-02", "data_original": "02/06/2026",
                 "descricao": "Concluso.", "fases": "", "movimentacao": ""},
            ],
        },
    }


def test_prompt_contem_instrucao_firac(paj_workspace):
    paj = paj_workspace(_meta_com_retorno())
    path = prompt_builder.gerar_prompt_max(paj)
    texto = path.read_text(encoding="utf-8")
    assert "## Analise solicitada — skill FIRAC" in texto
    assert "skill `firac`" in texto
    # Os 5 fluxos de entrada do desenho do Defensor
    assert "Abertura de PAJ" in texto
    assert "Retorno do Assistido" in texto
    assert "Intimacao judicial" in texto
    assert "Resposta de oficio" in texto
    assert "Controle de prazo" in texto
    # Orientação específica do retorno do assistido
    assert "documentos foram recebidos mas ainda estao incompletos" in texto
    # Aviso sobre o ruído de duplicidade
    assert "duplicidade" in texto


def test_prompt_inclui_evento_detectado(paj_workspace):
    paj = paj_workspace(_meta_com_retorno())
    texto = prompt_builder.gerar_prompt_max(paj).read_text(encoding="utf-8")
    assert "## Evento detectado pelo painel (heuristica)" in texto
    assert "Retorno do Assistido" in texto
    assert "seq 5" in texto  # o evento real, não a conclusão posterior (seq 6)


def test_prompt_sem_evento_omite_secao(paj_workspace):
    meta = _meta_com_retorno()
    meta["detalhes_sisdpu"]["movimentacoes"] = [
        {"seq": 1, "data": "2026-06-01", "data_original": "01/06/2026",
         "descricao": "Concluso.", "fases": "", "movimentacao": ""},
    ]
    paj = paj_workspace(meta)
    texto = prompt_builder.gerar_prompt_max(paj).read_text(encoding="utf-8")
    assert "## Evento detectado pelo painel" not in texto
    # A instrução FIRAC existe mesmo sem heurística
    assert "## Analise solicitada — skill FIRAC" in texto


def test_prompt_max_abre_com_situacao_quando_existe(paj_workspace, tmp_path):
    """Ordem definida pelo Defensor: análise FIRAC primeiro, prompt max depois."""
    paj = paj_workspace(_meta_com_retorno())
    (tmp_path / paj / "SITUACAO.md").write_text(
        "1. Resumo da demanda...\n4. Sugiro o seguinte despacho no PAJ: ciência.",
        encoding="utf-8")
    texto = prompt_builder.gerar_prompt_max(paj).read_text(encoding="utf-8")
    assert texto.startswith("# Situacao do PAJ — analise FIRAC ja realizada")
    assert texto.index("Sugiro o seguinte despacho") < texto.index("## Ultimas movimentacoes")


def test_montar_contexto_sem_instrucao(paj_workspace):
    paj = paj_workspace(_meta_com_retorno())
    ctx = prompt_builder.montar_contexto(paj)
    assert "## Ultimas movimentacoes" in ctx
    assert "## Analise solicitada" not in ctx  # instrução fica fora do contexto


def test_digest_pje_truncado(paj_workspace, tmp_path):
    paj = paj_workspace(_meta_com_retorno())
    (tmp_path / paj / "_situacao_pje.md").write_text(
        "X" * (prompt_builder.MAX_PJE_DIGEST_CHARS + 1000), encoding="utf-8")
    texto = prompt_builder.gerar_prompt_max(paj).read_text(encoding="utf-8")
    assert "Digest truncado" in texto
    assert "X" * (prompt_builder.MAX_PJE_DIGEST_CHARS + 500) not in texto
