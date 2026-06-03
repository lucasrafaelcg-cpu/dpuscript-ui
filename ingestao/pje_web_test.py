"""Teste/execucao do acesso automatizado ao PJe via navegador.

Uso (raiz do projeto, venv ativada):

    # por DATA da intimacao (baixa de 5 dias antes ate hoje):
    python -m ingestao.pje_web_test PAJ-2026-020-02404 --data 07/05/2026

    # por ID da peca (baixa so aquela peca):
    python -m ingestao.pje_web_test PAJ-2026-020-02404 --id 580617842

    # tambem aceita o numero do processo no lugar do PAJ:
    python -m ingestao.pje_web_test 5001690-86.2026.4.03.6130 --data 07/05/2026

Fluxo: abre o Chrome -> login (1a vez) -> busca o numero -> abre os autos ->
baixa as pecas (por data ou por ID) -> OCR -> _digest.md. Sem criterio, cai no
modo assistido (voce baixa, ele captura). Sua senha nunca e' lida nem salva.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ingestao import pje_web


def _resolver_numero(arg: str) -> str:
    if arg.upper().startswith("PAJ-"):
        num = pje_web.numero_do_paj(arg)
        if not num:
            raise SystemExit(
                f"[erro] PAJ {arg}: numero do processo nao encontrado no "
                f"metadata.json (campo 'processo_judicial')."
            )
        print(f"[pje-web] PAJ {arg} -> processo {num}")
        return num
    return arg


def _parse_args(argv: list[str]) -> tuple[str, str | None, str | None]:
    """Retorna (alvo, data_intimacao, id_peca)."""
    alvo = argv[1]
    data = None
    id_peca = None
    i = 2
    while i < len(argv):
        if argv[i] in ("--data", "-d") and i + 1 < len(argv):
            data = argv[i + 1]
            i += 2
        elif argv[i] in ("--id", "-i") and i + 1 < len(argv):
            id_peca = argv[i + 1]
            i += 2
        else:
            i += 1
    return alvo, data, id_peca


async def _run(alvo: str, data: str | None, id_peca: str | None) -> int:
    numero = _resolver_numero(alvo)
    so_digitos = "".join(ch for ch in numero if ch.isdigit())
    out = Path(__file__).resolve().parent.parent / "_pje_teste" / (so_digitos or "processo")

    res = await pje_web.processar(numero, out, data_intimacao=data, id_peca=id_peca)
    print("\n" + "=" * 60)
    print(f"[pje-web] modo: {res['modo']}")
    print(f"[pje-web] {len(res['arquivos'])} arquivo(s) salvos em {out}")
    if res.get("digest_md"):
        print(f"[pje-web] digest: {res['digest_md']}")
        previa = Path(res["digest_md"]).read_text(encoding="utf-8")[:1500]
        print("\n" + previa)
    else:
        print("[pje-web] nenhuma peca capturada. Veja logs/pje_debug/ para calibrar.")
    print("=" * 60)
    return 0 if res["arquivos"] else 1


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Uso: python -m ingestao.pje_web_test <numero|PAJ-...> [--data DD/MM/AAAA] [--id <idPeca>]")
        return 2
    alvo, data, id_peca = _parse_args(argv)
    return asyncio.run(_run(alvo, data, id_peca))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
