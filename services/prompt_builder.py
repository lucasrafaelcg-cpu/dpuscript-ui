"""Gera PROMPT_MAX.md dinamicamente por PAJ (contexto tecnico da elaboracao).

Papel no fluxo (docs/FLUXO_DE_TRABALHO.md):
- `montar_contexto()` — o CONTEXTO do PAJ (identificacao, prazos, movimentacoes,
  evento detectado, pecas, PJe, texto do SISDPU). Reusado pela analise FIRAC
  executada (services/situacao_service) e pelo PROMPT_MAX.
- `gerar_prompt_max()` — PROMPT_MAX.md consumido pelo chat/elaboracao. Quando a
  analise FIRAC ja foi executada (SITUACAO.md na pasta do PAJ), o PROMPT_MAX
  ABRE com ela — a elaboracao parte da situacao ja analisada, conforme o fluxo
  definido pelo Defensor (primeiro a analise da situacao, depois o prompt max).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from config import PAJS_DIR


# Quantidade de movimentacoes no resumo. 12 (e nao so a ultima) porque o
# evento que efetivamente encaminhou o PAJ ao defensor pode estar atras de
# conclusoes/encaminhamentos em duplicidade posteriores.
MAX_MOVIMENTACOES_RESUMO = 12

# Quantas das movimentacoes mais recentes entram praticamente inteiras, e os
# tetos de corte. O apontamento da assessoria / do Nucleo Assistencial — que
# diz o que precisa ser feito agora — vem nas ultimas movimentacoes e passa
# facilmente de 400 chars; truncar ali apagava a orientacao principal.
MOVS_RECENTES_INTEGRAIS = 4
MAX_CHARS_MOV_RECENTE = 2_000
MAX_CHARS_MOV = 600

# O digest do PJe (_situacao_pje.md) contém o OCR integral das peças baixadas —
# pode passar de centenas de páginas. No PROMPT_MAX entra só o início; o texto
# completo continua disponível no arquivo, e o aviso aponta para ele.
MAX_PJE_DIGEST_CHARS = 30_000

# Anexos baixados do SISDPU (pasta `pecas/`). O contexto lista TODOS pelo nome
# (barato) e embute o texto extraido dos mais RECENTES — sao eles que dizem o
# que aconteceu agora (ex.: o laudo pericial que motivou a intimacao). Sem isso
# a analise "ve" so a descricao da movimentacao ("Laudo pericial emitido") e
# conclui, erradamente, que o teor do documento nao esta disponivel.
MAX_ANEXOS_COM_TEXTO = 6
MAX_ANEXOS_CHARS_POR_ARQUIVO = 6_000
MAX_ANEXOS_CHARS_TOTAL = 30_000

# A minuta a revisar entra INTEIRA (ou quase): revisar por amostra produz
# revisao errada. Teto alto so' pra evitar estourar o contexto em pecas gigantes.
MAX_MINUTA_CHARS = 40_000

# Nomes que indicam que um anexo e' a minuta produzida pela assessoria.
_RE_NOME_MINUTA = re.compile(
    r"minuta|petic|petiç|replica|répl|contrarraz|impugnac|impugnaç|recurso|"
    r"\bpi\b|\bps\b|manifest|contest|memorial|embargos|agravo|apelac|apelaç",
    re.I,
)

# Arquivo com o RESULTADO da analise FIRAC executada (services/situacao_service).
SITUACAO_FILE = "SITUACAO.md"


def _ordem_e_data(nome: str) -> tuple[int, str]:
    """Extrai (indice, data) do padrao de nome gravado pelo sincronizador:
    `NN_DD_MM_AAAA_descricao.ext`. O indice e' a posicao na tabela de arquivos
    do SISDPU, que lista do mais RECENTE para o mais antigo — logo indice
    menor = anexo mais novo."""
    m = re.match(r"^(\d+)_(\d{2})_(\d{2})_(\d{4})_?", nome)
    if m:
        return int(m.group(1)), f"{m.group(2)}/{m.group(3)}/{m.group(4)}"
    return (9_999, "")


def _inventario_anexos(pasta: Path) -> list[dict]:
    """Inventario dos anexos do PAJ, do mais recente para o mais antigo.

    Considera DOIS estados possiveis de cada anexo:
      - binario presente (+ `.txt` companion, quando houve extracao);
      - binario JA REMOVIDO pela limpeza de anexos (`limpar_anexos_paj`), que
        apaga o PDF/DOCX e PRESERVA o `.txt` — nesse caso o `.txt` fica orfao
        e continua sendo a unica fonte do teor. Ignorar orfaos faria a analise
        perder o conteudo de todo PAJ ja limpo.

    Cada item: {nome, data, txt (Path|None), removido (bool)}.
    """
    pecas = pasta / "pecas"
    if not pecas.is_dir():
        return []

    arquivos = [f for f in pecas.iterdir() if f.is_file()]
    fontes = [f for f in arquivos if f.suffix.lower() != ".txt"]
    txts = [f for f in arquivos if f.suffix.lower() == ".txt"]
    stems_com_fonte = {f.stem for f in fontes}

    itens: list[dict] = []
    for f in fontes:
        txt = f.with_suffix(".txt")
        itens.append({
            "nome": f.name,
            "data": _ordem_e_data(f.name)[1],
            "ordem": _ordem_e_data(f.name)[0],
            "txt": txt if txt.exists() else None,
            "removido": False,
        })
    for t in txts:
        if t.stem in stems_com_fonte:
            continue  # e' companion de uma fonte ja listada
        itens.append({
            "nome": t.stem,
            "data": _ordem_e_data(t.name)[1],
            "ordem": _ordem_e_data(t.name)[0],
            "txt": t,
            "removido": True,
        })

    itens.sort(key=lambda i: i["ordem"])
    return itens


def _secao_anexos(pasta: Path, ler_texto) -> list[str]:
    """Lista os anexos do SISDPU e embute o texto dos mais recentes.

    Sem esta secao a analise nao tem acesso ao CONTEUDO dos documentos — so'
    a' descricao da movimentacao —, e passa a afirmar que o teor de um laudo
    ou decisao "nao consta", mesmo com o texto disponivel na pasta.
    """
    itens = _inventario_anexos(pasta)
    if not itens:
        return []

    linhas = ["", f"## Anexos do SISDPU ({len(itens)})"]
    linhas.append(
        "Ordenados do mais recente para o mais antigo. O texto extraido de cada "
        "um esta no `.txt` de mesmo nome, dentro de `pecas/` nesta pasta — "
        "LEIA o arquivo quando precisar do inteiro teor."
    )
    for it in itens:
        txt = it["txt"]
        if txt is None:
            marca = "sem texto extraido"
        else:
            tam = txt.stat().st_size
            marca = (
                "texto extraido" if tam > 400
                else f"texto quase vazio ({tam} B) — possivel PDF escaneado sem OCR util"
            )
        if it["removido"]:
            marca += " · binario removido pela limpeza (texto preservado)"
        linhas.append(f"- **[{it['data'] or '?'}]** `{it['nome']}` — {marca}")

    # Conteudo dos mais recentes, com teto global pra nao estourar o contexto.
    embutidos = 0
    total = 0
    for it in itens:
        if embutidos >= MAX_ANEXOS_COM_TEXTO or total >= MAX_ANEXOS_CHARS_TOTAL:
            break
        txt = it["txt"]
        if txt is None or txt.stat().st_size <= 400:
            continue
        conteudo = (ler_texto(txt) or "").strip()
        if not conteudo:
            continue
        if len(conteudo) > MAX_ANEXOS_CHARS_POR_ARQUIVO:
            conteudo = conteudo[:MAX_ANEXOS_CHARS_POR_ARQUIVO].rstrip() + "\n[...] (truncado — leia o .txt para o resto)"
        linhas.append("")
        linhas.append(f"### Texto do anexo [{it['data'] or '?'}] `{it['nome']}`")
        linhas.append("")
        linhas.append(conteudo)
        embutidos += 1
        total += len(conteudo)

    if embutidos == 0:
        linhas.append("")
        linhas.append(
            "> Nenhum anexo tinha texto extraido utilizavel. Se o evento depende "
            "do teor de um documento, abra o PDF em `pecas/` ou avise que o OCR falhou."
        )
    return linhas


def _localizar_minuta(pasta: Path) -> dict | None:
    """Melhor candidato, em `pecas/`, a ser a minuta feita pela assessoria.

    Prioriza (1) nome com "minuta", (2) demais nomes de peca, sempre do anexo
    mais RECENTE para o mais antigo. Exige texto extraido — sem ele nao ha' o
    que revisar. Aceita anexo cujo binario ja foi removido pela limpeza, desde
    que o `.txt` tenha sido preservado.
    """
    cands = []
    for it in _inventario_anexos(pasta):
        txt = it["txt"]
        if txt is None or txt.stat().st_size <= 200:
            continue
        # `_` e' caractere de palavra: sem trocar por espaco, `\bpi\b` nunca
        # casaria em nomes como "03_29_07_2026_PI.docx".
        nome_norm = it["nome"].replace("_", " ")
        if not _RE_NOME_MINUTA.search(nome_norm):
            continue
        cands.append((0 if "minuta" in nome_norm.lower() else 1, it["ordem"], it))

    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]))
    return cands[0][2]


def _secao_minuta(pasta: Path, movs_ord: list[dict], ler_texto) -> list[str]:
    """Secao de REVISAO DE MINUTA — so' aparece quando a assessoria devolveu
    uma minuta para o Defensor conferir."""
    from services.triagem_service import detectar_minuta_para_revisao

    minuta_evt = detectar_minuta_para_revisao(movs_ord)
    if not minuta_evt:
        return []

    linhas = ["", "## Minuta da assessoria aguardando revisao do Defensor"]
    linhas.append(
        f"- **Movimentacao:** [{minuta_evt['data'] or '?'}] (seq {minuta_evt['seq']}) "
        f"{minuta_evt['descricao']}"
    )

    item = _localizar_minuta(pasta)
    if item is not None:
        texto = (ler_texto(item["txt"]) or "").strip()
        if len(texto) > MAX_MINUTA_CHARS:
            texto = texto[:MAX_MINUTA_CHARS].rstrip() + "\n[...] (truncado)"
        linhas.append(f"- **Arquivo da minuta:** `pecas/{item['nome']}`")
        if item["removido"]:
            linhas.append(
                "- (binario original removido pela limpeza de anexos; abaixo "
                "esta o texto preservado)"
            )
        linhas.append("")
        linhas.append("### Texto integral da minuta a revisar")
        linhas.append("")
        linhas.append(texto)
    elif minuta_evt.get("link"):
        linhas.append(
            f"- **Onde esta:** no editor de texto do PJe — {minuta_evt['link']}"
        )
        linhas.append(
            "> ATENCAO: a minuta NAO esta nos arquivos deste PAJ; ela vive no "
            "editor do PJe. NAO tente adivinhar o teor: informe que o texto "
            "precisa ser colado/exportado para o PAJ antes da revisao."
        )
    else:
        linhas.append(
            "> ATENCAO: nao localizei o arquivo da minuta em `pecas/` (nem link "
            "do PJe). NAO invente o conteudo — diga que a minuta nao esta "
            "acessivel e peca o arquivo."
        )
    return linhas


def _ler_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def montar_contexto(paj_norm: str) -> str | None:
    """Contexto completo do PAJ em markdown (sem instrucao de tarefa).

    None se a pasta do PAJ nao existe. Base comum do PROMPT_MAX e do prompt
    da analise FIRAC executada.
    """
    pasta = PAJS_DIR / paj_norm
    if not pasta.exists():
        return None

    metadata = _ler_json(pasta / "metadata.json") or {}
    sisdpu_path = pasta / "sisdpu.txt"

    # Import tardio pra evitar ciclo com paj_service
    from services.paj_service import listar_pecas_assistido, ler_texto_robusto

    sisdpu_texto = ler_texto_robusto(sisdpu_path) if sisdpu_path.exists() else ""

    pecas_antes = listar_pecas_assistido(metadata.get("assistido_caixa", ""))

    partes: list[str] = []
    partes.append(f"# PAJ {metadata.get('paj', paj_norm)}")
    partes.append("")
    partes.append("## Identificacao")
    partes.append(f"- **Assistido:** {metadata.get('assistido_caixa') or '—'}")
    partes.append(f"- **Pretensao:** {metadata.get('pretensao') or '—'}")
    partes.append(f"- **Oficio responsavel:** {metadata.get('oficio_caixa') or '—'}")
    proc = metadata.get("processo_judicial") or ""
    foro_det = metadata.get("foro_detalhado") or ""
    if proc:
        partes.append(f"- **Processo judicial:** {proc}" + (f" ({foro_det})" if foro_det else ""))
    else:
        partes.append("- **Processo judicial:** (nao cadastrado)")
    partes.append(f"- **Status:** {metadata.get('detalhes_sisdpu', {}).get('status_paj') or 'Ativo'}")

    prazos = metadata.get("prazos_abertos") or []
    if prazos:
        partes.append("")
        partes.append("## Prazos abertos")
        for p in prazos:
            descr = p.get("descricao") or p.get("parte") or "prazo"
            partes.append(f"- **{p.get('data_final', '?')}** ({p.get('dias', '?')} dias) — {descr}")

    # Movimentacoes recentes (cronologico reverso)
    det = metadata.get("detalhes_sisdpu", {}) or {}
    movs = det.get("movimentacoes") or []
    movs_ord = sorted(movs, key=lambda m: int(m.get("seq", 0) or 0), reverse=True)
    truncou_alguma = False
    if movs_ord:
        partes.append("")
        partes.append(f"## Ultimas movimentacoes (top {min(MAX_MOVIMENTACOES_RESUMO, len(movs_ord))})")
        for pos, mov in enumerate(movs_ord[:MAX_MOVIMENTACOES_RESUMO]):
            data = mov.get("data_original") or mov.get("data") or "?"
            descr = (mov.get("descricao") or "").strip()
            # As movimentacoes mais RECENTES ganham teto bem maior: e' nelas que
            # vem o apontamento da assessoria / do Nucleo Assistencial dizendo o
            # que fazer agora, e esse texto costuma passar de 400 chars. Cortar
            # ali fazia a analise perder justamente a orientacao.
            limite = MAX_CHARS_MOV_RECENTE if pos < MOVS_RECENTES_INTEGRAIS else MAX_CHARS_MOV
            if len(descr) > limite:
                descr = descr[:limite].rstrip() + "..."
                truncou_alguma = True
            partes.append(f"- **[{data}]** {descr}")
        # Aviso explicito sobre truncamento + onde ler o texto integral. So aparece
        # quando alguma descricao foi cortada — caso contrario, o resumo ja basta.
        if truncou_alguma:
            partes.append("")
            partes.append(
                "> Algumas descricoes acima foram truncadas em 400 caracteres. O texto "
                "integral consta na secao \"Texto completo do SISDPU\" abaixo, e "
                "tambem em `sisdpu.txt` nesta mesma pasta caso prefira ler isolado."
            )

    # Evento que (provavelmente) encaminhou o PAJ ao defensor — heuristica
    # deterministica de triagem_service. E' uma DICA para a analise FIRAC,
    # nao um veredito.
    from services.triagem_service import detectar_evento_recente

    evento = detectar_evento_recente(movs_ord)
    if evento:
        partes.append("")
        partes.append("## Evento detectado pelo painel (heuristica)")
        partes.append(f"- **Tipo provavel:** {evento['label']}")
        partes.append(
            f"- **Movimentacao:** [{evento['data'] or '?'}] (seq {evento['seq']}) "
            f"{evento['descricao'] or '(sem descricao)'}"
        )
        partes.append(
            "> Classificacao automatica por padrao de texto — CONFIRME na "
            "analise antes de seguir o fluxo."
        )

    if pecas_antes:
        partes.append("")
        partes.append(f"## Pecas anteriores do mesmo assistido ({len(pecas_antes)})")
        partes.append("Arquivos em `Pecas Feitas/` com nome similar ao assistido:")
        for p in pecas_antes[:20]:
            partes.append(f"- `{p['nome']}`")

    # Situação do processo no PJe (peças/intimação) — gravada por
    # services/pje_service.puxar_pecas() quando o defensor puxa do TRF3.
    pje_md = pasta / "_situacao_pje.md"
    if pje_md.exists():
        partes.append("")
        partes.append("## Situação do processo no PJe (peças e intimação)")
        pje_texto = ler_texto_robusto(pje_md).strip() or "(vazio)"
        if len(pje_texto) > MAX_PJE_DIGEST_CHARS:
            pje_texto = pje_texto[:MAX_PJE_DIGEST_CHARS].rstrip() + "..."
            partes.append(
                f"> Digest truncado em {MAX_PJE_DIGEST_CHARS} caracteres. O texto "
                "integral (OCR completo das peças) está em `_situacao_pje.md` "
                "nesta mesma pasta — leia-o se precisar do inteiro teor."
            )
            partes.append("")
        partes.append(pje_texto)

    # Minuta da assessoria pendente de revisao (quando houver) — vem ANTES dos
    # anexos porque, nesse cenario, revisar a minuta e' a tarefa principal.
    partes.extend(_secao_minuta(pasta, movs_ord, ler_texto_robusto))

    # Anexos do SISDPU (nomes + texto extraido dos mais recentes).
    partes.extend(_secao_anexos(pasta, ler_texto_robusto))

    partes.append("")
    partes.append("---")
    partes.append("")
    partes.append("## Texto completo do SISDPU")
    partes.append("")
    partes.append(sisdpu_texto.strip() or "(sem texto de SISDPU)")

    return "\n".join(partes)


_INSTRUCAO_ELABORACAO = """## Analise solicitada — skill FIRAC

