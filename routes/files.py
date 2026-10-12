"""Rotas para servir e editar arquivos de PAJs (PDFs, TXTs, JSONs)."""

from fastapi import APIRouter, Body
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from services.paj_service import (
    PajNorm,
    ler_arquivo,
    ler_texto_robusto,
    salvar_texto_peca,
)

router = APIRouter()


@router.get("/files/{paj_norm}/{path:path}")
async def serve_file(paj_norm: PajNorm, path: str):
    arquivo, content_type = ler_arquivo(paj_norm, path)
    if not arquivo:
        return PlainTextResponse("Arquivo nao encontrado", status_code=404)

    if "pdf" in content_type:
        return FileResponse(arquivo, media_type=content_type, filename=arquivo.name)

    # TXT, JSON, MD — retorna como texto (encoding robusto: UTF-8/CP1252/Latin-1)
    if "text" in content_type or "json" in content_type:
        conteudo = ler_texto_robusto(arquivo)
        return PlainTextResponse(conteudo, media_type=content_type)

    return FileResponse(arquivo, media_type=content_type)


@router.post("/api/files/{paj_norm}/{path:path}")
async def salvar_arquivo(paj_norm: PajNorm, path: str, payload: dict = Body(...)):
    """Grava a edicao manual de uma peca em texto, feita no modal do painel.

    As travas (extensao, raiz do PAJ, containment, backup) ficam em
    `salvar_texto_peca` — esta rota so' transporta. POST em vez de PUT porque
    o resto do painel ja' usa POST para acao.
    """
    conteudo = payload.get("conteudo")
    if not isinstance(conteudo, str):
        return JSONResponse({"ok": False, "erro": "payload sem 'conteudo'"}, status_code=400)
    r = salvar_texto_peca(paj_norm, path, conteudo)
    return JSONResponse(r, status_code=200 if r.get("ok") else 400)
