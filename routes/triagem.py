"""Rotas da Caixa de triagem — fila de eventos que trouxeram PAJs à caixa.

Fase 2 do fluxo de trabalho (docs/FLUXO_DE_TRABALHO.md). O evento é gravado
na metadata pelo sincronizador (triagem_service.atualizar_evento_triagem);
aqui só leitura da fila e conclusão manual pelo Defensor.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from services import triagem_service
from services.paj_service import PAJ_NORM_REGEX, PajNorm

router = APIRouter()


@router.get("/api/triagem")
async def fila_triagem():
    """Itens pendentes da Caixa de triagem (mais recentes primeiro)."""
    return {"itens": triagem_service.listar_fila()}


@router.post("/api/triagem/concluir-todos")
async def concluir_triagem_todos(payload: dict = Body(default={})):
    """Conclui de uma vez os eventos pendentes da Caixa de triagem.

    O corpo pode trazer `pajs`: a lista que o navegador está exibindo.
    Concluir exatamente o que está na tela evita apagar evento que tenha
    chegado por sincronização depois de a página carregar. Sem a lista,
    conclui a fila inteira do servidor.

    Só escreve em PAJ cujo evento esteja de fato pendente. PAJ pedido que
    não esteja na fila volta em `ignorados`, sem alterar metadata — é o
    caso da tela desatualizada, não um erro.
    """
    pendentes = {i["paj_norm"] for i in triagem_service.listar_fila()}

    pedidos = payload.get("pajs")
    if not isinstance(pedidos, list) or not pedidos:
        pedidos = sorted(pendentes)

    concluidos: list[str] = []
    ignorados: list[str] = []
    falharam: list[str] = []
    for paj_norm in pedidos:
        if not isinstance(paj_norm, str) or not re.fullmatch(PAJ_NORM_REGEX, paj_norm):
            falharam.append(str(paj_norm))
            continue
        if paj_norm not in pendentes:
            ignorados.append(paj_norm)
            continue
        if triagem_service.concluir_evento(paj_norm):
            concluidos.append(paj_norm)
        else:
            falharam.append(paj_norm)

    return {
        "ok": not falharam,
        "concluidos": concluidos,
        "ignorados": ignorados,
        "falharam": falharam,
        "n_concluidos": len(concluidos),
    }


@router.post("/api/paj/{paj_norm}/triagem/concluir")
async def concluir_triagem(paj_norm: PajNorm):
    """Marca o evento de triagem do PAJ como concluído (sai da fila)."""
    ok = triagem_service.concluir_evento(paj_norm)
    if not ok:
        return JSONResponse(
            {"ok": False, "erro": "PAJ sem evento de triagem"}, status_code=404)
    return {"ok": True}
