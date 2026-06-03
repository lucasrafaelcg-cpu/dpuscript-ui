"""Console de consultas ao PJe/TRF3 reusando UMA sessao (login unico).

Voce autentica UMA vez; depois consulta quantos processos quiser sem reassinar,
porque o navegador permanece aberto entre as consultas.

Uso (raiz do projeto, venv ativada):

    python -m ingestao.pje_web_console

No prompt, digite uma consulta por linha:

    PAJ-2026-020-02404 --data 07/05/2026     (baixa de 5 dias antes ate hoje)
    5001690-86.2026.4.03.6130 --id 580617842 (baixa so a peca de id 580617842)
    sair                                      (encerra e fecha o navegador)

Os arquivos vao para _pje_teste/<numero>/ com _digest.md (OCR pronto). Sua senha
nunca e' lida nem salva.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ingestao import pje_web
from ingestao.pje_web_test import _parse_args, _resolver_numero


async def _uma_consulta(linha: str) -> None:
    # Reusa o parser do test: monta argv ficticio "x <tokens>".
    tokens = ["x", *linha.split()]
    alvo, data, id_peca = _parse_args(tokens)
    numero = _resolver_numero(alvo)
    so_digitos = "".join(ch for ch in numero if ch.isdigit())
    out = Path(__file__).resolve().parent.parent / "_pje_teste" / (so_digitos or "processo")

    res = await pje_web.consultar(numero, out, data_intimacao=data, id_peca=id_peca)
    print(f"  -> {len(res['arquivos'])} arquivo(s); digest: {res.get('digest_md')}")


async def _main() -> int:
    loop = asyncio.get_event_loop()
    print("Abrindo navegador e sessao do PJe/TRF3 (faca login se pedir)...")
    await pje_web.abrir_sessao()
    print("\nSessao pronta. Digite consultas (ou 'sair' para encerrar):")
    print("  exemplos:  PAJ-2026-020-02404 --data 07/05/2026")
    print("             5001690-86.2026.4.03.6130 --id 580617842\n")
    try:
        while True:
            try:
                linha = (await loop.run_in_executor(None, input, "pje> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not linha:
                continue
            if linha.lower() in ("sair", "exit", "quit", "q"):
                break
            try:
                await _uma_consulta(linha)
            except Exception as e:
                print(f"  [erro] {type(e).__name__}: {e}")
    finally:
        print("Encerrando sessao (fechando navegador)...")
        await pje_web.fechar_sessao()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
