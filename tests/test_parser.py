"""Testes do parser sisdpu.txt -> metadata, foco na extração do processo judicial.

Regressão: PAJs abertos por intimação não trazem "PROCESSO JUDICIAL VINCULADO"
no cabeçalho — o número vem numa movimentação ("Número do Processo Judicial: ...")
e antes era perdido (campo "—" no sistema).
"""

from __future__ import annotations

from ingestao import parser as p


# --- formatar_cnj -----------------------------------------------------------------

def test_formatar_cnj_20_digitos_recebe_mascara():
    assert p.formatar_cnj("50000953320184036130") == "5000095-33.2018.4.03.6130"


def test_formatar_cnj_ja_mascarado_inalterado():
    assert p.formatar_cnj("5000095-33.2018.4.03.6130") == "5000095-33.2018.4.03.6130"


def test_formatar_cnj_vazio_e_desconhecido():
    assert p.formatar_cnj("") == ""
    assert p.formatar_cnj("  123  ") == "123"  # não são 20 dígitos — só apara


# --- extrair_processo_das_movs ----------------------------------------------------

def _mov(seq, descricao):
    return {"seq": seq, "descricao": descricao, "movimentacao": "", "fases": ""}


def test_extrai_numero_do_rotulo_na_movimentacao():
    movs = [
        _mov(1, "Remessa ao Cartório: Remessa ao Cartório"),
        _mov(3, "Remessa ao Gabinete: Número do Processo Judicial: 50000953320184036130"),
        _mov(4, "MOVIMENTAÇÃO MANUAL: PAJ aberto, em razão de recebimento de intimação."),
    ]
    assert p.extrair_processo_das_movs(movs) == "5000095-33.2018.4.03.6130"


def test_extrai_cnj_mascarado_como_fallback():
    movs = [_mov(1, "Intimação referente ao processo 5008792-53.2025.4.03.6306 (id 123).")]
    assert p.extrair_processo_das_movs(movs) == "5008792-53.2025.4.03.6306"


def test_sem_numero_retorna_vazio():
    movs = [_mov(1, "Concluso ao defensor."), _mov(2, "Juntada de guia.")]
    assert p.extrair_processo_das_movs(movs) == ""


# --- montar_metadata (integração) -------------------------------------------------

def test_metadata_usa_numero_da_movimentacao_quando_cabecalho_nao_tem():
    txt = (
        "PAJ: 2026/020-08893 | MOISES ALVES DOS SANTOS\n"
        "Pretensão: Cível >> RECONHECIMENTO DE CONDIÇÃO JURÍDICA\n"
        "Data de Abertura: 29/06/2026\n"
        "MOVIMENTAÇÕES\n"
        "[seq=3] [26/06/2026 10:00] Remessa ao Gabinete: Número do Processo Judicial: 50000953320184036130\n"
        "[seq=4] [26/06/2026 11:00] MOVIMENTAÇÃO MANUAL: PAJ aberto, em razão de recebimento de intimação.\n"
    )
    meta = p.montar_metadata("PAJ-2026-020-08893", txt)
    assert meta["processo_judicial"] == "5000095-33.2018.4.03.6130"


def test_metadata_prefere_cabecalho_ao_corpo():
    """Quando o cabeçalho traz o processo vinculado, ele prevalece."""
    txt = (
        "PAJ: 2023/020-01783 | LUCAS\n"
        "PROCESSO JUDICIAL VINCULADO: 5012877-53.2023.4.03.6306\n"
        "MOVIMENTAÇÕES\n"
        "[seq=3] [01/06/2026 10:00] Remessa ao Gabinete: Número do Processo Judicial: 50000953320184036130\n"
    )
    meta = p.montar_metadata("PAJ-2023-020-01783", txt)
    assert meta["processo_judicial"] == "5012877-53.2023.4.03.6306"
