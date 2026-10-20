"""Descricao da movimentacao que acompanha a peca anexada no SISDPU.

Padrao do Defensor (07/10/2026): a descricao nao e' mais o nome do arquivo.
Primeira linha no formato "Petição de Réplica minutada e protocolada no PJe.",
seguida de um resumo brevissimo do que foi pedido e do que foi argumentado,
no total de ate 5 linhas.

O texto e' gerado pelo Claude CLI a partir do .txt da peca (o PDF anexado tem
sempre um .txt de mesmo nome ao lado) e chega ao Defensor EDITAVEL antes de
ir para o SISDPU. Se o Claude falhar, devolve-se so a primeira linha, montada
a partir do nome do arquivo, para nao travar a anexacao.
"""

from __future__ import annotations

import asyncio
import html
import re
import subprocess
from pathlib import Path

from config import PAJS_DIR
from services.chat_service import resolver_claude_cmd
from services.paj_service import ler_texto_robusto
from services.planejar_service import _env_sem_claudecode, classificar_erro_claude

MAX_LINHAS = 5
MAX_CHARS_PECA = 60_000

# Regra compartilhada com a aba Discussao (chat_livre_service), para os dois
# caminhos de anexacao escreverem a descricao do mesmo jeito.
REGRA_DESCRICAO = (
    "A descricao da movimentacao tem NO MAXIMO 5 linhas, em texto puro (sem "
    "markdown, sem travessao). A primeira linha diz o tipo da peca e que ela foi "
    "minutada e protocolada no PJe, no formato exato: \"Petição de <Tipo> "
    "minutada e protocolada no PJe.\" (ex.: Réplica, Apelação, Recurso "
    "Inominado, Embargos de Declaração, Contrarrazões, Manifestação). As linhas "
    "seguintes resumem, de forma brevissima, o que foi pedido e os argumentos "
    "centrais: de 2 a 4 linhas, cada uma com uma frase de no maximo 25 "
    "palavras, sem citar ID, folha ou precedente."
)


def _primeira_linha_pelo_nome(nome_arquivo: str) -> str:
    """Fallback: 'Réplica Maria Goretti.pdf' -> 'Petição de Réplica ...'.

    O nome segue o padrao '<tipo da peca> <Nome Sobrenome>', entao as duas
    ultimas palavras sao a parte. Com menos de tres palavras, usa o nome todo.
    """
    base = Path(nome_arquivo).stem.strip()
    palavras = base.split()
    tipo = " ".join(palavras[:-2]) if len(palavras) >= 3 else base
    return f"Petição de {tipo} minutada e protocolada no PJe."


def _txt_da_peca(pasta: Path, caminho_rel: str) -> Path | None:
    alvo = (pasta / caminho_rel).resolve()
    try:
        alvo.relative_to(pasta.resolve())
    except ValueError:
        return None
    txt = alvo.with_suffix(".txt")
    return txt if txt.is_file() else None


def _limpar(texto: str) -> str:
    """Tira marcacao que escape do modelo e corta em MAX_LINHAS."""
    linhas = []
    for linha in texto.splitlines():
        linha = re.sub(r"^\s*(#+|[-*>]|\d+\.)\s+", "", linha)
        linha = linha.replace("**", "").replace("`", "").strip()
        if linha:
            linhas.append(linha)
    return "\n".join(linhas[:MAX_LINHAS])


def descricao_para_html(texto: str) -> str:
    """Uma linha = um paragrafo no CKEditor do SISDPU."""
    return "".join(
        f"<p>{html.escape(l.strip())}</p>" for l in texto.splitlines() if l.strip()
    )


async def gerar_descricao(paj_norm: str, caminho_rel: str, timeout: int = 150) -> dict:
    """Devolve {ok, descricao, aviso?}. `descricao` sempre vem preenchida."""
    pasta = PAJS_DIR / paj_norm
    reserva = _primeira_linha_pelo_nome(Path(caminho_rel).name)

    txt = _txt_da_peca(pasta, caminho_rel)
    if not txt:
        return {
            "ok": False,
            "descricao": reserva,
            "aviso": "não achei o .txt da peça; complete o resumo à mão",
        }
    peca = ler_texto_robusto(txt)[:MAX_CHARS_PECA]

    prompt = (
        "Escreva a descricao de uma movimentacao do SISDPU que acompanha a "
        "peca juridica abaixo, anexada ao PAJ.\n\n"
        f"{REGRA_DESCRICAO}\n\n"
        "Responda SOMENTE com o texto da descricao, nada antes nem depois.\n\n"
        f"Nome do arquivo: {Path(caminho_rel).name}\n\n"
        "--- PECA ---\n"
        f"{peca}\n"
        "--- FIM DA PECA ---"
    )
    cmd = [
        *resolver_claude_cmd(),
        "--print",
        "--output-format", "text",
        "--setting-sources", "user",
        "--append-system-prompt",
        "Voce e' executor de tarefa curta. NAO inicie conversa nem use "
        "ferramentas. Responda apenas com o texto pedido.",
    ]
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(pasta),
            env=_env_sem_claudecode(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "descricao": reserva, "aviso": "o Claude demorou demais"}
    except Exception as e:
        return {"ok": False, "descricao": reserva, "aviso": f"{type(e).__name__}: {e}"}

    if proc.returncode != 0:
        return {"ok": False, "descricao": reserva, "aviso": classificar_erro_claude(proc)}

    descricao = _limpar(proc.stdout or "")
    if not descricao:
        return {"ok": False, "descricao": reserva, "aviso": "o Claude devolveu texto vazio"}
    return {"ok": True, "descricao": descricao}
