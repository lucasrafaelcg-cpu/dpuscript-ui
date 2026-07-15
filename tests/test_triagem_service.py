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


# Exemplos REAIS de decurso de prazo (jun/2026) — movimentação automática do
# sistema. Só situação "EFETIVADO" é evento; "PREVISTO" é programação futura.

def test_decurso_efetivado_ex1_audiencia():
    mov = _mov(30, fases="Decurso de prazo",
               descricao='PAJ em decurso com situação "EFETIVADO" em 10/06/2026 '
                         'a pedido do Defensor.(AUDIÊNCIA - 17/06 às 14hs)')
    assert ts.classificar_movimentacao(mov) == ts.TIPO_CONTROLE_PRAZO


def test_decurso_efetivado_ex2_protocolar():
    mov = _mov(31, fases="Decurso de prazo",
               descricao='PAJ em decurso com situação "EFETIVADO" em 08/06/2026 '
                         'a pedido do Defensor. (PRETIÇÃO INICIAL - PROTOCOLAR)')
    assert ts.classificar_movimentacao(mov) == ts.TIPO_CONTROLE_PRAZO


def test_decurso_efetivado_ex3_automatico():
    mov = _mov(32, fases="Decurso de prazo",
               descricao='PAJ em decurso com situação "EFETIVADO" em 08/06/2026 '
                         'a pedido do Defensor. (Decurso incluído automaticamente.)')
    assert ts.classificar_movimentacao(mov) == ts.TIPO_CONTROLE_PRAZO


def test_decurso_previsto_e_ignorado():
    """Inclusão do PAJ no decurso (situação PREVISTO) NÃO é envio ao defensor."""
    mov = _mov(33, fases="Decurso de prazo",
               descricao='PAJ em decurso alterado de "29/11/2026" para "29/05/2028" '
                         'com situação "PREVISTO" a pedido do Defensor.'
                         '(Decurso incluído automaticamente)')
    assert ts.classificar_movimentacao(mov) is None


def test_decurso_previsto_nao_mascara_evento_anterior():
    """PREVISTO posterior é pulado; o evento real anterior é encontrado."""
    movs = [
        _mov(40, descricao="Atendimento de retorno.", fases="Concluso ao defensor"),
        _mov(41, fases="Decurso de prazo",
             descricao='PAJ em decurso com situação "PREVISTO" a pedido do Defensor.'),
    ]
    ev = ts.detectar_evento_recente(movs)
    assert ev["tipo"] == ts.TIPO_RETORNO
    assert ev["seq"] == 40


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


# --- classificar_ultima_movimentacao: coluna "Última mov." da caixa ----------------

def test_ultima_mov_rotulos_curtos():
    """Os 4 fluxos da caixa usam os nomes exatos pedidos pelo Defensor."""
    casos = {
        ts.TIPO_RETORNO: ("Atendimento de retorno.", "Retorno do assistido"),
        ts.TIPO_ABERTURA: ("Redistribuição do PAJ à unidade de Osasco.", "Abertura de PAJ"),
        ts.TIPO_INTIMACAO: ("Intimação eletrônica — prazo de 15 dias.", "Intimação"),
        ts.TIPO_RESPOSTA_OFICIO: ("Resposta de ofício do INSS.", "Resposta de ofício"),
    }
    for tipo, (descricao, label) in casos.items():
        r = ts.classificar_ultima_movimentacao([_mov(5, descricao=descricao)])
        assert r["tipo"] == tipo
        assert r["label"] == label


def test_ultima_mov_pula_decurso_e_mostra_evento_real():
    """Decurso automático por cima da intimação: a coluna mostra a intimação."""
    movs = [
        _mov(50, descricao="Intimação eletrônica — prazo de 15 dias."),
        _mov(51, fases="Decurso de prazo",
             descricao='PAJ em decurso com situação "EFETIVADO" a pedido do Defensor.'),
    ]
    r = ts.classificar_ultima_movimentacao(movs)
    assert r["tipo"] == ts.TIPO_INTIMACAO
    assert r["seq"] == 50


def test_ultima_mov_controle_prazo_puro_nao_aparece():
    """Só há controle de prazo: não é um dos 4 fluxos → coluna vazia (None)."""
    movs = [_mov(60, fases="Decurso de prazo",
                 descricao='PAJ em decurso com situação "EFETIVADO".')]
    assert ts.classificar_ultima_movimentacao(movs) is None


def test_ultima_mov_ignora_conclusao_duplicidade():
    """Mesma regra anti-fantasma: conclusão genérica posterior não mascara."""
    movs = [
        _mov(70, descricao="Atendimento de retorno com juntada de documentos."),
        _mov(71, descricao="Concluso.", fases="Concluso ao defensor"),
    ]
    r = ts.classificar_ultima_movimentacao(movs)
    assert r["tipo"] == ts.TIPO_RETORNO
    assert r["seq"] == 70


def test_ultima_mov_sem_evento_retorna_none():
    movs = [_mov(1, descricao="Concluso."), _mov(2, descricao="Juntada de guia.")]
    assert ts.classificar_ultima_movimentacao(movs) is None


# --- atualizar_evento_triagem (gancho do sincronizador) -----------------------------

def _meta(movs):
    return {"detalhes_sisdpu": {"movimentacoes": movs}}


def test_atualizar_paj_novo_com_evento():
    meta = _meta([_mov(5, descricao="Atendimento de retorno.",
                       fases="Concluso ao defensor")])
    assert ts.atualizar_evento_triagem(meta, movs_antigas=[], paj_novo=True)
    ev = meta["evento_triagem"]
    assert ev["tipo"] == ts.TIPO_RETORNO
    assert ev["status"] == "pendente"
    assert ev["detectado_em"]


