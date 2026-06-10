"""Rotas da Caixa de triagem — fila de eventos que trouxeram PAJs à caixa.

Fase 2 do fluxo de trabalho (docs/FLUXO_DE_TRABALHO.md). O evento é gravado
na metadata pelo sincronizador (triagem_service.atualizar_evento_triagem);
aqui só leitura da fila e conclusão manual pelo Defensor.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services import triagem_service
from services.paj_service import PajNorm

router = APIRouter()


@router.get("/api/triagem")
async def fila_triagem():
    """Itens pendentes da Caixa de triagem (mais recentes primeiro)."""
    return {"itens": triagem_service.listar_fila()}


@router.post("/api/paj/{paj_norm}/triagem/concluir")
async def concluir_triagem(paj_norm: PajNorm):
    """Marca o evento de triagem do PAJ como concluído (sai da fila)."""
    ok = triagem_service.concluir_evento(paj_norm)
    if not ok:
        return JSONResponse(
            {"ok": False, "erro": "PAJ sem evento de triagem"}, status_code=404)
    return {"ok": True}
