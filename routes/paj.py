"""Rota de detalhe do PAJ."""

from fastapi import APIRouter, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse

from services.paj_service import (
    PajNorm,
    ler_paj,
    ler_notas,
    limpar_anexos_paj,
    salvar_notas,
)

router = APIRouter()


@router.get("/paj/{paj_norm}", response_class=HTMLResponse)
async def paj_detail(request: Request, paj_norm: PajNorm):
    dados = ler_paj(paj_norm)
    if not dados:
        return HTMLResponse("<h1>PAJ não encontrado</h1>", status_code=404)
    template = request.app.state.jinja.get_template("paj_detail.html")
    html = template.render(request=request, dados=dados, paj_norm=paj_norm)
    return HTMLResponse(html)


@router.get("/api/paj/{paj_norm}", response_class=JSONResponse)
async def api_paj(paj_norm: PajNorm):
    dados = ler_paj(paj_norm)
    if not dados:
        return JSONResponse({"erro": "PAJ não encontrado"}, status_code=404)
    # Remove prompt_max do JSON (muito grande) — tem endpoint proprio
    dados_resumo = {k: v for k, v in dados.items() if k != "prompt_max"}
    return dados_resumo


@router.post("/api/lote/contexto", response_class=JSONResponse)
async def lote_contexto(corpo: dict = Body(default={})):
    """Consolida VARIOS PAJs num contexto unico para analise conjunta.

    Reaproveita o `metadata.json` e a analise FIRAC (`SITUACAO.md`) que ja'
    existem em cada PAJ — nao reanalisa nada. Serve para decidir se cabe uma
    peca unica (tipicamente um oficio) abarcando mais de um caso.

    Corpo: {"lista": "texto livre com os PAJs"} e/ou {"pajs": [...]},
           opcional {"imagem": "caminho/da/foto.jpg"} para ler por OCR,
           opcional {"salvar_em": "caminho.md"}.
    """
    from pathlib import Path as _Path

    from services import lote_service as ls

    bruto = str(corpo.get("lista") or "")
    for p in corpo.get("pajs") or []:
        bruto += f" {p}"

    pajs = ls.extrair_pajs(bruto)
    ocr_texto = None
    if corpo.get("imagem"):
        try:
            achados, ocr_texto = ls.extrair_pajs_de_imagem(corpo["imagem"])
        except Exception as e:
            return JSONResponse(
                {"ok": False, "erro": f"OCR falhou: {type(e).__name__}: {e}"},
                status_code=400,
            )
        for p in achados:
            if p not in pajs:
                pajs.append(p)

    if not pajs:
        return JSONResponse(
            {
                "ok": False,
                "erro": "nenhum PAJ reconhecido na entrada",
                "ocr_texto": (ocr_texto or "")[:400] or None,
            },
            status_code=400,
        )

    res = ls.montar_contexto_lote(pajs, origem_ocr=bool(corpo.get("imagem")))
    destino = corpo.get("salvar_em")
    if destino:
        _Path(destino).write_text(res["texto"], encoding="utf-8")
        res["salvo_em"] = destino
        res.pop("texto", None)  # evita devolver 100k inline sem necessidade
    return JSONResponse({"ok": True, **res})


@router.post("/api/paj/{paj_norm}/descricao-movimentacao", response_class=JSONResponse)
async def descricao_movimentacao(paj_norm: PajNorm, corpo: dict = Body(default={})):
    """Sugere a descricao da movimentacao para a peca `arquivo` (relativo ao PAJ).

    So' LEITURA: nao toca no SISDPU. O texto volta para o Defensor revisar
    antes de anexar. Corpo: {arquivo}
    """
    from services import descricao_movimentacao_service as dms

    arquivo = str(corpo.get("arquivo") or "")
    if not arquivo:
        return JSONResponse({"ok": False, "erro": "arquivo ausente"}, status_code=400)
    return JSONResponse(await dms.gerar_descricao(paj_norm, arquivo))


@router.post("/api/paj/{paj_norm}/movimentar", response_class=JSONResponse)
async def movimentar_paj(paj_norm: PajNorm, corpo: dict = Body(default={})):
    """ESCRITA no SISDPU: inclui movimentacao no PAJ (com anexo opcional).

    Unico endpoint do painel que ALTERA o SISDPU. O default da API e'
    DRY-RUN (preenche, tira screenshot e PARA) — conservador para quem
    chama a API na mao. Grava com `{"confirmar": true}`.

    Politica definida pelo Defensor: o PEDIDO dele ja' e' a autorizacao,
    entao a aba Discussao manda `confirmar: true` direto, sem reconfirmar.
    As travas do modulo continuam valendo: evitam gravacao ERRADA (PAJ
    divergente, fase inexistente, anexo ausente) — assunto de correcao,
    nao de permissao.

    Corpo: {fase, descricao_html, anexos: [caminhos], tipo_arquivo,
            mostrar_na_internet, confirmar}
    """
    import re as _re

    from ingestao import sisdpu_movimentacao as mv

    m = _re.match(r"PAJ-(\d{4})-(\d{3})-(\d+)$", paj_norm)
    if not m:
        return JSONResponse(
            {"ok": False, "erro": f"paj_norm invalido: {paj_norm}"}, status_code=400
        )
    ano, unidade, numero = m.group(1), m.group(2), m.group(3)

    # `anexos_no_paj`: caminhos RELATIVOS a pasta do PAJ — e' o que a interface
    # usa. Resolver aqui (com checagem de containment) evita que o navegador
    # precise conhecer caminho absoluto e impede pedir arquivo de fora do PAJ.
    from pathlib import Path as _P

    from config import PAJS_DIR as _PAJS

    anexos = list(corpo.get("anexos") or [])
    raiz = (_PAJS / paj_norm).resolve()
    for rel in corpo.get("anexos_no_paj") or []:
        alvo = (raiz / str(rel)).resolve()
        try:
            alvo.relative_to(raiz)
        except ValueError:
            return JSONResponse(
                {"ok": False, "erro": f"anexo fora da pasta do PAJ: {rel}"},
                status_code=400,
            )
        anexos.append(str(alvo))

    try:
        res = await mv.inserir_movimentacao(
            numero=numero,
            ano=ano,
            unidade=unidade,
            fase=corpo.get("fase") or mv.FASE_PETICAO_CONTEUDO_JURIDICO,
            descricao_html=corpo.get("descricao_html") or "",
            anexos=anexos,
            tipo_arquivo=corpo.get("tipo_arquivo") or mv.TIPO_ARQUIVO_PETICOES,
            mostrar_na_internet=corpo.get("mostrar_na_internet"),
            confirmar=bool(corpo.get("confirmar")),
        )
    except mv.MovimentacaoAbortada as e:
        # Trava de seguranca reprovou — nada foi gravado.
        return JSONResponse(
            {"ok": False, "abortado": True, "erro": str(e)}, status_code=409
        )
    except Exception as e:  # falha tecnica (sessao, rede, seletor)
        return JSONResponse(
            {"ok": False, "erro": f"{type(e).__name__}: {e}"}, status_code=502
        )

    return JSONResponse({"ok": True, **res})


