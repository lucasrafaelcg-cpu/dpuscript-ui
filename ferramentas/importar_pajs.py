#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Importa o pacote de PAJs gerado pelo `exportar_pajs.py`.

Regra que governa tudo: NUNCA apaga e NUNCA sobrescreve coisa mais nova.
A comparacao e' por data de modificacao, arquivo a arquivo. Quem trabalhou
nos dois lados no mesmo PAJ nao perde o lado local — o arquivo mais novo
fica, e o caso e' relatado no fim para o Defensor decidir.

Confere o SHA-256 de cada arquivo contra o manifesto antes de gravar: pen
drive e' onde arquivo corrompe calado.

Uso:
    python ferramentas/importar_pajs.py E:\\PAJs-20261110-1930.zip
    python ferramentas/importar_pajs.py <zip> --simular
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PAJS_DIR  # noqa: E402

ESTADO = (".concluidos.json", ".diligencias.json", ".situacao_falhas.json")

# Margem na comparacao de datas (ver o comentario no laco de copia).
TOLERANCIA_S = 3


def _longo(p: Path) -> str:
    """Caminho no formato que vence o limite de 260 caracteres do Windows.

    Os anexos do SISDPU tem nome comprido ("PETICAO INICIAL. COBRANCA
    PREVIDENCIARIA. MARIA DAS GRACAS ROSA. 2026.056-00490.docx"), e somados a
    `...\\Oficio Geral\\PAJs\\PAJ-AAAA-056-NNNNN\\pecas\\` passam dos 260 que
    a API classica do Windows aceita. O prefixo `\\\\?\\` manda usar a API
    estendida. Sem ele a copia falhava com "nao pode encontrar o caminho".
    """
    if sys.platform != "win32":
        return str(p)
    abs_ = str(p.resolve())
    return abs_ if abs_.startswith("\\\\?\\") else "\\\\?\\" + abs_


