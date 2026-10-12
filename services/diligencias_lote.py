"""Envio em LOTE das diligências marcadas ao SISDPU — um login só.

Roda em segundo plano porque cada item leva cerca de um minuto (abre o PAJ,
preenche, grava e relê para confirmar). A tela acompanha por `estado()`.

Travas, em ordem de aplicação. As três primeiras são deste módulo; as demais
já existem em `ingestao/sisdpu_movimentacao` e valem para todo envio:

  1. só item MARCADO, com status pendente/erro e arquivo existente — item já
     anexado nunca é reenviado, porque movimentação gravada não volta atrás;
  2. o arquivo é resolvido DENTRO da pasta do PAJ (`resolver_arquivo`): o par
     PAJ ↔ arquivo foi fixado quando o produto nasceu e não se afrouxa aqui;
  3. despacho tem que ser arquivo de texto e peça tem que ter corpo — fase e
     tipo de arquivo saem do tipo do item, não de escolha no clique;
  4. o cabeçalho "Movimentação do PAJ" na tela tem que ser o PAJ pretendido;
  5. o NOME DO ASSISTIDO na tela tem que bater com o que a fila registrou
     (`assistido_esperado`);
  6. o anexo tem que aparecer em `tabelaArquivos` depois de "Anexar";
  7. depois de gravar, as movimentações são relidas para confirmar.

Falha de TRAVA (`MovimentacaoAbortada`) não grava nada: marca o item como erro
e o lote segue para o próximo. Falha TÉCNICA (sessão caída, seletor sumido,
rede) deixa o estado do SISDPU incerto, então o lote PARA ali — insistir às
cegas é como se duplica movimentação.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from pathlib import Path

from services import diligencias_service as ds

_log = logging.getLogger(__name__)

_EXT_TEXTO = (".txt", ".md")

# Pistas de que a sessao do painel foi bloqueada por login em outra estacao.
# A primeira vem da trava de `sisdpu_movimentacao`; a segunda e' o id do modal
# do SIS, que aparece no log do Playwright quando o clique e' interceptado.
_PISTAS_SESSAO = ("sessao do SISDPU bloqueada", "confirmDialogLogin")


def _sessao_bloqueada(msg: str) -> bool:
    return any(p in (msg or "") for p in _PISTAS_SESSAO)

_estado: dict = {
    "rodando": False,
    "iniciado_em": "",
    "terminado_em": "",
    "total": 0,
    "feitos": 0,
    "atual": "",
    "parado_por": "",
    "ensaio": False,
    "parando": False,
    "resultados": [],
}
_tarefa: asyncio.Task | None = None


def estado() -> dict:
    return dict(_estado, resultados=list(_estado["resultados"]))


def _ler_texto(alvo: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return alvo.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return alvo.read_text(encoding="utf-8", errors="replace")


def _preparar(item: dict) -> dict:
    """Monta os argumentos da movimentação a partir do tipo do item.

    Levanta ValueError quando o item não pode ser enviado como o tipo que diz
    ser — trava 3.
    """
    from ingestao import sisdpu_movimentacao as mv
    from services.despacho_firac import texto_para_html

    alvo = ds.resolver_arquivo(item["paj_norm"], item["arquivo"])

    if item["tipo"] == ds.TIPO_DESPACHO:
        if alvo.suffix.lower() not in _EXT_TEXTO:
            raise ValueError(
                f"despacho tem que ser arquivo de texto, veio {alvo.suffix}")
        texto = _ler_texto(alvo).strip()
        if len(texto) < 40:
            raise ValueError("despacho vazio ou curto demais")
        # Decisão do Defensor: o despacho vai DIGITADO na descrição da
        # movimentação, como se despacha no DPU Digital — sem anexo.
        return {
            "fase": mv.FASE_DESPACHO,
            "descricao_html": texto_para_html(texto),
            "anexos": [],
            "tipo_arquivo": mv.TIPO_ARQUIVO_DESPACHOS,
            "resumo": f"despacho na descrição ({len(texto)} caracteres)",
        }

    if alvo.stat().st_size == 0:
        raise ValueError("arquivo da peça está vazio")
    from html import escape

    return {
        "fase": mv.FASE_PETICAO_CONTEUDO_JURIDICO,
        "descricao_html": "<p>" + escape(item.get("titulo") or alvo.stem) + "</p>",
        "anexos": [str(alvo)],
        "tipo_arquivo": mv.TIPO_ARQUIVO_PETICOES,
        "resumo": f"peça anexada ({alvo.name})",
    }


async def _enviar_um(item: dict, ensaio: bool = False) -> dict:
    """Envia um item. Devolve {ok, gravado, erro, tecnico}.

    Em `ensaio`, preenche a tela inteira (fase, descricao, anexo), tira o
    screenshot e PARA antes de submeter — e' o dry-run de
    `inserir_movimentacao`. Serve para conferir a fase e o texto sem gravar
    movimentacao que nao volta atras.
    """
    import re

    from ingestao import sisdpu_movimentacao as mv

    m = re.match(r"PAJ-(\d{4})-(\d{3})-(\d+)$", item["paj_norm"])
    if not m:
        return {"ok": False, "tecnico": False,
                "erro": f"paj_norm inválido: {item['paj_norm']}"}
    ano, unidade, numero = m.group(1), m.group(2), m.group(3)

    try:
        args = _preparar(item)
    except (ValueError, OSError) as e:
        return {"ok": False, "tecnico": False, "erro": str(e)}

    try:
        res = await mv.inserir_movimentacao(
            numero=numero,
            ano=ano,
            unidade=unidade,
            fase=args["fase"],
            descricao_html=args["descricao_html"],
            anexos=args["anexos"],
            tipo_arquivo=args["tipo_arquivo"],
            mostrar_na_internet=bool(item.get("mostrar_na_internet")),
            assistido_esperado=item.get("assistido") or "",
            confirmar=not ensaio,
        )
    except mv.MovimentacaoAbortada as e:
        # Trava reprovou: NADA foi gravado. Erro do item, não do lote — salvo
        # quando o motivo é a sessão bloqueada, que é estado GLOBAL: insistir
        # nos próximos itens só repetiria a mesma falha.
        msg = str(e)
        return {"ok": False, "tecnico": _sessao_bloqueada(msg), "erro": msg}
    except Exception as e:
        # Estado incerto no SISDPU: o lote para.
        msg = f"{type(e).__name__}: {e}"
        if _sessao_bloqueada(msg):
            msg = (
                "o SISDPU bloqueou a sessão do painel porque houve login em "
                "outra estação (seu navegador). O modal de desbloqueio cobre "
                "a tela e nenhum clique chega. Saia do SISDPU no navegador e "
                "mande de novo."
            )
        return {"ok": False, "tecnico": True, "erro": msg}

    if ensaio:
        return {"ok": True, "tecnico": False, "erro": "", "resultado": res,
                "resumo": f"ENSAIO — fase {res.get('fase')!r}, nada gravado "
                          f"(screenshot: {res.get('screenshot')})"}

    if not res.get("gravado"):
        # Submeteu e a releitura não confirmou. Não repetir: pode ter gravado.
        return {"ok": False, "tecnico": True,
                "erro": res.get("aviso") or "gravação não confirmada na releitura",
                "resultado": res}

    return {"ok": True, "tecnico": False, "erro": "", "resultado": res,
            "resumo": args["resumo"]}


async def _rodar(ids: list[str] | None, ensaio: bool = False) -> None:
    fila = ds.pendentes_marcados()
    if ids:
        escolhidos = set(ids)
        fila = [i for i in fila if i["id"] in escolhidos]

    _estado.update({
        "rodando": True,
        "iniciado_em": datetime.datetime.now().isoformat(timespec="seconds"),
        "terminado_em": "",
        "total": len(fila),
        "feitos": 0,
        "atual": "",
        "parado_por": "",
        "ensaio": ensaio,
        "parando": False,
        "resultados": [],
    })

    try:
        for item in fila:
            # Parada pedida pelo Defensor. A checagem e' ENTRE itens, nunca no
            # meio de um: interromper uma movimentacao a meio caminho deixaria
            # o SISDPU em estado que ninguem sabe ler depois — pode ter
            # gravado, pode nao ter. Quem ja' comecou, termina.
            if _estado["parando"]:
                _estado["parado_por"] = (
                    f"interrompido por voce apos {_estado['feitos']} de "
                    f"{_estado['total']} — o que faltou segue na fila")
                _log.warning("lote interrompido pelo Defensor")
                break

            rotulo = f"{item['paj']} — {item['titulo']}"
            _estado["atual"] = rotulo
            ds.atualizar_status(item["id"], ds.STATUS_ENVIANDO)

            r = await _enviar_um(item, ensaio=ensaio)

            if r["ok"] and ensaio:
                ds.atualizar_status(item["id"], ds.STATUS_PENDENTE)
                _estado["resultados"].append(
                    {"id": item["id"], "paj": item["paj"], "titulo": item["titulo"],
                     "ok": True, "detalhe": r.get("resumo", "")})
            elif r["ok"]:
                res = r.get("resultado") or {}
                ds.atualizar_status(
                    item["id"], ds.STATUS_ANEXADO,
                    hash_enviado=ds._hash(
                        ds.resolver_arquivo(item["paj_norm"], item["arquivo"])),
                    mov=str(res.get("movs_depois") or res.get("fase") or ""))
                _estado["resultados"].append(
                    {"id": item["id"], "paj": item["paj"], "titulo": item["titulo"],
                     "ok": True, "detalhe": r.get("resumo", "")})
                _log.info("lote: gravado %s (%s)", item["paj"], item["arquivo"])
            else:
                ds.atualizar_status(item["id"], ds.STATUS_ERRO, erro=r["erro"])
                _estado["resultados"].append(
                    {"id": item["id"], "paj": item["paj"], "titulo": item["titulo"],
                     "ok": False, "detalhe": r["erro"]})
                _log.warning("lote: falhou %s — %s", item["paj"], r["erro"])
                if r["tecnico"]:
                    _estado["parado_por"] = (
                        f"falha técnica em {item['paj']}: {r['erro']} — "
                        "o lote parou aqui; confira esse PAJ no SISDPU antes "
                        "de mandar de novo")
                    break

            _estado["feitos"] += 1
            await asyncio.sleep(1)
    finally:
        _estado["rodando"] = False
        _estado["parando"] = False
        _estado["atual"] = ""
        _estado["terminado_em"] = datetime.datetime.now().isoformat(timespec="seconds")


def parar() -> dict:
    """Pede a parada do lote. O item em andamento termina antes.

    Nao cancela o que ja' foi gravado: movimentacao no SISDPU nao volta
    atras. O que ainda nao saiu continua marcado na fila.
    """
    if not _estado["rodando"]:
        return {"ok": False, "erro": "nao ha envio em andamento"}
    _estado["parando"] = True
    return {"ok": True, "atual": _estado["atual"],
            "feitos": _estado["feitos"], "total": _estado["total"]}


def iniciar(ids: list[str] | None = None, ensaio: bool = False) -> dict:
    """Dispara o lote em segundo plano. Um por vez.

    `ensaio=True` percorre o mesmo caminho sem submeter nada.
    """
    global _tarefa

    if _estado["rodando"]:
        return {"ok": False, "erro": "já existe um envio em andamento"}

    fila = ds.pendentes_marcados()
    if ids:
        escolhidos = set(ids)
        fila = [i for i in fila if i["id"] in escolhidos]
    if not fila:
        return {"ok": False, "erro": "nada marcado para enviar"}

    _tarefa = asyncio.create_task(_rodar(ids, ensaio=ensaio))
    return {"ok": True, "total": len(fila), "ensaio": ensaio,
            "pajs": sorted({i["paj"] for i in fila})}
