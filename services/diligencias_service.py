"""Fila de Diligências — o que foi produzido no painel e ainda não foi ao SIS.

Problema que esta fila resolve: cada gravação no SISDPU abre uma sessão
Playwright que faz login, e o SISDPU derruba a sessão que o Defensor tem no
navegador. Anexar seis despachos ao longo da tarde custa seis quedas de login.
Aqui os produtos se acumulam, o Defensor marca o que já revisou e manda tudo de
uma vez: **um login só**.

Onde fica: `PAJS_DIR/.diligencias.json`, deliberadamente FORA do
`metadata.json` de cada PAJ — a sincronização reescreve o metadata e apagaria a
fila (mesma razão de `concluidos_service`).

Cada item guarda o par PAJ ↔ arquivo fixado na origem. O arquivo precisa morar
dentro da pasta daquele PAJ, e isso é conferido de novo na hora de enviar: é a
primeira das travas que impedem o documento de cair no PAJ errado.

Estados: `pendente` → `enviando` → `anexado` | `erro`. Item `anexado` é imutável
(movimentação gravada não volta atrás); para refazer, o Defensor remove e
registra de novo, com o clique dele no meio.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import re
import threading
import uuid
from pathlib import Path

_log = logging.getLogger(__name__)
_LOCK = threading.Lock()

ARQUIVO = ".diligencias.json"

TIPO_DESPACHO = "despacho"
TIPO_PECA = "peca"

STATUS_PENDENTE = "pendente"
STATUS_ENVIANDO = "enviando"
STATUS_ANEXADO = "anexado"
STATUS_ERRO = "erro"


def _caminho() -> Path:
    from config import PAJS_DIR

    return PAJS_DIR / ARQUIVO


def _ler() -> dict:
    p = _caminho()
    if not p.exists():
        return {"itens": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not isinstance(d.get("itens"), list):
            return {"itens": []}
        return d
    except Exception as e:
        _log.warning("fila de diligencias ilegivel (%s); comecando vazia", e)
        return {"itens": []}


def _gravar(dados: dict) -> None:
    p = _caminho()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(p)


def _agora() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _hash(arquivo: Path) -> str:
    try:
        return hashlib.sha256(arquivo.read_bytes()).hexdigest()[:16]
    except Exception:
        return ""


def resolver_arquivo(paj_norm: str, rel: str) -> Path:
    """Caminho absoluto do arquivo, garantido DENTRO da pasta do PAJ.

    Levanta ValueError se o caminho escapar — `..`, caminho absoluto, link
    para fora. Esta é a trava que torna impossível um item da fila apontar
    para documento de outro assistido.
    """
    from config import PAJS_DIR

    raiz = (PAJS_DIR / paj_norm).resolve()
    alvo = (raiz / str(rel)).resolve()
    try:
        alvo.relative_to(raiz)
    except ValueError:
        raise ValueError(f"arquivo fora da pasta do PAJ: {rel}")
    return alvo


def listar(incluir_anexados: bool = True) -> list[dict]:
    """Fila inteira, mais recente primeiro, com o estado atual do arquivo."""
    itens = _ler()["itens"]
    saida = []
    for it in itens:
        if not incluir_anexados and it.get("status") == STATUS_ANEXADO:
            continue
        it = dict(it)
        try:
            alvo = resolver_arquivo(it["paj_norm"], it["arquivo"])
            it["existe"] = alvo.is_file()
            # Editado depois de entrar na fila? Não bloqueia (editar antes de
            # anexar é o fluxo normal), mas fica à vista e o hash do que FOI
            # enviado é regravado no envio.
            it["editado"] = bool(
                it["existe"] and it.get("hash") and _hash(alvo) != it["hash"])
        except Exception:
            it["existe"] = False
            it["editado"] = False
        saida.append(it)
    saida.sort(key=lambda i: i.get("criado_em") or "", reverse=True)
    return saida


def registrar(paj_norm: str, arquivo: str, tipo: str,
              titulo: str = "") -> dict:
    """Põe um produto na fila. Idempotente por (paj_norm, arquivo).

    Chamado na ORIGEM — quando a análise cria o despacho e quando o docgen
    grava a peça — e também pelo botão da tela do PAJ.
    """
    from config import PAJS_DIR

    try:
        alvo = resolver_arquivo(paj_norm, arquivo)
    except ValueError as e:
        return {"ok": False, "erro": str(e)}
    if not alvo.is_file():
        return {"ok": False, "erro": f"arquivo inexistente: {arquivo}"}

    meta = {}
    try:
        meta = json.loads(
            (PAJS_DIR / paj_norm / "metadata.json").read_text(encoding="utf-8"))
    except Exception:
        pass

    with _LOCK:
        dados = _ler()
        for it in dados["itens"]:
            if it["paj_norm"] == paj_norm and it["arquivo"] == arquivo:
                return {"ok": True, "id": it["id"], "motivo": "ja estava na fila"}

        item = {
            "id": uuid.uuid4().hex[:12],
            "paj_norm": paj_norm,
            "paj": meta.get("paj") or paj_norm,
            "assistido": meta.get("assistido_caixa") or "",
            "tipo": tipo if tipo in (TIPO_DESPACHO, TIPO_PECA) else TIPO_PECA,
            "arquivo": arquivo,
            "titulo": titulo or Path(arquivo).stem,
            "hash": _hash(alvo),
            "criado_em": _agora(),
            "marcado": False,
            "status": STATUS_PENDENTE,
            "anexado_em": "",
            "erro": "",
            "mostrar_na_internet": False,
        }
        dados["itens"].append(item)
        _gravar(dados)
    _log.info("diligencia registrada: %s / %s (%s)", paj_norm, arquivo, tipo)
    return {"ok": True, "id": item["id"], "motivo": "registrada"}


def _mexer(item_id: str, mudanca) -> dict:
    with _LOCK:
        dados = _ler()
        for it in dados["itens"]:
            if it["id"] == item_id:
                erro = mudanca(it)
                if erro:
                    return {"ok": False, "erro": erro}
                _gravar(dados)
                return {"ok": True, "item": dict(it)}
    return {"ok": False, "erro": "item inexistente na fila"}


def marcar(item_id: str, marcado: bool) -> dict:
    def _f(it):
        if it["status"] == STATUS_ANEXADO:
            return "item já anexado no SISDPU"
        it["marcado"] = bool(marcado)
        return None
    return _mexer(item_id, _f)


def marcar_todos(marcado: bool) -> int:
    with _LOCK:
        dados = _ler()
        n = 0
        for it in dados["itens"]:
            if it["status"] in (STATUS_PENDENTE, STATUS_ERRO):
                it["marcado"] = bool(marcado)
                n += 1
        _gravar(dados)
    return n


def definir_visibilidade(item_id: str, visivel: bool) -> dict:
    """Descrição da movimentação visível ao assistido na internet.

    Padrão é NÃO. O despacho administrativo é documento de trabalho interno;
    publicá-lo para o assistido é ato que depende de decisão a cada caso.
    """
    def _f(it):
        if it["status"] == STATUS_ANEXADO:
            return "item já anexado no SISDPU"
        it["mostrar_na_internet"] = bool(visivel)
        return None
    return _mexer(item_id, _f)


def remover(item_id: str) -> dict:
    """Tira da fila. Não apaga arquivo nem desfaz movimentação gravada."""
    with _LOCK:
        dados = _ler()
        antes = len(dados["itens"])
        dados["itens"] = [i for i in dados["itens"] if i["id"] != item_id]
        if len(dados["itens"]) == antes:
            return {"ok": False, "erro": "item inexistente na fila"}
        _gravar(dados)
    return {"ok": True}


def limpar_anexados() -> int:
    with _LOCK:
        dados = _ler()
        antes = len(dados["itens"])
        dados["itens"] = [i for i in dados["itens"]
                          if i.get("status") != STATUS_ANEXADO]
        _gravar(dados)
    return antes - len(dados["itens"])


def atualizar_status(item_id: str, status: str, erro: str = "",
                     hash_enviado: str = "", mov: str = "") -> None:
    with _LOCK:
        dados = _ler()
        for it in dados["itens"]:
            if it["id"] == item_id:
                it["status"] = status
                it["erro"] = erro
                if status == STATUS_ANEXADO:
                    it["anexado_em"] = _agora()
                    it["marcado"] = False
                    if hash_enviado:
                        it["hash_enviado"] = hash_enviado
                    if mov:
                        it["movimentacao"] = mov
                _gravar(dados)
                return


def pendentes_marcados() -> list[dict]:
    """O que o lote vai enviar: marcado, não anexado e com arquivo no lugar."""
    saida = []
    for it in listar():
        if not it.get("marcado"):
            continue
        if it.get("status") == STATUS_ANEXADO:
            continue
        if not it.get("existe"):
            continue
        saida.append(it)
    # Agrupa por PAJ para o lote não ficar pulando de PAJ em PAJ no SISDPU.
    saida.sort(key=lambda i: (i["paj_norm"], i.get("criado_em") or ""))
    return saida


_RE_PAJ_NORM = re.compile(r"PAJ-\d{4}-\d{3}-\d+$")


def paj_norm_valido(paj_norm: str) -> bool:
    return bool(isinstance(paj_norm, str) and _RE_PAJ_NORM.fullmatch(paj_norm))
