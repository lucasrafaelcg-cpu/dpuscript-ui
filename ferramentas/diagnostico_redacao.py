# -*- coding: utf-8 -*-
"""Diagnostico de redacao: mede os textos gerados contra a escala do Defensor.

VERSAO 3.1 — MODO DPU EM VIGOR (decisao do Defensor em 18/09/2026).

O alvo default e o despacho da DPU: `--nivel simples`. Dentro do modo o detalhe
ainda escala (`trabalhoso`), porque ele proprio escala. O nivel `complexo`
guarda a base do modo MPF, arquivado em
~/.claude/_modelo-anterior/instrucoes-mpf.md, e continua disponivel para
comparacao a qualquer momento.

O objetivo nao e' zerar contadores, e' convergir para o numero dele no nivel
certo.

Tres coisas do manual NAO sao medidas aqui e dependem de leitura: a frase de
efeito (C.2), o uso de negrito (C.4) e a ordem narrativa (B.2).

Uso:
    python ferramentas/diagnostico_redacao.py
    python ferramentas/diagnostico_redacao.py --nivel simples
    python ferramentas/diagnostico_redacao.py --pasta X --glob "*.txt"
    python ferramentas/diagnostico_redacao.py --arquivo p.txt --nivel complexo
    python ferramentas/diagnostico_redacao.py --sem-exemplos
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter
from pathlib import Path


PADRAO_BASE = Path.home() / "Desktop" / "Ofício Geral"
PADRAO_GLOB = "PAJs/*/*.txt"
IGNORAR_NOMES = {"sisdpu.txt", "resumo.txt", "contexto.txt"}
MIN_CHARS = 400


# ---------------------------------------------------------------------------
# DEFEITOS. Cada entrada: (regex, ignore_case, regra_do_manual, base_do_defensor)
# `base` = % de documentos DELE com o padrao, medido no corpus do MPF.
# ---------------------------------------------------------------------------
PADROES: dict[str, tuple[str, bool, str, str]] = {
    "anuncia-quantidade": (
        r"\b(duas|dois|tr[eê]s|quatro|cinco|seis)\s+"
        r"(raz[oõ]es|consequ[eê]ncias|observa[cç][oõ]es|ressalvas|pontos|cautelas|"
        r"provid[eê]ncias|requisitos|condi[cç][oõ]es|medidas|premissas|cuidados|"
        r"exig[eê]ncias|crit[eé]rios|obje[cç][oõ]es|notas|aspectos|fundamentos|"
        r"vertentes|planos|respostas|teses|hip[oó]teses)\b",
        False, "5", "4%",
    ),
    "primeira-e-que": (r"\bA (primeira|segunda|terceira) (é|e) que\b", False, "5", "0%"),
    "travessao-par": (r"—[^—\n.!?]{1,120}—", False, "3", "0% (1 caso em 284)"),
    "adjetivo-enfatico": (
        r"\b(cristalin[oa]|insofism[aá]vel|cabal(mente)?|inequ[ií]voc[oa]|robust[oa]|"
        r"indene de d[uú]vidas|estreme de d[uú]vidas|irretorqu[ií]vel|incontest[aá]vel)\b",
        True, "9", "7%",
    ),
    "grandiloquencia": (
        r"\b(Estado Democr[aá]tico de Direito|em [uú]ltima an[aá]lise|"
        r"dignidade da pessoa humana|m[ií]nimo existencial)\b",
        True, "10", "2%",
    ),
    "nao-se-trata-mas": (r"[Nn][aã]o se trata de .{0,90}?\bmas\b", False, "11", "0%"),
    "anuncio-vazio": (
        r"\b(é|e) (importante|fundamental|essencial|crucial|imprescind[ií]vel) "
        r"(destacar|salientar|ressaltar|registrar|notar|mencionar|frisar|consignar|observar)\b",
        False, "—", "1%",
    ),
    "prova-generica": (
        r"\b(documenta[cç][aã]o (acostada|carreada|juntada) aos autos|"
        r"documentos acostados|farta documenta[cç][aã]o|documenta[cç][aã]o dos autos)\b",
        True, "4", "0%",
    ),
}

# ---------------------------------------------------------------------------
# REGISTRO DO DEFENSOR. Medidos, NAO sao defeito. Estavam na tabela de
# defeitos da v1 por erro meu: ele usa mais que eu. Ficam aqui so' para
# acompanhar, com a frequencia dele ao lado.
# ---------------------------------------------------------------------------
REGISTRO_LEGITIMO: dict[str, tuple[str, str]] = {
    "Outrossim": (r"\bOutrossim\b", "38% dos docs dele"),
    "Nesse contexto/sentido": (
        r"\bNe(sse|sta|ste|ssa) (contexto|sentido|senda|esteira|linha|toada|passo)\b",
        "33% dos docs dele",
    ),
    "Com efeito": (r"\bCom efeito\b", "25% dos docs dele"),
    "Registre-se/Ressalte-se": (
        r"\b(Registre-se|Ressalte-se|Destaque-se|Frise-se|Anote-se|Salienta-se)\b",
        "7% dos docs dele",
    ),
    "Cumpre/Vale destacar": (
        r"\b(Cumpre|Vale|Importa|Conv[eé]m|Cabe)\s+"
        r"(destacar|salientar|ressaltar|registrar|mencionar|consignar|notar|frisar|observar)\b",
        "6% dos docs dele",
    ),
    "Em suma/Em sintese": (r"\b(Em suma|Em s[ií]ntese)\b", "25% dos docs dele"),
}

# Titulos de secao. Cobre os formatos que ele usa (romano) e os que eu uso
# (markdown e topico numerado).
#
# A ultima alternativa foi acrescentada depois de a ferramenta dar "OK" no
# despacho que o Defensor reprovou: ali os topicos eram numerados num nivel
# so' e INLINE ("1. DO ESCLARECIMENTO SOBRE O ACIDENTE. Esclarecido que..."),
# forma que nenhum dos padroes anteriores pegava. Sem isso a regra 1 era
# inverificavel no formato de despacho, que e' texto puro sem markdown.
RX_TITULO = re.compile(
    r"(?m)^\s{0,6}(?:"
    r"#{1,4}\s+\S"
    r"|[IVXLC]{1,5}\s*[-–—.]\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ]"
    r"|[IVXLC]{1,5}\.\d{1,2}\.?\s*[A-ZÁÉÍÓÚÂÊÔÃÕÇ]"
    r"|\d{1,2}\.\d{1,2}\.?\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3}"
    r"|\d{1,2}\s*[.)]\s+(?:D[AEO]S?|AO|À|NO|NA)\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ]{3}"
    r"|\d{1,2}\s*[.)]\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][A-ZÁÉÍÓÚÂÊÔÃÕÇ\-]{2}[A-ZÁÉÍÓÚÂÊÔÃÕÇ \-/]{5,}"
    r")"
)
RX_ANCORA = re.compile(
    r"\b(?:fls?|ff)\.\s*\d"           # processo fisico (corpus antigo de 2017)
    r"|\b(?:ID|evento|seq)\.?\s*\d"    # PJe
    r"|\bmov\.?\s*\d",                 # SISDPU
    re.IGNORECASE,
)

# Titulo que nomeia ARGUMENTO em vez de MATERIA. O Defensor apontou o defeito
# num recurso meu: "III - DO QUE A PROPRIA AUTARQUIA JA RECONHECEU" deveria ser
# "III - DOS REQUISITOS DO BENEFICIO E DO NEXO ACIDENTARIO", com aquela
# observacao dentro da prosa. Sinais conservadores, escolhidos para nao acusar
# titulo legitimo de materia (DA NULIDADE, DA PRESCRICAO, DO TERMO INICIAL):
#   - dois-pontos no titulo (titulo retorico em duas partes);
#   - abertura por "DO QUE"/"DAQUILO QUE";
#   - adverbio de sinalizacao processual como prefixo;
#   - substantivo valorativo (ERRO, EQUIVOCO, FRAGILIDADE...);
#   - verbo conjugado no titulo (RECONHECEU, ENFRENTOU, IGNOROU...).
RX_TITULO_ARGUMENTO = re.compile(
    r"(?m)^\s{0,6}(?:#{1,4}\s+)?(?:[IVXLC]{1,5}|\d{1,2})\s*[-–—.]\s*([^\n]{6,90})$"
)
_SINAIS_ARGUMENTO = (
    re.compile(r":"),
    re.compile(r"(?i)^\s*D[OA]\s+QUE\b|^\s*DAQUILO\s+QUE\b"),
    re.compile(r"(?i)^\s*(?:SUBSIDIARIAMENTE|PRELIMINARMENTE|AINDA|POR FIM|ADEMAIS)\b"),
    re.compile(r"(?i)\b(?:ERRO|EQU[IÍ]VOCO|FRAGILIDADE|INCONSIST[EÊ]NCIA|ACERTO"
               r"|ABSURDO|TERATOLOGIA|DESCUIDO|OMISS[AÃ]O DA DECIS[AÃ]O)\b"),
    re.compile(r"(?i)\b\w+(?:OU|ARAM|ERAM|IRAM|AVA|ERA\b|SERIA|DEVERIA)\b(?!\s*$)"),
)


def _e_titulo_de_verdade(linha: str, texto_titulo: str) -> bool:
    """Filtra item de lista e ruido de OCR, que o regex de titulo tambem casa.

    Titulo nestes documentos e' linha curta e predominantemente em CAIXA ALTA,
    ou cabecalho markdown. Sem esta checagem, "1) auxilio-doenca e aposentadoria
    por invalidez: 12 (doze) contribuicoes" e "Por fim, minutar resposta..."
    eram acusados como titulo retorico (26 falsos positivos no corpus dele).
    """
    if linha.lstrip().startswith("#"):
        return True
    letras = [c for c in texto_titulo if c.isalpha()]
    if len(letras) < 8:
        return False
    return sum(1 for c in letras if c.isupper()) / len(letras) >= 0.6


def titulos_de_argumento(texto: str) -> list[str]:
    """Titulos que nomeiam argumento em vez de materia."""
    out = []
    for m in RX_TITULO_ARGUMENTO.finditer(texto):
        t = m.group(1).strip().rstrip(".")
        if not _e_titulo_de_verdade(m.group(0), t):
            continue
        if any(s.search(t) for s in _SINAIS_ARGUMENTO):
            out.append(t)
    return out

# ---------------------------------------------------------------------------
# A ESCALA DE DETALHE. O Defensor nao tem um modelo unico: ele escala o detalhe
# conforme a complexidade, e o gradiente esta medido dentro dos proprios
# corpora dele. Comparar uma peca complexa com a base do despacho simples (ou
# o contrario) produz diagnostico errado, por isso o `--nivel`.
#
#   simples    = 105 despachos curtos da DPU (< 1.500 chars)  <- default
#   trabalhoso = 23 despachos longos da DPU (>= 3.000 chars)
#   complexo   = 284 documentos do MPF — modo ARQUIVADO, so para comparar
# ---------------------------------------------------------------------------
NIVEIS: dict[str, dict[str, float]] = {
    "simples":       {"titulos": 0.17, "ancora": 0.31, "conectivo": 4.30,
                      "frases_par": 1.5, "par_1frase": 74.0, "palavras_frase": 21.4},
    "trabalhoso":   {"titulos": 0.17, "ancora": 0.57, "conectivo": 4.09,
                      "frases_par": 2.3, "par_1frase": 62.0, "palavras_frase": 23.9},
    "complexo":      {"titulos": 1.46, "ancora": 2.48, "conectivo": 2.47,
                      "frases_par": 5.2, "par_1frase": 39.0, "palavras_frase": 26.0},
    # Peca judicial: medido nas 10 pecas judiciais DELE (ACP, contrarrazoes,
    # denuncia, inicial, recurso — 37.155 palavras). Vale independente do modo
    # DPU/MPF em vigor, porque o corpus da DPU e so de despachos: e a unica
    # medicao de como ELE escreve peca. Aqui titulo e ancora sao exigidos, e a
    # frase e MAIS longa que no despacho, nao menos.
    "peca":          {"titulos": 1.29, "ancora": 3.47, "conectivo": 2.34,
                      "frases_par": 6.3, "par_1frase": 37.0, "palavras_frase": 30.2},
}
# Alias: o nome antigo continua valendo em scripts e no historico.
NIVEIS["intermediario"] = NIVEIS["trabalhoso"]

RX_CONECTIVO = re.compile(
    r"(?i)\b(outrossim|com efeito|nesse (?:contexto|sentido|passo)|nessa linha"
    r"|ademais|entretanto|todavia|em que pese|do mesmo modo|nesse cen[aá]rio"
    r"|em resumo|em suma|como se sabe|afinal|para tanto)\b"
)


def carregar(caminhos: list[Path]) -> dict[Path, str]:
    out: dict[Path, str] = {}
    for p in caminhos:
        if p.name in IGNORAR_NOMES:
            continue
        texto = None
        for enc in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                texto = p.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, OSError):
                continue
        if texto and len(texto) >= MIN_CHARS:
            out[p] = texto
    return out


RX_DISPOSITIVO = re.compile(
    r"(?is)\b(?:ante o exposto|diante do exposto|do exposto)[^\n]{0,60}?"
    r"(?:determino|requer|requeiro|pugna|pede)\s*:.*$"
)


def _corpo(texto: str) -> str:
    """Prosa, para medir ritmo: sem titulo, sem marcador e SEM dispositivo.

    O dispositivo em alineas e' uma frase unica de centenas de palavras
    separada por ponto e virgula, e o manual o aprova nessa forma. Medi-lo
    como frase inflava a media (36,2 contra 31,2 no despacho do PAJ
    2026/056-00674) e mandava encurtar o que estava certo.
    """
    t = re.sub(r"^\s*#.*$", "", texto, flags=re.MULTILINE)
    t = re.sub(r"\[[A-Z ÇÃÕÁÉÍÓÚ]+\]", "", t)
    return RX_DISPOSITIVO.sub("", t)


def medir(textos: dict[Path, str], exemplos: bool = True,
          nivel: str = "simples") -> int:
    n_arq = len(textos)
    if not n_arq:
        print("Nenhuma peca encontrada.")
        return 1

    tot: Counter = Counter()
    arqs: Counter = Counter()
    amostras: dict[str, list[tuple[str, str]]] = {k: [] for k in PADROES}

    for p, t in textos.items():
        for nome, (rx, ic, _regra, _base) in PADROES.items():
            achados = list(re.finditer(rx, t, re.IGNORECASE if ic else 0))
            if not achados:
                continue
            tot[nome] += len(achados)
            arqs[nome] += 1
            if len(amostras[nome]) < 3:
                m = achados[0]
                ini, fim = max(0, m.start() - 60), min(len(t), m.end() + 60)
                amostras[nome].append((p.name, " ".join(t[ini:fim].split())))

    print(f"PECAS ANALISADAS: {n_arq}\n")
    print("DEFEITOS (a coluna 'dele' e' a frequencia no corpus do Defensor)")
    print(f"{'padrao':24} {'regra':>5} {'ocorr':>6} {'arqs':>5} {'%arqs':>6}   {'dele':<18}")
    print("-" * 74)
    for nome, (_rx, _ic, regra, base) in PADROES.items():
        pct = 100 * arqs[nome] / n_arq
        print(f"{nome:24} {regra:>5} {tot[nome]:>6} {arqs[nome]:>5} {pct:>5.0f}%   {base:<18}")
    print("-" * 74)
    print(f"{'TOTAL':24} {'':>5} {sum(tot.values()):>6}")

    # --- a escala: compara com o nivel escolhido ---
    alvo = NIVEIS[nivel]
    palavras = sum(len(t.split()) for t in textos.values())
    titulos = sum(len(RX_TITULO.findall(t)) for t in textos.values())
    ancoras = sum(len(RX_ANCORA.findall(t)) for t in textos.values())
    conect = sum(len(RX_CONECTIVO.findall(t)) for t in textos.values())

    pf: list[int] = []
    for t in textos.values():
        for par in re.split(r"\n\s*\n", t):
            par = " ".join(par.split())
            if len(par.split()) >= 8 and not par.startswith(("#", "|", ">")):
                pf.append(len([f for f in re.split(r"(?<=[.!?])\s+", par) if f.strip()]))
    frases = [len(f.split()) for t in textos.values()
              for f in re.split(r"(?<=[.!?])\s+", _corpo(t)) if len(f.split()) > 2]

    def linha(rot, valor, base, direcao, fmt="{:.2f}"):
        """direcao: 'menos' (alvo e' teto), 'mais' (alvo e' piso), 'perto' (faixa)."""
        if direcao == "menos":
            sit = "ok" if valor <= base * 1.6 else "ACIMA"
        elif direcao == "mais":
            sit = "ok" if valor >= base * 0.6 else "ABAIXO"
        else:
            sit = "ok" if base * 0.75 <= valor <= base * 1.35 else (
                "ACIMA" if valor > base else "ABAIXO")
        print(f"  {rot:34} {fmt.format(valor):>7}   alvo {fmt.format(base):>7}   {sit}")

    print(f"\nESCALA — comparando com o nivel '{nivel}' ({palavras:,} palavras)")
    print(f"  {'metrica':34} {'medido':>7}   {'':>12}")
    linha("titulos por mil palavras", 1000 * titulos / palavras if palavras else 0,
          alvo["titulos"], "menos")
    linha("ancora de documento por mil", 1000 * ancoras / palavras if palavras else 0,
          alvo["ancora"], "perto")
    linha("conectivo classico por mil", 1000 * conect / palavras if palavras else 0,
          alvo["conectivo"], "mais")
    if pf:
        linha("frases por paragrafo", statistics.mean(pf), alvo["frases_par"], "perto", "{:.1f}")
        linha("% paragrafos de 1 frase", 100 * sum(1 for x in pf if x == 1) / len(pf),
              alvo["par_1frase"], "perto", "{:.0f}")
    if frases:
        linha("palavras por frase", statistics.mean(frases), alvo["palavras_frase"],
              "perto", "{:.1f}")

    # --- titulo de argumento (defeito apontado pelo Defensor em 18/09/2026) ---
    arg: list[tuple[str, str]] = []
    for p, t in textos.items():
        for titulo in titulos_de_argumento(t):
            arg.append((p.name, titulo))
    print("\nTITULO DE ARGUMENTO (o titulo nomeia a MATERIA, nunca o argumento)")
    if arg:
        print(f"  {len(arg)} titulo(s) em {len({a for a, _ in arg})} peca(s). "
              f"Base do Defensor: 1 caso em 457 documentos.")
        for nome, titulo in arg[:8]:
            print(f"    {nome}: {titulo[:70]}")
        if len(arg) > 8:
            print(f"    ... e mais {len(arg) - 8}")
    else:
        print("  nenhum")

    # --- registro legitimo ---
    print("\nREGISTRO DO DEFENSOR (legitimo, so' para acompanhar)")
    for nome, (rx, base) in REGISTRO_LEGITIMO.items():
        o = sum(len(re.findall(rx, t)) for t in textos.values())
        a = sum(1 for t in textos.values() if re.search(rx, t))
        print(f"  {nome:24} {o:>4} ocorr | {a:>3}/{n_arq} arqs ({100*a/n_arq:>3.0f}%) | {base}")

    # --- dispersao: referencia, nao defeito. A media de palavras por frase ja
    # entra na tabela da escala; aqui fica so' a variacao, que nao e' defeito
    # em nenhum dos corpora.
    if frases:
        curtas = 100 * sum(1 for x in frases if x <= 12) / len(frases)
        longas = 100 * sum(1 for x in frases if x >= 40) / len(frases)
        print(f"\nDISPERSAO (referencia, nao defeito): {len(frases)} frases | "
              f"desvio {statistics.pstdev(frases):.1f} | "
              f"curtas {curtas:.0f}% | longas {longas:.0f}%")

    if exemplos:
        print("\n=== EXEMPLOS EM CONTEXTO ===")
        for nome in PADROES:
            if amostras[nome]:
                print(f"\n[{nome}]")
                for arq, ex in amostras[nome]:
                    print(f"  - {arq}: ...{ex}...")

    print("\nNAO medido aqui (depende de leitura): frase de efeito (regra 2), "
          "negrito (regra 6), ordem narrativa (regra 8).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Mede os defeitos do manual-redacao.md nas pecas.")
    ap.add_argument("--pasta", type=Path, help="raiz a varrer (default: Desktop/Ofício Geral)")
    ap.add_argument("--glob", default=PADRAO_GLOB, help=f"padrao de busca (default: {PADRAO_GLOB})")
    ap.add_argument("--arquivo", type=Path, action="append", help="medir arquivo(s) especifico(s)")
    ap.add_argument("--sem-exemplos", action="store_true", help="so' as tabelas")
    ap.add_argument("--nivel", choices=sorted(NIVEIS), default="simples",
                    help="nivel esperado do caso (default: simples; 'complexo' e a base do modo MPF arquivado)")
    args = ap.parse_args()

    if args.arquivo:
        caminhos = list(args.arquivo)
        faltando = [p for p in caminhos if not p.exists()]
        if faltando:
            print(f"Nao encontrei: {', '.join(str(p) for p in faltando)}", file=sys.stderr)
            return 2
    else:
        base = args.pasta or PADRAO_BASE
        if not base.exists():
            print(f"Pasta nao encontrada: {base}", file=sys.stderr)
            return 2
        caminhos = sorted(base.glob(args.glob))

    return medir(carregar(caminhos), exemplos=not args.sem_exemplos, nivel=args.nivel)


if __name__ == "__main__":
    raise SystemExit(main())
