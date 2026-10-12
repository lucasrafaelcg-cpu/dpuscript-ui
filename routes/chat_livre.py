"""Chat livre — rotas HTTP + WebSocket. SEMPRE vinculado a PAJ.

UI:
  GET  /chat-livre?conv=<id>                       — pagina do chat

API REST:
  GET    /api/chat-livre/paj/{paj_norm}/conversas  — listar conversas do PAJ
  POST   /api/chat-livre/paj/{paj_norm}/conversas  — criar conversa do PAJ
  GET    /api/chat-livre/conversas/{conv_id}       — ler (varredura por id)
  PATCH  /api/chat-livre/conversas/{conv_id}       — renomear / mudar skill
  DELETE /api/chat-livre/conversas/{conv_id}       — apagar
  GET    /api/chat-livre/stats                     — pool de sessoes

Streaming:
  WS     /ws/chat-livre/{conv_id}                  — stream-json com Claude
"""

from __future__ import annotations

import asyncio
import queue as _queue

from fastapi import APIRouter, Body, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from services import chat_livre_service as chat_livre


router = APIRouter()


# ---------------------------------------------------------------------------
# Pagina
# ---------------------------------------------------------------------------

@router.get("/chat-livre", response_class=HTMLResponse)
async def chat_livre_page(request: Request, conv: str = ""):
    """Renderiza o chat. Espera ?conv=<id> apontando para conversa existente.

    Sem `conv` valido, mostra estado vazio com instrucao para abrir via PAJ.
    """
    template = request.app.state.jinja.get_template("chat_livre.html")
    conversa = chat_livre.ler_conversa(conv) if conv else None
    contexto = {
        "request": request,
        "conv_inicial": conversa["id"] if conversa else "",
        "paj_inicial": conversa.get("paj_norm", "") if conversa else "",
        "titulo_inicial": conversa.get("titulo", "") if conversa else "",
    }
    return HTMLResponse(template.render(**contexto))


# ---------------------------------------------------------------------------
# API por PAJ
# ---------------------------------------------------------------------------

@router.get("/api/chat-livre/paj/{paj_norm}/conversas")
async def api_listar_paj(paj_norm: str):
    return {"paj_norm": paj_norm, "conversas": chat_livre.listar_conversas_paj(paj_norm)}


@router.post("/api/chat-livre/paj/{paj_norm}/conversas")
async def api_criar_paj(paj_norm: str, payload: dict = Body(default={})):
    if not isinstance(payload, dict):
        payload = {}
    titulo = (payload.get("titulo") or "").strip()
    skill = (payload.get("skill_slug") or "").strip() or None
    conversa = chat_livre.criar_conversa(paj_norm, titulo=titulo, skill_slug=skill)
    if conversa is None:
        return JSONResponse(
            {"erro": "PAJ nao encontrado ou identificador invalido"},
            status_code=400,
        )
    return conversa


# ---------------------------------------------------------------------------
# API por id de conversa (sem precisar saber o PAJ)
# ---------------------------------------------------------------------------

@router.get("/api/chat-livre/conversas/{conv_id}")
async def api_ler(conv_id: str):
    conversa = chat_livre.ler_conversa(conv_id)
    if not conversa:
        return JSONResponse({"erro": "conversa nao encontrada"}, status_code=404)
    return conversa


@router.patch("/api/chat-livre/conversas/{conv_id}")
async def api_atualizar(conv_id: str, payload: dict = Body(...)):
    """Atualiza titulo e/ou skill_slug.

    Convencao: chave AUSENTE no payload = nao mexe; chave PRESENTE = atualiza.
    Em skill_slug, string vazia significa "remover skill".
    """
    if not isinstance(payload, dict):
        return JSONResponse({"erro": "payload invalido"}, status_code=400)
    titulo = payload.get("titulo")
    skill_slug = payload.get("skill_slug")
    conversa = chat_livre.atualizar_metadata(
        conv_id, titulo=titulo, skill_slug=skill_slug
    )
    if not conversa:
        return JSONResponse({"erro": "conversa nao encontrada"}, status_code=404)
    return conversa


@router.delete("/api/chat-livre/conversas/{conv_id}")
async def api_remover(conv_id: str):
    ok = chat_livre.remover_conversa(conv_id)
    return {"ok": ok}


@router.get("/api/chat-livre/stats")
async def api_stats():
    return chat_livre.get_stats()


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

# Um socket por conversa. Recarregar a pagina (ou clicar na conversa na lista)
# abre um socket novo sem que o antigo tenha morrido; com dois handlers vivos,
# os DOIS drenavam a MESMA `output_queue` e os eventos da resposta se dividiam
# entre eles — o navegador, que escuta so' um, perdia parte (ou tudo) da
# resposta. Aqui o socket novo assume e o antigo se retira.
_ws_ativo: dict[str, object] = {}


@router.websocket("/ws/chat-livre/{conv_id}")
async def chat_livre_ws(websocket: WebSocket, conv_id: str):
    await websocket.accept()
    _ws_ativo[conv_id] = websocket

    def sou_o_ativo() -> bool:
        return _ws_ativo.get(conv_id) is websocket

    sess = chat_livre.get_or_create_session(conv_id)
    if sess is None:
        await websocket.send_json({"type": "error", "text": "Conversa nao encontrada."})
        await websocket.send_json({"type": "done"})
        await websocket.close()
        return

    if not sess.is_alive():
        sess.start()

    try:
        async def drenar_output():
            while True:
                # Um handler superado para de consumir a fila: senao roubaria
                # eventos do socket que o navegador esta realmente escutando.
                if not sou_o_ativo():
                    return
                try:
                    event = sess.output_queue.get_nowait()
                except _queue.Empty:
                    await asyncio.sleep(0.05)
                    continue
                try:
                    await websocket.send_json(event)
                except Exception:
                    return  # socket morreu; quem fecha o handler e' o loop de leitura
                # NAO encerrar no 'done'. Ele marca o fim de UM turno (ou a morte
                # do subprocesso do Claude), nao o fim da conversa. Encerrar aqui
                # derrubava o socket depois da primeira resposta: o front marcava
                # `conectado = false` e a CAIXA DE TEXTO ficava desabilitada — o
                # Defensor nao conseguia mais escrever ate abrir outra conversa.
                # A sessao morta e' ressuscitada no proximo envio
                # (`ChatLivreSession.send_message`).

        out_task = asyncio.create_task(drenar_output())

        while True:
            if not sou_o_ativo():
                break
            try:
                data = await asyncio.wait_for(websocket.receive_json(), timeout=0.1)
                tipo = data.get("type")
                if tipo == "message":
                    texto = (data.get("text") or "").strip()
                    if texto:
                        sess.send_message(texto)
                elif tipo == "stop":
                    chat_livre.stop_session(conv_id)
                    break
            except TimeoutError:
                # Nada chegou do navegador nesses 100ms — normal. NAO encerrar
                # aqui por causa da drenagem: o socket precisa continuar aberto
                # entre turnos, senao a caixa de texto do Defensor e' desabilitada.
                continue
            except WebSocketDisconnect:
                break

        out_task.cancel()

    except WebSocketDisconnect:
        pass
    finally:
        # Libera o registro so' se este ainda for o socket ativo — se outro ja'
        # assumiu, apagar aqui deixaria a conversa sem handler ativo.
        if _ws_ativo.get(conv_id) is websocket:
            _ws_ativo.pop(conv_id, None)