@router.post("/api/paj/{paj_norm}/concluir", response_class=JSONResponse)
async def concluir_paj(paj_norm: PajNorm, payload: dict = Body(default={})):
    """Tira o PAJ da listagem do dashboard. Marca pessoal, sem efeito no SIS.

    `max_seq_mov` vem do proprio item da lista: e' a maior sequencia de
    movimentacao no momento em que o Defensor concluiu. Chegando movimentacao
    nova, a sequencia cresce e o PAJ volta sozinho para a lista.
    """
    from services import concluidos_service
    from services.paj_service import invalidar_cache_listagem

    res = concluidos_service.concluir(paj_norm, payload.get("max_seq_mov") or 0)
    invalidar_cache_listagem()   # o botao tem que sumir o PAJ na hora
    return JSONResponse(res)


@router.post("/api/paj/{paj_norm}/reabrir", response_class=JSONResponse)
async def reabrir_paj(paj_norm: PajNorm):
    """Desfaz a conclusao: o PAJ volta imediatamente para a listagem."""
    from services import concluidos_service
    from services.paj_service import invalidar_cache_listagem

    res = concluidos_service.reabrir(paj_norm)
    invalidar_cache_listagem()
    return JSONResponse(res)


@router.post("/api/paj/{paj_norm}/abrir-pasta", response_class=JSONResponse)
async def abrir_pasta_paj(paj_norm: PajNorm):
    """Abre a pasta do PAJ no gerenciador de arquivos da maquina.

    Precisa ser feito no SERVIDOR: o navegador bloqueia links `file://`
    disparados de uma pagina `http://`. Como o painel roda na propria maquina
    do Defensor, abrir daqui tem o mesmo efeito de um duplo clique na pasta.
    """
    from services.paj_service import abrir_pasta_no_explorer

    res = abrir_pasta_no_explorer(paj_norm)
    return JSONResponse(res, status_code=200 if res.get("ok") else 400)


@router.post("/api/paj/{paj_norm}/situacao/gerar", response_class=JSONResponse)
async def gerar_situacao(paj_norm: PajNorm):
    """Roda a análise FIRAC da situação atual (Claude CLI headless) e grava
    SITUACAO.md — conteúdo da aba 'Situação do PAJ'. Demora 1-3 min."""
    from services.situacao_service import gerar_situacao as _gerar

    res = await _gerar(paj_norm)
    return JSONResponse(res, status_code=200 if res.get("ok") else 502)


@router.get("/api/paj/{paj_norm}/limpar-anexos/preview", response_class=JSONResponse)
async def limpar_anexos_preview(paj_norm: PajNorm):
    """Dry-run: lista o que seria apagado e mostra bloqueios de seguranca."""
    resultado = limpar_anexos_paj(paj_norm, dry_run=True)
    if not resultado.get("ok"):
        return JSONResponse(resultado, status_code=404)
    return resultado


@router.post("/api/paj/{paj_norm}/limpar-anexos", response_class=JSONResponse)
async def limpar_anexos_executar(paj_norm: PajNorm, forcar: bool = False):
    """Executa a limpeza. Se forcar=True, ignora os bloqueios de seguranca."""
    resultado = limpar_anexos_paj(paj_norm, dry_run=False, forcar=forcar)
    if not resultado.get("ok"):
        return JSONResponse(resultado, status_code=400)
    return resultado


@router.get("/api/paj/{paj_norm}/notas", response_class=JSONResponse)
async def api_notas_ler(paj_norm: PajNorm):
    """Le NOTAS.md do PAJ (string vazia se nao existe)."""
    return {"paj_norm": paj_norm, "texto": ler_notas(paj_norm)}


@router.post("/api/paj/{paj_norm}/notas", response_class=JSONResponse)
async def api_notas_salvar(paj_norm: PajNorm, payload: dict = Body(...)):
    """Salva NOTAS.md do PAJ. Body: {"texto": "..."}."""
    texto = payload.get("texto", "") if isinstance(payload, dict) else ""
    ok = salvar_notas(paj_norm, texto)
    if not ok:
        return JSONResponse({"ok": False, "erro": "PAJ inválido"}, status_code=400)
    return {"ok": True}
