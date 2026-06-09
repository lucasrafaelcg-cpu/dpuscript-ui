"""Ponte entre o SIS e o MCP do PJe TRF3 (pacote canônico em C:\\DPU\\pje-mcp-trf3).

Expõe funções de alto nível para a UI/rotas do SIS:
- `numero_trf3_do_paj(paj_norm)` — número do processo TRF3 1g vinculado ao PAJ.
- `situacao_processual(paj_norm, emit)` — últimas movimentações + intimação/prazo.
- `puxar_pecas(paj_norm, emit)` — baixa peças do período recente, roda OCR e
  grava um digest `_situacao_pje.md` na pasta do PAJ (material para a análise).

IMPORTANTE: as funções do MCP usam `sync_playwright` e abrem o Chrome REAL
(o Akamai do TRF3 bloqueia headless). Por isso ESTAS funções são SÍNCRONAS e
devem ser executadas em thread separada pelas rotas (`asyncio.to_thread`),
nunca no loop async direto. O parâmetro `emit(linha)` é um callback de log
(thread-safe, fornecido pela rota) para feedback em tempo real (SSE).

Nada de credenciais aqui: o MCP lê CPF/senha/seed do Cofre do Windows.
"""

from __future__ import annotations

import datetime as _dt
import importlib
import json
import os
import re
import sys
import threading
from pathlib import Path
from collections.abc import Callable

from config import PAJS_DIR, TIMEOUT_OCR_POR_PAGINA_SEG

# Diretório do pacote canônico do MCP (ajustável por env).
PJE_MCP_DIR = Path(os.getenv("PJE_MCP_DIR", r"C:\DPU\pje-mcp-trf3"))

_mcp_mod = None

# O MCP abre o Chrome REAL com sessão persistente única — duas operações
# simultâneas disputariam a mesma janela/perfil. O lock garante uma por vez;
# a segunda recebe erro amigável em vez de corromper a sessão.
_PJE_LOCK = threading.Lock()
_ERRO_OCUPADO = (
    "Já existe uma operação do PJe em andamento (o Chrome só comporta uma por "
    "vez). Aguarde a conclusão e tente novamente."
)


def _importar_mcp():
    """Importa (lazy, cacheado) o módulo server.py do MCP canônico."""
    global _mcp_mod
    if _mcp_mod is not None:
        return _mcp_mod
    if not (PJE_MCP_DIR / "server.py").exists():
        raise RuntimeError(
            f"MCP do PJe não encontrado em {PJE_MCP_DIR}. "
            f"Defina a variável de ambiente PJE_MCP_DIR."
        )
    if str(PJE_MCP_DIR) not in sys.path:
        sys.path.insert(0, str(PJE_MCP_DIR))
    _mcp_mod = importlib.import_module("server")
    return _mcp_mod


def disponivel() -> bool:
    """True se o pacote do MCP está acessível (não valida credenciais)."""
    return (PJE_MCP_DIR / "server.py").exists()


# --- Helpers -----------------------------------------------------------------

def _metadata(paj_norm: str) -> dict:
    p = PAJS_DIR / paj_norm / "metadata.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def eh_trf3_1g(processo: str | None) -> bool:
    """True se o número CNJ é da Justiça Federal (J=4) do TRF3 (TR=03).

    Regra ÚNICA de detecção — usada aqui, no sincronizador e nos templates
    (filtro Jinja registrado no app.py). Aceita número formatado ou só dígitos.
    """
    d = re.sub(r"\D", "", processo or "")
    return len(d) == 20 and d[13:14] == "4" and d[14:16] == "03"


def numero_trf3_do_paj(paj_norm: str) -> str | None:
    """Número do processo judicial vinculado ao PAJ, se for TRF3 1º grau.

    Retorna o número (como gravado no metadata) ou None se não houver processo
    ou se não for TRF3 1g (justiça=4, tribunal=03).
    """
    proc = (_metadata(paj_norm).get("processo_judicial") or "").strip()
    return proc if eh_trf3_1g(proc) else None


