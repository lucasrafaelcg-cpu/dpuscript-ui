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

from services import pje_service, situacao_service
from services.paj_service import PajNorm

router = APIRouter()


async def _stream_job(job):
    """Transmite por SSE o log e o resultado de uma corrotina `job(emit)`.

    `job` recebe o callback thread-safe `emit(linha)` (para log em tempo real)
    e devolve o dict de resultado. Concentra o encanamento SSE (fila +
    call_soon_threadsafe) usado por todas as operações do PJe.
    """
    loop = asyncio.get_running_loop()
    fila: asyncio.Queue = asyncio.Queue()

    def emit(linha: str) -> None:
        loop.call_soon_threadsafe(fila.put_nowait, ("log", str(linha)))

    async def runner():
        try:
            res = await job(emit)
        except Exception as e:  # falha inesperada na ponte/MCP/análise
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


async def _stream(func, paj_norm: str):
    """Roda `func(paj_norm, emit)` (síncrono, em thread) e transmite por SSE."""
    async def job(emit):
        return await asyncio.to_thread(func, paj_norm, emit)

    async for evento in _stream_job(job):
        yield evento


async def _job_intimacao(paj_norm: str, emit) -> dict:
    """1 clique: puxa as peças do PJe (download + OCR) e, na sequência, roda a
    análise FIRAC — as duas etapas numa única stream.

    Encadeamento: `puxar_pecas` grava `_situacao_pje.md` (peças + OCR); só então
    `gerar_situacao` roda o Claude CLI, que lê esse digest e produz `SITUACAO.md`.
    Se as peças falham, aborta antes da análise (sem peças a análise seria cega).
    Fatorada como função de módulo para ser testável sem SSE.
    """
    emit("Etapa 1/2 — baixando as peças do PJe e rodando OCR...")
    res_pecas = await asyncio.to_thread(pje_service.puxar_pecas, paj_norm, emit)
    if not res_pecas.get("ok"):
        return {**res_pecas, "etapa": "pecas"}

    emit("")
    emit("Etapa 2/2 — análise FIRAC (Fatos · Questões · Regras · Aplicação · "
         "Conclusão). O Claude lê as peças, a intimação e as movimentações.")
    emit("Isso leva de 1 a 3 minutos...")
    res_firac = await situacao_service.gerar_situacao(paj_norm)
    if res_firac.get("ok"):
        emit("Análise FIRAC concluída — abrindo a Situação do PAJ.")
    else:
        emit(f"[aviso] a análise FIRAC não concluiu: {res_firac.get('erro', '')}")

    return {
        "ok": bool(res_firac.get("ok")),
        "etapa": "firac",
        "arquivo": res_pecas.get("arquivo"),
        "chars_ocr": res_pecas.get("chars_ocr"),
        "gerada_em": res_firac.get("gerada_em"),
        "erro": res_firac.get("erro"),
    }


@router.get("/api/paj/{paj_norm}/pje/situacao/stream")
async def pje_situacao(paj_norm: PajNorm):
    """Botão 'Situação Processual': últimas movimentações + intimação/prazo."""
    return EventSourceResponse(_stream(pje_service.situacao_processual, paj_norm))


@router.get("/api/paj/{paj_norm}/pje/pecas/stream")
async def pje_pecas(paj_norm: PajNorm):
    """Botão 'Puxar peças do PJe': baixa peças recentes, OCR e grava digest."""
    return EventSourceResponse(_stream(pje_service.puxar_pecas, paj_norm))


@router.get("/api/paj/{paj_norm}/pje/intimacao/stream")
async def pje_intimacao(paj_norm: PajNorm):
    """Botão 1 clique (intimação nova): puxa as peças do PJe (download + OCR) e
    executa a análise FIRAC em sequência, numa única stream SSE."""
    return EventSourceResponse(_stream_job(lambda emit: _job_intimacao(paj_norm, emit)))