def _mesclar_estado(origem: Path, destino: Path, log) -> None:
    """Junta os arquivos de estado do painel, sem perder nenhum dos lados.

    `.concluidos.json` e `.situacao_falhas.json` sao mapas por PAJ: a uniao
    resolve. `.diligencias.json` e' lista de itens com id: entram os ids que
    faltam, e o que ja' existe nao e' tocado — item marcado como anexado de
    um lado nao pode voltar a pendente pelo outro.
    """
    try:
        novo = json.loads(origem.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"    estado {origem.name}: ilegivel no pacote ({e}) — mantido o local")
        return

    if not destino.exists():
        shutil.copy2(origem, destino)
        log(f"    estado {destino.name}: criado")
        return

    try:
        atual = json.loads(destino.read_text(encoding="utf-8"))
    except Exception:
        log(f"    estado {destino.name}: local ilegivel — mantido como esta")
        return

    if destino.name == ".diligencias.json":
        ids = {i.get("id") for i in (atual.get("itens") or [])}
        novos = [i for i in (novo.get("itens") or []) if i.get("id") not in ids]
        if novos:
            atual.setdefault("itens", []).extend(novos)
            destino.write_text(json.dumps(atual, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        log(f"    estado {destino.name}: +{len(novos)} item(ns) novo(s)")
        return

    if isinstance(atual, dict) and isinstance(novo, dict):
        faltando = {k: v for k, v in novo.items() if k not in atual}
        if faltando:
            atual.update(faltando)
            destino.write_text(json.dumps(atual, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        log(f"    estado {destino.name}: +{len(faltando)} registro(s)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pacote", help="caminho do zip gerado pelo exportar_pajs.py")
    ap.add_argument("--simular", action="store_true",
                    help="mostra o que faria, sem gravar nada")
    args = ap.parse_args()

    pacote = Path(args.pacote)
    if not pacote.is_file():
        print(f"[ERRO] pacote nao encontrado: {pacote}")
        return 1

    PAJS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"pacote : {pacote.name}  ({pacote.stat().st_size/1e6:.1f} MB)")
    print(f"destino: {PAJS_DIR}")

    tmp = Path(tempfile.mkdtemp(prefix="importar-pajs-"))
    try:
        with zipfile.ZipFile(pacote) as z:
            ruim = z.testzip()
            if ruim:
                print(f"[ERRO] zip corrompido no arquivo {ruim} — nao importei nada.")
                return 1
            z.extractall(tmp)
            # O zipfile do Python NAO restaura a data de modificacao: todo
            # arquivo extraido fica com a hora da extracao. Isso quebrava duas
            # coisas: a regra "o mais novo vence" comparava sempre contra
            # agora, e o SITUACAO.md importado parecia recem-gerado, enganando
            # a medida de analise desatualizada. Devolve-se a data gravada no
            # proprio zip.
            for info in z.infolist():
                if info.is_dir():
                    continue
                alvo = tmp / info.filename
                if not alvo.exists():
                    continue
                quando = datetime.datetime(*info.date_time).timestamp()
                os.utime(alvo, (quando, quando))

        man_path = tmp / "_manifesto.json"
        if not man_path.is_file():
            print("[ERRO] pacote sem _manifesto.json — nao parece do exportar_pajs.py")
            return 1
        man = json.loads(man_path.read_text(encoding="utf-8"))

        print(f"gerado : {man.get('gerado_em', '?')} em {man.get('origem', '?')}")
        print(f"criterio: {man.get('criterio', '?')}  |  PAJs: {man.get('n_pajs', '?')}")
        if man.get("sem_anexos"):
            print("AVISO  : pacote SEM os anexos binarios (so' texto e analises).")
        print()

        novos = atualizados = mantidos = corrompidos = 0
        conflitos: list[str] = []

        def log(m: str) -> None:
            print(m)

        for rel, hash_esperado in sorted(man.get("arquivos", {}).items()):
            origem = tmp / rel
            if not origem.is_file():
                print(f"    {rel}: no manifesto mas ausente no zip — pulado")
                continue
            if hashlib.sha256(origem.read_bytes()).hexdigest()[:16] != hash_esperado:
                corrompidos += 1
                print(f"    CORROMPIDO {rel} — NAO gravado")
                continue

            if rel.startswith("_estado/"):
                continue

            destino = PAJS_DIR / rel
            if destino.exists():
                t_novo = origem.stat().st_mtime
                t_atual = destino.stat().st_mtime
                # Tolerancia de 3s: o zip guarda a data com granularidade de
                # DOIS segundos e perde a fracao, entao um arquivo identico
                # reextraido aparece com diferenca de ate 2s. Com tolerancia de
                # 1s, reimportar o mesmo pacote reescrevia os 1.772 arquivos e
                # dizia "atualizados", o que e' falso e castiga o pen drive.
                if t_atual > t_novo + TOLERANCIA_S:
                    mantidos += 1
                    conflitos.append(rel)
                    continue
                if abs(t_atual - t_novo) <= TOLERANCIA_S:
                    mantidos += 1
                    continue
                acao = "atualizado"
                atualizados += 1
            else:
                acao = "novo"
                novos += 1

            if not args.simular:
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(_longo(origem), _longo(destino))
            if acao == "novo" and rel.endswith("metadata.json"):
                print(f"    + {rel.split('/')[0]}")

        if not args.simular:
            for nome in ESTADO:
                f = tmp / "_estado" / nome
                if f.is_file():
                    _mesclar_estado(f, PAJS_DIR / nome, log)

        print()
        print(f"novos: {novos} | atualizados: {atualizados} | "
              f"mantidos (locais iguais ou mais novos): {mantidos}")
        if corrompidos:
            print(f"[ATENCAO] {corrompidos} arquivo(s) corrompido(s) no pacote, "
                  "nao gravados. Refaca o pacote na maquina de origem.")
        if conflitos:
            print()
            print(f"[DECISAO SUA] {len(conflitos)} arquivo(s) estavam MAIS NOVOS "
                  "aqui e foram preservados. Houve trabalho nos dois lados:")
            for rel in conflitos[:12]:
                print(f"    {rel}")
            if len(conflitos) > 12:
                print(f"    ... e mais {len(conflitos) - 12}")
            print("    Nada foi perdido: o pacote segue no pen drive se quiser "
                  "comparar.")
        if args.simular:
            print()
            print("SIMULACAO — nada foi gravado.")
        else:
            print()
            print("Reinicie o painel para ele reler a pasta.")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