Aplique a skill `firac` (Sistema Integrado de Analise Juridica da DPU) sobre
este PAJ. Se a secao "Situacao do PAJ — analise FIRAC ja realizada" estiver
presente no INICIO deste documento, PARTA dela (nao refaca a analise do zero;
apenas confirme contra as movimentacoes) e siga direto ao encaminhamento.

1. **Razao do encaminhamento.** Leia as ULTIMAS MOVIMENTACOES acima (nao apenas
   a ultima) e identifique qual movimentacao EFETIVAMENTE encaminhou este PAJ
   ao defensor. Cuidado com os ruidos conhecidos do SISDPU:
   - PAJs chegam em duplicidade na caixa: a ultima movimentacao pode ser uma
     "conclusao" posterior — o evento real esta em movimentacao anterior.
   - Descricao "Fase incluida automaticamente, verificar fase anterior": o
     sinal esta na FASE da propria movimentacao ou na movimentacao anterior.
   - Decurso de prazo com situacao "PREVISTO" e' programacao futura — ignore;
     so o decurso "EFETIVADO" caracteriza envio ao defensor.

2. **Classifique o evento** em um destes 5 fluxos de entrada:
   1. Abertura de PAJ (ou redistribuicao a unidade)
   2. Retorno do Assistido
   3. Intimacao judicial
   4. Resposta de oficio
   5. Controle de prazo (envio automatico pelo sistema ao encerrar um prazo de controle)

