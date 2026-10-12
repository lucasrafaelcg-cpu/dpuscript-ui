"""Rotas da aba Diligências — fila do que ainda não foi ao SISDPU.

Leitura e marcação são triviais. O que exige cuidado é `/anexar`: ele GRAVA no
SISDPU, e movimentação gravada não é removível pelo Defensor. As travas estão
em `services/diligencias_lote` e em `ingestao/sisdpu_movimentacao`; aqui só se
valida a entrada e se dispara.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse

from services import diligencias_lote as lote
from services import diligencias_service as ds

router = APIRouter()


@router.get("/diligencias", response_class=HTMLResponse)
async def pagina_diligencias(request: Request):
    template = request.app.state.jinja.get_template("diligencias.html")
    ambiente = getattr(request.app.state, "ambiente", {})
    return HTMLResponse(template.render(request=request, ambiente=ambiente))


@router.get("/api/diligencias")
async def listar_diligencias():
    itens = ds.listar()
    return {
        "itens": itens,
        "lote": lote.estado(),
        "n_pendentes": sum(1 for i in itens if i["status"] != ds.STATUS_ANEXADO),
        "n_marcados": sum(1 for i in itens
                          if i.get("marcado") and i["status"] != ds.STATUS_ANEXADO),
    }


@router.post("/api/diligencias")
async def registrar_diligencia(corpo: dict = Body(default={})):
    """Põe um arquivo do PAJ na fila (botão da tela do PAJ)."""
    paj_norm = corpo.get("paj_norm") or ""
    arquivo = corpo.get("arquivo") or ""
    if not ds.paj_norm_valido(paj_norm):
        return JSONResponse({"ok": False, "erro": f"paj_norm inválido: {paj_norm}"},
                            status_code=400)
    if not isinstance(arquivo, str) or not arquivo.strip():
        return JSONResponse({"ok": False, "erro": "arquivo não informado"},
                            status_code=400)

    tipo = corpo.get("tipo")
    if tipo not in (ds.TIPO_DESPACHO, ds.TIPO_PECA):
        # Mesma regra da aba Despachos: classifica pelo nome do arquivo.
        from services.paj_service import PREFIXOS_DESPACHO, _normalizar

        tipo = (ds.TIPO_DESPACHO
                if _normalizar(arquivo).startswith(PREFIXOS_DESPACHO)
                else ds.TIPO_PECA)

    res = ds.registrar(paj_norm, arquivo, tipo, titulo=corpo.get("titulo") or "")
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@router.post("/api/diligencias/{item_id}/marcar")
async def marcar_diligencia(item_id: str, corpo: dict = Body(default={})):
    res = ds.marcar(item_id, bool(corpo.get("marcado")))
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@router.post("/api/diligencias/marcar-todos")
async def marcar_todas(corpo: dict = Body(default={})):
    n = ds.marcar_todos(bool(corpo.get("marcado")))
    return {"ok": True, "n": n}


@router.post("/api/diligencias/{item_id}/visibilidade")
async def visibilidade_diligencia(item_id: str, corpo: dict = Body(default={})):
    res = ds.definir_visibilidade(item_id, bool(corpo.get("visivel")))
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@router.delete("/api/diligencias/{item_id}")
async def remover_diligencia(item_id: str):
    res = ds.remover(item_id)
    return JSONResponse(res, status_code=200 if res.get("ok") else 404)


@router.post("/api/diligencias/limpar-anexados")
async def limpar_anexados():
    return {"ok": True, "n": ds.limpar_anexados()}


@router.post("/api/diligencias/anexar")
async def anexar_marcados(corpo: dict = Body(default={})):
    """ESCRITA no SISDPU, em lote. Um login para todos os itens marcados.

    O clique do Defensor é o pedido, e o pedido dele já é a autorização — a
    confirmação na tela é guarda contra clique acidental. As travas do lote
    continuam valendo: elas impedem gravação ERRADA, não pedem permissão.
    """
    ids = corpo.get("ids")
    if ids is not None and not isinstance(ids, list):
        return JSONResponse({"ok": False, "erro": "ids tem que ser lista"},
                            status_code=400)
    res = lote.iniciar([str(i) for i in ids] if ids else None,
                       ensaio=bool(corpo.get("ensaio")))
    return JSONResponse(res, status_code=200 if res.get("ok") else 409)


@router.get("/api/diligencias/lote")
async def estado_do_lote():
    return lote.estado()


@router.post("/api/paj/{paj_norm}/despacho-firac")
async def extrair_despacho_da_analise(paj_norm: str, corpo: dict = Body(default={})):
    """Extrai o despacho da seção 4 da análise e põe na aba Despachos.

    Serve para os PAJs analisados ANTES desta função existir: o despacho
    sugerido ficou só dentro da SITUACAO.md. Não sobrescreve despacho já
    criado a partir da mesma análise.
    """
    from services import despacho_firac

    if not ds.paj_norm_valido(paj_norm):
        return JSONResponse({"ok": False, "erro": f"paj_norm inválido: {paj_norm}"},
                            status_code=400)

    res = despacho_firac.criar_do_firac(paj_norm)
    if not res.get("ok"):
        return JSONResponse(res, status_code=400)

    if corpo.get("enfileirar", True):
        ds.registrar(paj_norm, res["arquivo"], ds.TIPO_DESPACHO,
                     titulo="Despacho sugerido na análise")
    return JSONResponse(res)
