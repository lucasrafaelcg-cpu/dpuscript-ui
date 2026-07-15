"""Backfill do `processo_judicial` em PAJs já sincronizados.

Motivo: PAJs abertos por intimação não trazem "PROCESSO JUDICIAL VINCULADO" no
cabeçalho do SISDPU — o número consta apenas numa movimentação
("Número do Processo Judicial: <20 dígitos>"). O parser passou a extrair isso
(ingestao/parser.extrair_processo_das_movs), mas os PAJs já gravados ficaram
com o campo vazio. Este script preenche o campo a partir das movimentações JÁ
ARMAZENADAS em cada metadata.json — sem re-sincronizar e sem regerar o metadata
inteiro (preserva evento_triagem, em_caixa_atual, pje_intimacao_pendente etc.).

Uso (a partir da raiz do projeto, com a venv):
    .venv/Scripts/python.exe ferramentas/backfill_processo_judicial.py          # dry-run
    .venv/Scripts/python.exe ferramentas/backfill_processo_judicial.py --apply  # grava
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PAJS_DIR  # noqa: E402
from ingestao.parser import extrair_processo_das_movs  # noqa: E402


def main(apply: bool) -> int:
    if not PAJS_DIR.exists():
        print(f"PAJS_DIR não existe: {PAJS_DIR}")
        return 1

    total = achou = gravou = 0
    for pasta in sorted(PAJS_DIR.iterdir()):
        meta_path = pasta / "metadata.json"
        if not pasta.is_dir() or not meta_path.exists():
            continue
        total += 1
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[skip] {pasta.name}: metadata ilegível ({e})")
            continue

        if (meta.get("processo_judicial") or "").strip():
            continue  # já tem número — não mexe

        movs = (meta.get("detalhes_sisdpu", {}) or {}).get("movimentacoes", []) or []
        numero = extrair_processo_das_movs(movs)
        if not numero:
            continue

        achou += 1
        print(f"[{'grava' if apply else 'dry '}] {pasta.name}: processo_judicial -> {numero}")
        if apply:
            meta["processo_judicial"] = numero
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            gravou += 1

    print("-" * 60)
    print(f"PAJs analisados: {total} | número recuperável: {achou} | gravados: {gravou}")
    if achou and not apply:
        print("Dry-run — rode de novo com --apply para gravar.")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