2b. **PRIORIDADE — apontamentos da assessoria.** Antes de qualquer coisa, leia
   as ULTIMAS movimentacoes com atencao especial aos apontamentos da
   ASSESSORIA e do NUCLEO ASSISTENCIAL: e' ali que normalmente esta dito, de
   forma direta, o que precisa ser feito AGORA (minutar determinada peca,
   despachar, oficiar, aguardar, arquivar). Essa orientacao e' o eixo do
   trabalho: confirme-a contra os autos e produza a providencia indicada
   (DESPACHO ou PECA). Nao proponha caminho diverso sem motivo expresso.

   Pendencia de documentacao NAO e' achado padrao: trate-a apenas se IMPEDIR a
   providencia apontada. Se nao impede, no maximo uma observacao curta — nunca
   entregue "documentacao incompleta" no lugar da peca/despacho cabivel.

2c. **SE CABE PECA, A PECA E' O PRODUTO.** Concluindo que cabe peticao
   intercorrente, recurso ou qualquer manifestacao ao juizo, ELABORE A MINUTA
   agora. NAO aguarde a assessoria e NAO produza despacho remetendo o caso a'
   assessoria/gabinete/apoio para que outra pessoa minute — formulas como
   "encaminhe-se a' assessoria para minuta" ou "ao apoio para minutar" estao
   PROIBIDAS como produto quando a peca ja' e' cabivel. Despacho so' e' produto
   final quando NAO ha' peca a fazer (mero acompanhamento, ciencia de ato
   neutro, arquivamento). Quando a assessoria JA' entregou algo, leia e use;
   quando ainda nao entregou, faca voce.

