"""Rotas da integração com o PJe (TRF3) — Situação Processual e Puxar Peças.

As operações do PJe são síncronas e abrem o Chrome real (Akamai bloqueia
headless), então rodam em thread (`asyncio.to_thread`); o progresso é
transmitido por SSE (mesmo padrão do `routes/sync.py`).
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from services import pje_service
from services.paj_service import PajNorm

router = APIRouter()


async def _stream(func, paj_norm: str):
    """Roda `func(paj_norm, emit)` em thread e transmite log + resultado por SSE."""
    loop = asyncio.get_running_loop()
    fila: asyncio.Queue = asyncio.Queue()

    def emit(linha: str) -> None:
        loop.call_soon_threadsafe(fila.put_nowait, ("log", str(linha)))

    async def runner():
        try:
            res = await asyncio.to_thread(func, paj_norm, emit)
        except Exception as e:  # falha inesperada na ponte/MCP
            loop.call_soon_threadsafe(fila.put_nowait, ("log", f"[ERRO] {type(e).__name__}: {e}"))
            res = {"ok": False, "erro": f"{type(e).__name__}: {e}"}
        loop.call_soon_threadsafe(fila.put_nowait, ("result", res))
        loop.call_soon_threadsafe(fila.put_nowait, ("done", None))

    task = asyncio.create_task(runner())
    try:
        while True:
            ev, data = await fila.get()
            if ev == "done":
                break
            if ev == "result":
                yield {"event": "result", "data": json.dumps(data, ensure_ascii=False, default=str)}
            else:
                yield {"event": "log", "data": str(data)}
        yield {"event": "done", "data": "Concluído"}
    finally:
        await task


@router.get("/api/paj/{paj_norm}/pje/situacao/stream")
async def pje_situacao(paj_norm: PajNorm):
    """Botão 'Situação Processual': últimas movimentações + intimação/prazo."""
    return EventSourceResponse(_stream(pje_service.situacao_processual, paj_norm))


@router.get("/api/paj/{paj_norm}/pje/pecas/stream")
async def pje_pecas(paj_norm: PajNorm):
    """Botão 'Puxar peças do PJe': baixa peças recentes, OCR e grava digest."""
    return EventSourceResponse(_stream(pje_service.puxar_pecas, paj_norm))