def test_atualizar_paj_novo_sem_evento_vira_abertura():
    meta = _meta([_mov(1, descricao="Concluso.")])
    assert ts.atualizar_evento_triagem(meta, movs_antigas=[], paj_novo=True)
    assert meta["evento_triagem"]["tipo"] == ts.TIPO_ABERTURA


def test_atualizar_mov_nova_gera_evento():
    antigas = [_mov(1, descricao="Concluso.")]
    novas = [*antigas, _mov(2, descricao="Intimação eletrônica — 15 dias.")]
    meta = _meta(novas)
    assert ts.atualizar_evento_triagem(meta, movs_antigas=antigas)
    assert meta["evento_triagem"]["tipo"] == ts.TIPO_INTIMACAO


def test_atualizar_resync_sem_mov_nova_nao_reabre():
    """Re-sincronizar com as mesmas movimentações não recoloca na fila —
    inclusive evento já concluído pelo Defensor."""
    movs = [_mov(2, descricao="Intimação eletrônica — 15 dias.")]
    meta = _meta(movs)
    meta["evento_triagem"] = {"tipo": ts.TIPO_INTIMACAO, "seq": 2,
                              "status": "concluido"}
    assert not ts.atualizar_evento_triagem(meta, movs_antigas=movs)
    assert meta["evento_triagem"]["status"] == "concluido"


def test_atualizar_evento_pendente_nao_e_sobrescrito_pelo_mesmo_seq():
    antigas = [_mov(1, descricao="Concluso.")]
    novas = [*antigas, _mov(2, descricao="Intimação eletrônica.")]
    meta = _meta(novas)
    meta["evento_triagem"] = {"tipo": ts.TIPO_INTIMACAO, "seq": 2,
                              "status": "pendente", "detectado_em": "2026-06-01T10:00:00"}
    assert not ts.atualizar_evento_triagem(meta, movs_antigas=antigas)
    assert meta["evento_triagem"]["detectado_em"] == "2026-06-01T10:00:00"


# --- listar_fila / concluir_evento ---------------------------------------------------

import json as _json  # noqa: E402


def _criar_paj(pajs_dir, nome, meta):
    pasta = pajs_dir / nome
    pasta.mkdir()
    (pasta / "metadata.json").write_text(
        _json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_listar_fila_e_concluir(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "PAJS_DIR", tmp_path)

    _criar_paj(tmp_path, "PAJ-2026-020-00001", {
        "paj": "2026/020-00001", "assistido_caixa": "FULANO",
        "processo_judicial": "5001690-86.2026.4.03.6130",
        "evento_triagem": {"tipo": ts.TIPO_INTIMACAO, "label": "Intimação judicial",
                           "seq": 9, "status": "pendente",
                           "detectado_em": "2026-06-10T08:00:00"},
    })
    _criar_paj(tmp_path, "PAJ-2026-020-00002", {
        "paj": "2026/020-00002",
        "evento_triagem": {"tipo": ts.TIPO_RETORNO, "label": "Retorno do Assistido",
                           "seq": 3, "status": "concluido"},
    })
    _criar_paj(tmp_path, "PAJ-2026-020-00003", {"paj": "2026/020-00003"})

    fila = ts.listar_fila()
    assert len(fila) == 1
    assert fila[0]["paj_norm"] == "PAJ-2026-020-00001"
    assert fila[0]["trf3"] is True

    assert ts.concluir_evento("PAJ-2026-020-00001")
    assert ts.listar_fila() == []
    meta = _json.loads(
        (tmp_path / "PAJ-2026-020-00001" / "metadata.json").read_text(encoding="utf-8"))
    assert meta["evento_triagem"]["status"] == "concluido"
    assert meta["evento_triagem"]["concluido_em"]


def test_concluir_evento_paj_sem_evento(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "PAJS_DIR", tmp_path)
    _criar_paj(tmp_path, "PAJ-2026-020-00009", {"paj": "2026/020-00009"})
    assert not ts.concluir_evento("PAJ-2026-020-00009")
    assert not ts.concluir_evento("PAJ-2026-020-99999")


def test_listar_fila_situacao_pronta(tmp_path, monkeypatch):
    """SITUACAO.md mais novo que o evento → item marcado como análise pronta;
    evento mais novo que o arquivo (análise velha) → não pronta."""
    import config
    monkeypatch.setattr(config, "PAJS_DIR", tmp_path)

    _criar_paj(tmp_path, "PAJ-2026-020-00010", {
        "paj": "2026/020-00010",
        "evento_triagem": {"tipo": ts.TIPO_RETORNO, "label": "Retorno do Assistido",
                           "seq": 5, "status": "pendente",
                           "detectado_em": "2020-01-01T00:00:00"},
    })
    (tmp_path / "PAJ-2026-020-00010" / "SITUACAO.md").write_text(
        "análise", encoding="utf-8")  # mtime = agora >> detectado_em

    _criar_paj(tmp_path, "PAJ-2026-020-00011", {
        "paj": "2026/020-00011",
        "evento_triagem": {"tipo": ts.TIPO_INTIMACAO,
                           "label": "Intimação judicial",
                           "seq": 7, "status": "pendente",
                           "detectado_em": "2099-01-01T00:00:00"},
    })
    (tmp_path / "PAJ-2026-020-00011" / "SITUACAO.md").write_text(
        "análise velha", encoding="utf-8")  # evento "futuro" → análise defasada

    fila = {i["paj_norm"]: i for i in ts.listar_fila()}
    assert fila["PAJ-2026-020-00010"]["situacao_pronta"] is True
    assert fila["PAJ-2026-020-00011"]["situacao_pronta"] is False