2d. **PAJ DE PRIMEIRO CONTATO — MERITO, nao checklist.** Se o PAJ chega ao
   defensor pela primeira vez (abertura de PAJ, redistribuicao, PAJ novo na
   caixa), analise o MERITO antes de decidir: qualifique o direito pleiteado,
   confronte os REQUISITOS legais um a um com o que os documentos provam,
   levante obstaculos (prescricao, prévio requerimento administrativo, coisa
   julgada, competencia, tese contraria consolidada) e conclua a viabilidade
   como VIAVEL, AINDA NAO VIAVEL (dizendo qual prova falta e como obter) ou
   INVIAVEL (dizendo o encaminhamento). Consulte a base da CCR/DPU em
   `~/.claude/conhecimento-dpu/` (comece pelo `INDICE.md`) e cite enunciado,
   tese de arquivamento ou precedente SO' se estiver literalmente na base.
   Sendo VIAVEL, produza a peca cabivel — nao um despacho de encaminhamento.

3. **Siga a orientacao do fluxo identificado:**
   - **Retorno do Assistido** — leia o que o assistido solicitou ou apresentou a DPU
     e o que a assessoria apontou:
     (a) requerimento, reclamacao ou pedido de informacao → analise e minute
         resposta educada ao assistido em linguagem acessivel (skill `mensagem`);
     (b) apresentacao de documentacao → se ela ja viabiliza a providencia
         apontada, EXECUTE a providencia; so' minute mensagem cobrando
         documento faltante quando a falta realmente impedir o proximo passo,
         listando exatamente o que falta.
   - **Abertura de PAJ** — leia a narrativa e os documentos, aplique a triagem
     da area e verifique a viabilidade. Aponte lacunas documentais so' quando
     impedirem a atuacao agora.
   - **Intimacao judicial** — identifique o ato comunicado, o prazo e a peca
     cabivel (FIRAC Modulo 1). Se processo do TRF3, considere as pecas do PJe
     (secao "Situacao do processo no PJe" acima, quando existir).
   - **Resposta de oficio** — leia o documento respondido (texto OCR nas pecas):
     a demanda foi solucionada? SIM → proponha despacho de conclusao e
     comunicado ao assistido; NAO → proponha os proximos passos (reiteracao,
     judicializacao, nova diligencia).
   - **Controle de prazo** — identifique o que o prazo controlava (resposta de
     orgao, retorno do assistido, transito) e proponha a providencia: cobranca,
     arquivamento ou proximo passo.

