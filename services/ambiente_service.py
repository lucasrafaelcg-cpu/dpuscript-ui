"""Healthcheck de dependencias externas (Tesseract, Chromium).

Rodado no startup de app.py — resultado fica em `app.state.ambiente` pra ser
exibido no dashboard como banner amarelo quando algo falta.

Barato (cache em memoria), nao refaz check durante a vida do processo.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from config import validar_paths


_log = logging.getLogger("ambiente")

_cache: dict | None = None

# Estado do reparo automatico do navegador (rodado em thread, nao trava o
# startup). Valores: "" (nada a fazer) | "rodando" | "ok" | "falhou: <motivo>"
_reparo_status: str = ""
_reparo_tentado = False  # instala no maximo uma vez por processo
_reparo_lock = threading.Lock()

# Executavel esperado de cada browser do Playwright, por plataforma.
_EXES_POR_BROWSER = {
    "chromium": {
        "win32": Path("chrome-win64") / "chrome.exe",
        "linux": Path("chrome-linux") / "chrome",
        "darwin": Path("chrome-mac") / "Chromium.app" / "Contents" / "MacOS" / "Chromium",
    },
    "chromium-headless-shell": {
        "win32": Path("chrome-headless-shell-win64") / "chrome-headless-shell.exe",
        "linux": Path("chrome-headless-shell-linux") / "chrome-headless-shell",
        "darwin": Path("chrome-headless-shell-mac") / "chrome-headless-shell",
    },
}


def _plataforma() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    return "darwin" if sys.platform == "darwin" else "win32"


def _dir_browsers() -> Path:
    """Pasta onde o Playwright guarda os navegadores baixados."""
    env = (os.getenv("PLAYWRIGHT_BROWSERS_PATH") or "").strip()
    if env and env != "0":
        return Path(env)
    if sys.platform == "win32":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path.home() / ".cache" / "ms-playwright"


def _revisoes_esperadas() -> dict[str, str]:
    """Revisao que a versao INSTALADA do Playwright exige, por browser.

    Lida do proprio pacote (`driver/package/browsers.json`) — e' isso que
    evita o falso "ok" depois de um upgrade do playwright, quando a pasta
    antiga continua no disco mas o driver ja procura outra revisao.
    """
    import playwright

    arq = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    return {
        b["name"]: str(b["revision"])
        for b in dados.get("browsers", [])
        if b.get("installByDefault") and b.get("name") in _EXES_POR_BROWSER
    }


def _navegadores_sistema() -> list[str]:
    """Chrome/Edge instalados no sistema — usados como plano B quando o
    binario empacotado esta ausente ou bloqueado pelo Windows."""
    achados = []
    candidatos = {
        "Chrome": [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ],
        "Edge": [
            Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        ],
    }
    for nome, caminhos in candidatos.items():
        if any(c.is_file() for c in caminhos):
            achados.append(nome)
    return achados


def _tesseract_ok() -> tuple[bool, str]:
    """Retorna (ok, versao_ou_motivo)."""
    exe = shutil.which("tesseract")
    if not exe:
        return (False, "tesseract nao encontrado no PATH")
    # Tenta executar --version sem travar
    try:
        import subprocess
        out = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        linha_1 = (out.stdout or out.stderr or "").splitlines()[0] if (out.stdout or out.stderr) else ""
        return (True, linha_1.strip() or "ok")
    except Exception as e:
        return (False, f"erro ao executar: {type(e).__name__}: {e}")


def _chromium_ok() -> tuple[bool, str, list[str]]:
    """Retorna (ok, motivo, faltantes).

    Confere se existe em disco o executavel da REVISAO EXATA que a versao
    instalada do Playwright exige. Checar so' "existe alguma pasta chromium-*"
    nao serve: depois de um upgrade do playwright a pasta antiga continua la',
    o check diria "ok" e a sincronizacao quebraria com
    "Executable doesn't exist".
    """
    try:
        revisoes = _revisoes_esperadas()
    except Exception as e:
        return (False, f"nao consegui ler browsers.json do playwright: {e}", [])

    if not revisoes:
        return (False, "browsers.json do playwright nao listou navegadores", [])

    base = _dir_browsers()
    plat = _plataforma()
    faltantes: list[str] = []
    presentes: list[str] = []

    for browser, rev in revisoes.items():
        rel = _EXES_POR_BROWSER[browser].get(plat)
        if rel is None:
            continue
        # No disco a pasta usa "_" no lugar de "-" (chromium_headless_shell-1228)
        pasta = base / f"{browser.replace('-', '_')}-{rev}"
        exe = pasta / rel
        (presentes if exe.is_file() else faltantes).append(f"{browser}-{rev}")

    if faltantes:
        return (
            False,
            f"faltando em {base}: {', '.join(faltantes)} — "
            "rode `python -m playwright install chromium`",
            faltantes,
        )
    return (True, f"revisoes ok em {base}: {', '.join(presentes)}", [])


def _instalar_navegadores() -> None:
    """Roda `playwright install chromium` numa thread (nao trava o startup).

    Tenta UMA vez por processo: se a instalacao rodar e os binarios seguirem
    ausentes, insistir sozinho viraria um laco de downloads de ~180 MB.
    """
    global _reparo_status, _reparo_tentado
    with _reparo_lock:
        if _reparo_tentado or _reparo_status == "rodando":
            return
        _reparo_tentado = True
        _reparo_status = "rodando"

    def _rodar() -> None:
        global _reparo_status
        _log.warning("navegador do Playwright ausente — instalando automaticamente...")
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                capture_output=True, text=True, timeout=1800,
            )
            if proc.returncode == 0:
                _reparo_status = "ok"
                _log.warning("navegador do Playwright instalado com sucesso")
                verificar_ambiente(forcar=True)  # atualiza o banner da UI
            else:
                cauda = (proc.stderr or proc.stdout or "").strip().splitlines()
                _reparo_status = f"falhou: {cauda[-1] if cauda else f'codigo {proc.returncode}'}"
                _log.error("falha ao instalar navegador: %s", _reparo_status)
        except Exception as e:
            _reparo_status = f"falhou: {type(e).__name__}: {e}"
            _log.error("falha ao instalar navegador: %s", _reparo_status)

    threading.Thread(target=_rodar, daemon=True).start()


def verificar_ambiente(forcar: bool = False) -> dict:
    """Retorna dict com status das dependencias externas.

    {
        "tesseract_ok": bool,
        "tesseract_info": str,
        "chromium_ok": bool,
        "chromium_info": str,
        "avisos": [str],  # lista pra UI
    }

    Cacheia em memoria — so refaz se `forcar=True`.
    """
    global _cache
    if _cache is not None and not forcar:
        return _cache

    t_ok, t_info = _tesseract_ok()
    c_ok, c_info, faltantes = _chromium_ok()
    sistema = _navegadores_sistema()
    erros_path = validar_paths()

    avisos: list[str] = []
    for erro in erros_path:
        avisos.append(f"Workspace ausente — {erro}. Ajuste OFICIO_GERAL no .env.")
    if not t_ok:
        avisos.append(
            f"Tesseract ausente — OCR desligado. {t_info}. "
            "Instale pelo README (UB-Mannheim) e reinicie o painel."
        )

    if not c_ok:
        # Ausencia REAL do binario: reinstalar resolve, entao reinstala sozinho.
        # (Distinto do caso em que o arquivo existe mas o Windows bloqueia sua
        # execucao — ali reinstalar nao muda nada, quem resolve e' a troca
        # automatica de canal em ingestao/sisdpu_client.py.)
        if faltantes:
            _instalar_navegadores()
        if _reparo_status == "rodando":
            avisos.append(
                "Navegador do Playwright ausente — instalando automaticamente "
                "em segundo plano. Aguarde alguns minutos e recarregue; "
                "a sincronização só funciona depois que terminar."
            )
        elif _reparo_status.startswith("falhou"):
            avisos.append(
                f"Instalação automática do navegador falhou ({_reparo_status}). "
                "Rode manualmente: `.venv\\Scripts\\python.exe -m playwright install chromium`."
            )
        else:
            avisos.append(f"Chromium do Playwright indisponível — {c_info}.")

    if not sistema:
        avisos.append(
            "Chrome/Edge não encontrados no sistema — sem eles não há plano B "
            "caso o Windows bloqueie o navegador empacotado do Playwright."
        )

    _cache = {
        "tesseract_ok": t_ok,
        "tesseract_info": t_info,
        "chromium_ok": c_ok,
        "chromium_info": c_info,
        "chromium_faltantes": faltantes,
        "navegadores_sistema": sistema,
        "reparo_status": _reparo_status,
        "avisos": avisos,
    }
    return _cache
