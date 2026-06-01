"""Rota para servir arquivos de PAJs (PDFs, TXTs, JSONs)."""

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse

from services.paj_service import PajNorm, ler_arquivo, ler_texto_robusto

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