4. **Entregue, nesta ordem:**
   (a) a razao do encaminhamento em 2-3 frases;
   (b) breve analise FIRAC (Fatos, Questoes, Regras, Aplicacao, Conclusao);
   (c) o proximo passo recomendado, ja indicando a peca (peticao, despacho ao
       DPU Digital ou mensagem ao assistido) e a skill adequada.

Siga o `CLAUDE.md` do workspace e, apos a aprovacao do Defensor, produza o
TEXTO pronto da peca/despacho/mensagem na pasta do PAJ.

NOME DO ARQUIVO: inclua o NOME e o SOBRENOME da parte, no formato
`<tipo da peca> <Nome Sobrenome>.txt` — ex.:
`Manifestacao Impugnacao Laudo Clarissa Lopes.txt`,
`Recurso Inominado Maria Souza.txt`. Use o primeiro nome + primeiro sobrenome
(nome completo fica longo demais). Espacos e acentos podem; evite
`\\ / : * ? " < > | # &`. Despacho comeca com a palavra `Despacho` (o painel usa
esse prefixo para separar despachos de pecas judiciais)."""


def gerar_prompt_max(paj_norm: str) -> Path | None:
    """Monta PROMPT_MAX.md dentro da pasta do PAJ e retorna o Path.

    Ordem definida pelo Defensor: se a analise FIRAC executada existe
    (SITUACAO.md), ela ABRE o documento; o contexto tecnico e a instrucao
    de elaboracao vem depois.
    """
    pasta = PAJS_DIR / paj_norm
    contexto = montar_contexto(paj_norm)
    if contexto is None:
        return None

    from services.paj_service import ler_texto_robusto

    partes: list[str] = []
    situacao_path = pasta / SITUACAO_FILE
    if situacao_path.exists():
        situacao = ler_texto_robusto(situacao_path).strip()
        if situacao:
            partes.append("# Situacao do PAJ — analise FIRAC ja realizada")
            partes.append("")
            partes.append(situacao)
            partes.append("")
            partes.append("---")
            partes.append("")

    partes.append(contexto)
    partes.append("")
    partes.append("---")
    partes.append("")
    partes.append(_INSTRUCAO_ELABORACAO)

    prompt_path = pasta / "PROMPT_MAX.md"
    prompt_path.write_text("\n".join(partes), encoding="utf-8")
    return prompt_path
