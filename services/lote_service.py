#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analise de VARIOS PAJs em conjunto (lote).

Para que serve: o Defensor recebe uma lista de PAJs — digitada, copiada do
SISDPU ou fotografada — e precisa olha-los JUNTOS, para decidir se cabe uma
peca unica que abarque todos (tipicamente um oficio a um mesmo orgao pedindo
informacao sobre varios assistidos).

O ganho aqui e' NAO reanalisar nada: cada PAJ ja' tem `SITUACAO.md` (a analise
FIRAC executada pelo painel) e `metadata.json`. Este modulo consolida esse
material que ja' existe num unico contexto, pronto para o Claude raciocinar
sobre o conjunto.

Uso pela linha de comando (e' assim que a aba Discussao chama):

    python -m services.lote_service 2026/056-00511 2026/056-00427
    python -m services.lote_service --arquivo lista.txt
    python -m services.lote_service --imagem foto_da_lista.jpg
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from config import PAJS_DIR

# Orcamento de caracteres do contexto consolidado. Acima disso o prompt fica
# grande demais e a analise perde foco; o corte e' por PAJ, proporcional.
ORCAMENTO_TOTAL = 120_000
MIN_CHARS_POR_PAJ = 1_200
MAX_MOVS_POR_PAJ = 3

# Aceita 2026/056-00511, PAJ-2026-056-00511, 2026-056-00511, 2026.056.00511
_RE_PAJ = re.compile(r"(?:PAJ[\s\-:]*)?(\d{4})[\s./\-]+(\d{3})[\s./\-]+(\d{4,6})")


def extrair_pajs(texto: str) -> list[str]:
    """Extrai identificadores de PAJ de texto livre, na ordem, sem repetir."""
    achados: list[str] = []
    for m in _RE_PAJ.finditer(texto or ""):
        ano, uni, num = m.group(1), m.group(2), m.group(3).zfill(5)
        norm = f"PAJ-{ano}-{uni}-{num}"
        if norm not in achados:
            achados.append(norm)
    return achados


def extrair_pajs_de_imagem(caminho: str | Path) -> tuple[list[str], str]:
    """OCR numa foto/print da lista. Retorna (pajs, texto_reconhecido)."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            f"OCR indisponivel ({e}). Instale pillow e pytesseract."
        ) from e

    img = Image.open(str(caminho))
    texto = pytesseract.image_to_string(img, lang="por")
    return extrair_pajs(texto), texto


def _resumo_situacao(paj_dir: Path, limite: int) -> str:
    """Analise FIRAC previa do PAJ, sem o rodape de metadados do painel."""
    f = paj_dir / "SITUACAO.md"
    if not f.is_file():
        return "(sem análise prévia — rode a análise da Situação do PAJ)"
    t = f.read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"^_Análise FIRAC gerada.*?\n", "", t, flags=re.S | re.M).strip()
    if len(t) > limite:
        t = t[:limite].rstrip() + "\n[...] (truncado — leia o SITUACAO.md completo)"
    return t


def _bloco_paj(paj_norm: str, limite: int) -> dict:
    """Monta o bloco de um PAJ. `encontrado=False` se a pasta nao existe."""
    d = PAJS_DIR / paj_norm
    if not d.is_dir():
        return {"paj_norm": paj_norm, "encontrado": False, "texto": ""}

    meta = {}
    fm = d / "metadata.json"
    if fm.is_file():
        try:
            meta = json.loads(fm.read_text(encoding="utf-8"))
        except Exception:
            meta = {}

    movs = ((meta.get("detalhes_sisdpu") or {}).get("movimentacoes")) or []
    movs = sorted(movs, key=lambda m: int(m.get("seq", 0) or 0), reverse=True)

    linhas = [
        f"### {meta.get('paj') or paj_norm} — {meta.get('assistido_caixa') or '?'}",
        "",
        f"- Pretensão: {meta.get('pretensao') or meta.get('classificacao') or '?'}",
        f"- Processo judicial: {meta.get('processo_judicial') or '(sem processo)'}",
        f"- Abertura: {meta.get('data_abertura') or '?'}"
        f" | Foro: {meta.get('foro_detectado') or '?'}",
    ]
    if meta.get("decurso"):
        linhas.append(f"- Decurso/prazo: {meta['decurso']}")
    pecas = d / "pecas"
    if pecas.is_dir():
        n = len([p for p in pecas.iterdir() if p.is_file()])
        if n:
            linhas.append(f"- Anexos/peças na pasta: {n}")

    if movs:
        linhas += ["", "**Últimas movimentações:**"]
        for m in movs[:MAX_MOVS_POR_PAJ]:
            data = m.get("data_original") or m.get("data") or "?"
            desc = re.sub(r"\s+", " ", (m.get("descricao") or "")).strip()[:300]
            linhas.append(f"- [{data}] {desc}")

    linhas += ["", "**Análise prévia (FIRAC do painel):**", "",
               _resumo_situacao(d, limite)]
    return {"paj_norm": paj_norm, "encontrado": True, "texto": "\n".join(linhas)}


def montar_contexto_lote(pajs: list[str], origem_ocr: bool = False) -> dict:
    """Consolida os PAJs num unico contexto markdown.

    `origem_ocr=True` acrescenta aviso de conferencia: OCR troca digito (visto
    na pratica: 00126 lido como 00128). Quando a troca cai num PAJ que NAO
    existe, o proprio relatorio acusa; o perigo e' quando cai num PAJ que
    EXISTE — daí o oficio sairia com o assistido errado. Por isso o nome do
    assistido vai no titulo de cada bloco, para conferencia visual.

    Retorna {texto, encontrados, nao_encontrados, chars}.
    """
    if not pajs:
        return {"texto": "", "encontrados": [], "nao_encontrados": [], "chars": 0}

    # divide o orcamento entre os PAJs, com piso por PAJ
    limite = max(MIN_CHARS_POR_PAJ, ORCAMENTO_TOTAL // max(1, len(pajs)))

    blocos, encontrados, faltando = [], [], []
    for p in pajs:
        b = _bloco_paj(p, limite)
        if b["encontrado"]:
            encontrados.append(p)
            blocos.append(b["texto"])
        else:
            faltando.append(p)

    cabecalho = [
        f"# Análise em lote — {len(encontrados)} PAJ(s)",
        "",
        "Contexto consolidado pelo painel a partir do `metadata.json` e da "
        "análise FIRAC (`SITUACAO.md`) que JÁ EXISTEM em cada PAJ — nada foi "
        "reanalisado aqui.",
    ]
    if origem_ocr:
        cabecalho += [
            "",
            "> **A lista veio de OCR (foto/print) — CONFIRA antes de usar.** O "
            "reconhecimento troca dígito (já ocorreu `00126` lido como "
            "`00128`). Confronte cada número com o NOME DO ASSISTIDO no título "
            "dos blocos abaixo e confirme com o Defensor antes de redigir "
            "qualquer peça: um dígito errado que caia em outro PAJ existente "
            "colocaria o assistido errado na peça.",
        ]
    if faltando:
        cabecalho += [
            "",
            f"> **Não localizados** ({len(faltando)}): {', '.join(faltando)}. "
            "Confira o número ou sincronize o PAJ antes de considerá-lo."
            + (" Vindo de OCR, o mais provável é dígito lido errado."
               if origem_ocr else ""),
        ]
    texto = "\n".join(cabecalho) + "\n\n" + "\n\n---\n\n".join(blocos) + "\n"
    return {
        "texto": texto,
        "encontrados": encontrados,
        "nao_encontrados": faltando,
        "chars": len(texto),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Consolida vários PAJs num contexto único para análise conjunta."
    )
    ap.add_argument("pajs", nargs="*", help="PAJs (ex.: 2026/056-00511)")
    ap.add_argument("--arquivo", help="arquivo de texto com a lista")
    ap.add_argument("--imagem", help="foto/print da lista (usa OCR)")
    ap.add_argument("--saida", help="grava o contexto neste arquivo .md")
    args = ap.parse_args(argv)

    bruto = " ".join(args.pajs)
    if args.arquivo:
        bruto += "\n" + Path(args.arquivo).read_text(encoding="utf-8", errors="replace")

    lista = extrair_pajs(bruto)
    if args.imagem:
        achados, texto_ocr = extrair_pajs_de_imagem(args.imagem)
        print(f"[OCR] reconheci {len(achados)} PAJ(s) na imagem", file=sys.stderr)
        if not achados:
            print(f"[OCR] texto lido: {texto_ocr[:300]!r}", file=sys.stderr)
        for p in achados:
            if p not in lista:
                lista.append(p)

    if not lista:
        print("Nenhum PAJ reconhecido na entrada.", file=sys.stderr)
        return 1

    res = montar_contexto_lote(lista, origem_ocr=bool(args.imagem))
    if args.saida:
        Path(args.saida).write_text(res["texto"], encoding="utf-8")
        print(f"[OK] contexto de {len(res['encontrados'])} PAJ(s) em {args.saida}",
              file=sys.stderr)
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(res["texto"])
    if res["nao_encontrados"]:
        print(f"[AVISO] nao localizados: {res['nao_encontrados']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