def _intervalo_recente(paj_norm: str, dias_antes: int = 5, janela_padrao: int = 45) -> tuple[str, str]:
    """(data_inicio, data_fim) em 'DD/MM/AAAA'. Usa a data da intimação detectada
    (flag `pje_intimacao_pendente` ou último prazo), menos `dias_antes`; se não
    houver, usa os últimos `janela_padrao` dias."""
    meta = _metadata(paj_norm)
    base = None
    flag = meta.get("pje_intimacao_pendente") or {}
    data_ref = flag.get("data") or ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", str(data_ref))
    if m:
        try:
            base = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            base = None
    hoje = _dt.date.today()
    if base:
        inicio = base - _dt.timedelta(days=dias_antes)
    else:
        inicio = hoje - _dt.timedelta(days=janela_padrao)
    # Data de intimação malformada/futura no metadata não pode gerar um
    # intervalo invertido (inicio > fim) — o PJe rejeitaria a busca.
    if inicio > hoje:
        inicio = hoje - _dt.timedelta(days=janela_padrao)
    return inicio.strftime("%d/%m/%Y"), hoje.strftime("%d/%m/%Y")


def _extrair_expedientes(html: str) -> list[str]:
    """Extrai do HTML da aba Expedientes as linhas relevantes (intimação, prazo,
    ciência, data-limite)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    txt = BeautifulSoup(html, "html.parser").get_text("\n")
    linhas = [ln.strip() for ln in txt.split("\n") if ln.strip()]
    rgx = re.compile(
        r"intima|ci[êe]ncia|prazo|manifesta|despacho|decis|senten|aberto|fechado|"
        r"\d{2}/\d{2}/\d{4}", re.I)
    vistos: list[str] = []
    for ln in linhas:
        if rgx.search(ln) and ln not in vistos:
            vistos.append(ln[:200])
    return vistos[:40]


# --- Operações (SÍNCRONAS — rodar em thread via asyncio.to_thread) -----------

def _login_e_resolver(numero: str, emit: Callable[[str], None]) -> dict:
    """Autentica no PJe e resolve o número CNJ em id interno.

    Retorna {"mcp": mod, "idp": str} em sucesso, ou {"erro": ..., [
    "sem_habilitacao": bool]} em falha — caller repassa direto à UI.
    """
    mcp = _importar_mcp()
    emit("Autenticando no PJe (TOTP)...")
    login = mcp.login_automatico()
    if not login.get("sucesso"):
        return {"erro": f"Falha no login: {login.get('erro') or login.get('mensagem')}"}

    emit(f"Resolvendo processo {numero} ...")
    res = mcp.consultar_processo_numero(numero)
    if not res.get("encontrado"):
        return {"erro": res.get("erro", "processo não encontrado"),
                "sem_habilitacao": bool(res.get("sem_habilitacao"))}
    return {"mcp": mcp, "idp": res["id_processo"]}


def _expedientes_do_processo(mcp, idp: str, numero: str,
                             emit: Callable[[str], None]) -> list[str]:
    """Linhas relevantes da aba Expedientes (intimação/prazo/ciência).

    Usa `_abrir_aba_expedientes` do MCP (interno — pode sumir numa atualização
    do pacote); qualquer falha vira aviso no log, nunca quebra a operação.
    """
    abrir = getattr(mcp, "_abrir_aba_expedientes", None)
    if abrir is None:
        emit("[aviso] expedientes: função indisponível nesta versão do MCP")
        return []
    try:
        html, _vs = abrir(idp, numero)
        return _extrair_expedientes(html)
    except Exception as e:
        emit(f"[aviso] expedientes: {type(e).__name__}: {e}")
        return []


def _limpar_flag_intimacao(paj_norm: str) -> None:
    """Após puxar as peças, a intimação deixa de ser 'pendente': arquiva o flag
    em `pje_ultima_intimacao` e registra quando as peças foram puxadas — o
    badge ⚠ da UI some no próximo render."""
    pasta = PAJS_DIR / paj_norm
    meta = _metadata(paj_norm)
    if not meta:
        return
    flag = meta.pop("pje_intimacao_pendente", None)
    if flag:
        meta["pje_ultima_intimacao"] = flag
    meta["pje_pecas_puxadas_em"] = _dt.datetime.now().isoformat(timespec="seconds")
    (pasta / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def situacao_processual(paj_norm: str, emit: Callable[[str], None]) -> dict:
    """Login + resolve + lê expedientes/movimentações. Retorna dict resumo.

    Não baixa peças; é uma consulta leve para o botão "Situação Processual".
    """
    numero = numero_trf3_do_paj(paj_norm)
    if not numero:
        return {"ok": False, "erro": "PAJ sem processo do TRF3 1º grau vinculado."}
    if not _PJE_LOCK.acquire(blocking=False):
        return {"ok": False, "erro": _ERRO_OCUPADO}
    try:
        return _situacao_processual_locked(paj_norm, numero, emit)
    finally:
        _PJE_LOCK.release()


def _situacao_processual_locked(paj_norm: str, numero: str,
                                emit: Callable[[str], None]) -> dict:
    sessao = _login_e_resolver(numero, emit)
    if "erro" in sessao:
        return {"ok": False, **sessao}
    mcp, idp = sessao["mcp"], sessao["idp"]
    emit(f"Processo aberto (id {idp}). Lendo expedientes e movimentações...")

    expedientes = _expedientes_do_processo(mcp, idp, numero, emit)

    movimentos: list[dict] = []
    documentos: list[dict] = []
    try:
        proc = mcp.ler_processo(id_processo=idp, numero=numero)
        movimentos = (proc.get("movimentos") or [])[:15]
        documentos = (proc.get("documentos") or [])[-15:]
    except Exception as e:
        emit(f"[aviso] timeline: {type(e).__name__}: {e}")

    emit("Consulta concluída.")
    return {
        "ok": True, "numero": numero, "id_processo": idp,
        "expedientes": expedientes, "movimentos": movimentos, "documentos": documentos,
    }


def puxar_pecas(paj_norm: str, emit: Callable[[str], None]) -> dict:
    """Login + resolve + baixa peças do período recente + OCR + grava digest.

    Salva o PDF em PAJS_DIR/<paj>/pecas_pje/, o texto OCR (.txt) ao lado e um
    `_situacao_pje.md` na pasta do PAJ (consumido pelo prompt_builder).
    """
    numero = numero_trf3_do_paj(paj_norm)
    if not numero:
        return {"ok": False, "erro": "PAJ sem processo do TRF3 1º grau vinculado."}
    if not _PJE_LOCK.acquire(blocking=False):
        return {"ok": False, "erro": _ERRO_OCUPADO}
    try:
        return _puxar_pecas_locked(paj_norm, numero, emit)
    finally:
        _PJE_LOCK.release()


def _puxar_pecas_locked(paj_norm: str, numero: str,
                        emit: Callable[[str], None]) -> dict:
    sessao = _login_e_resolver(numero, emit)
    if "erro" in sessao:
        return {"ok": False, **sessao}
    mcp, idp = sessao["mcp"], sessao["idp"]

    pasta = PAJS_DIR / paj_norm
    destino_dir = pasta / "pecas_pje"
    destino_dir.mkdir(parents=True, exist_ok=True)
    ini, fim = _intervalo_recente(paj_norm)
    pdf = destino_dir / f"autos_{ini.replace('/', '-')}_a_{fim.replace('/', '-')}.pdf"

    emit(f"Abrindo o Chrome para baixar as peças ({ini} a {fim})...")
    dl = mcp.baixar_processo_completo(
        id_processo=idp, numero=numero,
        data_inicio=ini, data_fim=fim, destino=str(pdf),
    )
    if not dl.get("sucesso"):
        return {"ok": False, "erro": f"Download falhou: {dl.get('erro')}"}
    emit(f"PDF baixado ({dl.get('tamanho', 0)} bytes). Rodando OCR...")

    # OCR (reusa o pipeline do SIS)
    from ingestao import ocr
    texto = ""
    try:
        texto = ocr.extrair_texto(Path(dl["arquivo"]),
                                  timeout_por_pagina_seg=TIMEOUT_OCR_POR_PAGINA_SEG)
        Path(dl["arquivo"]).with_suffix(".txt").write_text(texto, encoding="utf-8")
    except Exception as e:
        emit(f"[aviso] OCR: {type(e).__name__}: {e}")

    # Expedientes (intimação/prazo) para o cabeçalho do digest
    expedientes = _expedientes_do_processo(mcp, idp, numero, emit)

    # Digest consumido pelo prompt_builder
    linhas = [f"# Situação do processo no PJe — {numero}", "",
              f"_Capturado em {_dt.datetime.now().strftime('%d/%m/%Y %H:%M')} (período {ini} a {fim})._", ""]
    if expedientes:
        linhas += ["## Expedientes / intimação / prazo", ""]
        linhas += [f"- {ln}" for ln in expedientes]
        linhas.append("")
    linhas += ["## Peças (texto OCR)", "", (texto.strip() or "_(sem texto extraído)_")]
    (pasta / "_situacao_pje.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    _limpar_flag_intimacao(paj_norm)
    emit("Peças do PJe prontas para análise (_situacao_pje.md gravado).")
    return {"ok": True, "numero": numero, "arquivo": dl.get("arquivo"),
            "tamanho": dl.get("tamanho"), "expedientes": expedientes,
            "chars_ocr": len(texto)}
