#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exporta PAJs para levar em pen drive, sem nuvem.

Por que existe. O Defensor trabalha de casa e da DPU, e sincronizar o SISDPU
duas vezes custa tempo e derruba o login. Guardar a pasta dos PAJs na nuvem
resolveria, mas ali trafegam dados pessoais e de saude dos assistidos — CPF,
laudos, pericias — e ele decidiu, com razao, nao os expor. Entao o transporte
e' fisico: este script empacota, o `importar_pajs.py` desempacota.

O que entra. Por padrao, os PAJs tocados desde a ULTIMA EXPORTACAO (a data
fica em `.ultima_exportacao.json`, dentro da pasta dos PAJs). Sem marca
anterior, usa as ultimas 24 horas. Da' para pedir outro corte com `--desde` ou
mandar tudo com `--tudo`.

O que NAO entra. Nada de credencial: `.env`, `.credentials.json` e afins ficam
de fora por lista explicita, conferida arquivo a arquivo antes de fechar o
pacote.

Uso:
    python ferramentas/exportar_pajs.py
    python ferramentas/exportar_pajs.py --desde 2026-11-01
    python ferramentas/exportar_pajs.py --tudo --saida E:\\
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PAJS_DIR  # noqa: E402

MARCA = ".ultima_exportacao.json"

# Arquivos de estado do painel: viajam junto, porque sao o trabalho do
# Defensor (o que ele concluiu, o que pos na fila de Diligencias).
ESTADO = (".concluidos.json", ".diligencias.json", ".situacao_falhas.json")

# Nunca exportar. Conferido nome a nome antes de gravar no zip.
PROIBIDOS = {".env", ".env.local", ".credentials.json", "credentials.json",
             ".ultima_exportacao.json"}
PROIBIDOS_SUFIXO = (".pem", ".key", ".pfx")


def _data(txt: str) -> datetime.datetime:
    return datetime.datetime.strptime(txt, "%Y-%m-%d")


def _corte(args) -> datetime.datetime | None:
    if args.tudo:
        return None
    if args.desde:
        return _data(args.desde)
    marca = PAJS_DIR / MARCA
    if marca.is_file():
        try:
            d = json.loads(marca.read_text(encoding="utf-8"))
            return datetime.datetime.fromisoformat(d["em"])
        except Exception:
            pass
    return datetime.datetime.now() - datetime.timedelta(hours=24)


def _proibido(nome: str) -> bool:
    n = nome.lower()
    return n in PROIBIDOS or n.endswith(PROIBIDOS_SUFIXO)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--desde", help="corte no formato AAAA-MM-DD")
    ap.add_argument("--tudo", action="store_true",
                    help="exporta todos os PAJs, nao so' os recentes")
    ap.add_argument("--saida", default=str(Path.home() / "Desktop"),
                    help="pasta onde gravar o pacote (ex.: E:\\ para o pen drive)")
    ap.add_argument("--sem-anexos", action="store_true",
                    help="deixa de fora os PDFs de pecas/ (pacote bem menor)")
    args = ap.parse_args()

    if not PAJS_DIR.exists():
        print(f"[ERRO] pasta dos PAJs nao encontrada: {PAJS_DIR}")
        return 1

    corte = _corte(args)
    print(f"pasta  : {PAJS_DIR}")
    print(f"criterio: {'TODOS os PAJs' if corte is None else 'modificados desde ' + corte.strftime('%d/%m/%Y %H:%M')}")

    # Seleciona por PAJ: se QUALQUER arquivo do PAJ mudou, o PAJ inteiro vai.
    # Mandar meio PAJ deixaria a outra maquina com metadata nova e anexo
    # velho, que e' pior que nao mandar.
    selecionados: list[Path] = []
    for pasta in sorted(PAJS_DIR.glob("PAJ-*")):
        if not pasta.is_dir():
            continue
        if corte is None:
            selecionados.append(pasta)
            continue
        for f in pasta.rglob("*"):
            if f.is_file() and datetime.datetime.fromtimestamp(f.stat().st_mtime) >= corte:
                selecionados.append(pasta)
                break

    if not selecionados:
        print("nada mudou desde o ultimo pacote — nenhum arquivo gerado.")
        return 0

    carimbo = datetime.datetime.now()
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    destino = saida / f"PAJs-{carimbo.strftime('%Y%m%d-%H%M')}.zip"

    arquivos: list[tuple[Path, str]] = []
    pulados_proibidos: list[str] = []
    for pasta in selecionados:
        for f in sorted(pasta.rglob("*")):
            if not f.is_file():
                continue
            if _proibido(f.name):
                pulados_proibidos.append(f.name)
                continue
            if args.sem_anexos and "pecas" in f.parts and f.suffix.lower() != ".txt":
                continue
            arquivos.append((f, str(f.relative_to(PAJS_DIR)).replace("\\", "/")))

    for nome in ESTADO:
        f = PAJS_DIR / nome
        if f.is_file():
            arquivos.append((f, f"_estado/{nome}"))

    manifesto = {
        "gerado_em": carimbo.isoformat(timespec="seconds"),
        "origem": str(PAJS_DIR),
        "criterio": "tudo" if corte is None else f"desde {corte.isoformat(timespec='seconds')}",
        "pajs": [p.name for p in selecionados],
        "n_pajs": len(selecionados),
        "sem_anexos": bool(args.sem_anexos),
        "arquivos": {},
    }

    print(f"PAJs   : {len(selecionados)}")
    print(f"arquivos: {len(arquivos)}")
    print("empacotando...")

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f, rel in arquivos:
            z.write(f, rel)
            # Hash de cada arquivo: a importacao confere antes de gravar, e
            # pen drive e' justamente onde arquivo corrompe calado.
            manifesto["arquivos"][rel] = hashlib.sha256(f.read_bytes()).hexdigest()[:16]
        z.writestr("_manifesto.json",
                   json.dumps(manifesto, ensure_ascii=False, indent=2))

    (PAJS_DIR / MARCA).write_text(
        json.dumps({"em": carimbo.isoformat(timespec="seconds"),
                    "pacote": destino.name}, ensure_ascii=False),
        encoding="utf-8")

    mb = destino.stat().st_size / 1e6
    print()
    print(f"[OK] {destino}  ({mb:.1f} MB)")
    if pulados_proibidos:
        print(f"     {len(pulados_proibidos)} arquivo(s) de credencial deixados de fora, "
              "por regra.")
    print()
    print("Leve o arquivo no pen drive. Na outra maquina, rode:")
    print(r"     python ferramentas\importar_pajs.py <caminho do zip>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
