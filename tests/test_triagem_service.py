"""Testes do classificador heurístico de eventos (triagem_service).

Os 3 primeiros casos de "retorno do assistido" são exemplos REAIS de
movimentações recebidas pelo Defensor (jun/2026) — não alterar sem conferir.
"""

from __future__ import annotations

from services import triagem_service as ts


def _mov(seq, descricao="", fases="", data="2026-06-01"):
    return {
        "seq": seq,
        "data": data,
        "data_original": "01/06/2026",
        "descricao": descricao,
        "movimentacao": "",
        "fases": fases,
    }


# --- classificar_movimentacao: exemplos reais de atendimento de retorno --------

def test_retorno_ex1_concluso_com_juntada():
    mov = _mov(10, descricao="Atendimento de retorno com juntada de documentos.",
               fases="Concluso ao defensor")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_RETORNO


def test_retorno_ex2_fase_automatica_sinal_na_fase():
    """Descrição é ruído ('Fase incluída automaticamente...'); o sinal está na FASE."""
    mov = _mov(11, descricao="Fase incluída automaticamente, verificar fase anterior.",
               fases="Atendimento de retorno")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_RETORNO


def test_retorno_ex3_concluso_descricao_simples():
    mov = _mov(12, descricao="Atendimento de retorno.", fases="Concluso ao defensor")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_RETORNO


# --- demais tipos ----------------------------------------------------------------

def test_intimacao():
    mov = _mov(5, descricao="Intimação eletrônica recebida — prazo de 15 dias.")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_INTIMACAO


def test_resposta_oficio():
    mov = _mov(6, descricao="Juntada de resposta de ofício do INSS.")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_RESPOSTA_OFICIO


def test_resposta_oficio_vence_intimacao():
    """Resposta de ofício que menciona a intimação original não vira 'intimacao'."""
    mov = _mov(7, descricao="Resposta ao ofício expedido após intimação do juízo.")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_RESPOSTA_OFICIO


def test_controle_prazo():
    mov = _mov(8, descricao="Controle de prazo encerrado pelo sistema.")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_CONTROLE_PRAZO


def test_abertura_redistribuicao():
    mov = _mov(1, descricao="Redistribuição do PAJ à unidade de Osasco.")
    assert ts.classificar_movimentacao(mov) == ts.TIPO_ABERTURA


def test_conclusao_generica_nao_classifica():
    mov = _mov(9, descricao="Concluso.", fases="Concluso ao defensor")
    assert ts.classificar_movimentacao(mov) is None


def test_mov_vazia_nao_classifica():
    assert ts.classificar_movimentacao({}) is None


# --- detectar_evento_recente: o cenário da duplicidade -----------------------------

def test_evento_real_atras_de_conclusao_posterior():
    """PAJ encaminhado em duplicidade: a última movimentação é uma conclusão
    genérica, mas o evento real (retorno do assistido) está antes."""
    movs = [
        _mov(20, descricao="Atendimento de retorno com juntada de documentos.",
             fases="Concluso ao defensor"),
        _mov(21, descricao="Concluso.", fases="Concluso ao defensor"),
        _mov(22, descricao="Concluso ao defensor.", fases=""),
    ]
    ev = ts.detectar_evento_recente(movs)
    assert ev is not None
    assert ev["tipo"] == ts.TIPO_RETORNO
    assert ev["seq"] == 20


def test_evento_mais_recente_vence():
    """Com dois eventos classificáveis, vale o mais recente (seq maior)."""
    movs = [
        _mov(3, descricao="Intimação eletrônica — prazo de 15 dias."),
        _mov(7, descricao="Atendimento de retorno.", fases="Concluso ao defensor"),
    ]
    ev = ts.detectar_evento_recente(movs)
    assert ev["tipo"] == ts.TIPO_RETORNO
    assert ev["seq"] == 7


def test_sem_evento_retorna_none():
    movs = [_mov(1, descricao="Concluso."), _mov(2, descricao="Juntada de guia.")]
    assert ts.detectar_evento_recente(movs) is None


def test_janela_limita_busca():
    """Evento fora da janela não é encontrado (não vasculha o histórico todo)."""
    movs = [_mov(1, descricao="Atendimento de retorno.")]
    movs += [_mov(i, descricao=f"Movimentação genérica {i}.") for i in range(2, 14)]
    assert ts.detectar_evento_recente(movs, max_janela=10) is None
