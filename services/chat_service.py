"""Servico de chat interativo com Claude Code CLI via stream-json bidirecional."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import queue
from pathlib import Path

from config import OFICIO_GERAL, PAJS_DIR
from services import historico
from services.paj_service import IGNORAR as ARQUIVOS_NAO_PECAS
from services.skills_catalog import skill_descricao, skill_valida
import contextlib


def _resolver_claude_cmd() -> list[str]:
    r"""Resolve o comando base pra invocar o Claude CLI.

    Ordem de busca:
      1. `CLAUDE_CODE_EXECPATH` (env var canonica setada pelo proprio Claude Code
         quando o servidor e' lancado de dentro de uma sessao do Claude Code).
      2. `shutil.which("claude")` — pega o instalador via npm (`claude.cmd`) ou
         o nativo (`claude.exe`) quando estao no PATH.
      3. Caminhos bem conhecidos no Windows:
         - `%USERPROFILE%\.local\bin\claude.exe` (instalador nativo Anthropic)
         - `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\claude-code\<versao>\claude.exe`
           (Claude Desktop / MSIX — versao mais recente).

    Sem isso, instalacoes via Desktop App ficavam invisiveis (PATH nao contem
    o caminho do MSIX) e toda elaboracao morria com `FileNotFoundError`.

    No Windows, `claude.cmd` (npm) precisa de `cmd.exe /c` pra ser executavel
    pelo Popen sem shell=True. `.exe` roda direto.
    """
    # 1. Hint do proprio Claude Code
    env_hint = os.environ.get("CLAUDE_CODE_EXECPATH", "").strip()
    if env_hint and Path(env_hint).is_file():
        return [env_hint]

    # 2. PATH (npm global ou instalador no PATH)
    resolved = shutil.which("claude")
    if resolved:
        if sys.platform == "win32" and resolved.lower().endswith((".cmd", ".bat")):
            return ["cmd.exe", "/c", resolved]
        return [resolved]

    # 3. Locais bem conhecidos (Windows)
    if sys.platform == "win32":
        # Instalador nativo Anthropic
        nativo = Path.home() / ".local" / "bin" / "claude.exe"
        if nativo.is_file():
            return [str(nativo)]
        # Claude Desktop / MSIX — pasta versionada, pega a mais recente
        local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        packages = local_app / "Packages"
        if packages.is_dir():
            for pkg in packages.glob("Claude_*"):
                cc_dir = pkg / "LocalCache" / "Roaming" / "Claude" / "claude-code"
                if not cc_dir.is_dir():
                    continue
                versoes = sorted(
                    (d for d in cc_dir.iterdir() if d.is_dir()),
                    key=lambda p: p.name,
                    reverse=True,
                )
                for v in versoes:
                    exe = v / "claude.exe"
                    if exe.is_file():
                        return [str(exe)]

    return ["claude"]  # fallback — Popen vai falhar com mensagem clara


# NAO cacheie o resultado num global — resolva a cada uso (`resolver_claude_cmd()`).
# Um valor cacheado na importacao do modulo fica preso pra sempre se o Claude
# Desktop estiver no meio de uma atualizacao (ou qualquer outra condicao
# transitoria) no exato instante em que o servidor sobe, exigindo reiniciar o
# processo pra "curar". Resolver por chamada e' barato (checagens de arquivo)
# e se auto-corrige na tentativa seguinte.
resolver_claude_cmd = _resolver_claude_cmd


# Falhas do CLI que NAO sao resposta do modelo. Em `stream-json` o CLI escreve
# esses erros como texto solto no stdout e sai com codigo != 0; sem detecta-los,
# a sessao terminava como "concluida" e o erro em ingles aparecia no lugar da
# peca (foi o que fazia a aba Discussao/elaboracao "parar de funcionar" sem
# mensagem clara).
_RE_FALHA_AUTH = re.compile(
    r"(?i)failed to authenticate"
    r"|oauth (?:session|token) (?:expired|has expired)"
    r"|invalid authentication"
    r"|(?:^|\W)401(?:\W|$)"
)
# Limite de uso do plano. O CLI muda a redacao dessas mensagens de versao pra
# versao, e a lista curta de antes nao pegava a atual ("You've hit your session
# limit - resets 1:30pm"): a elaboracao terminava como "done" com essa frase
# em ingles no lugar da peca. Por isso a ultima alternativa casa a assinatura
# que nenhuma resposta do modelo tem — o "resets <hora>".
_RE_FALHA_CREDITO = re.compile(
    r"(?i)credit balance is too low|insufficient credit|quota exceeded"
    r"|rate limit|(?:usage|session|weekly|hourly|output) limit reached"
    r"|hit your (?:session|usage|weekly|5-hour|five-hour) limit"
    r"|(?:session|usage|weekly) limit (?:reached|exceeded)"
    r"|upgrade to increase your (?:usage )?limit"
    r"|out of (?:usage|credits|credit)"
    r"|limit\b.{0,40}?\bresets? \d{1,2}(?::\d{2})?\s*(?:am|pm)"
)

# "resets 1:30pm (America/Fortaleza)" — a hora de reset e' a informacao que o
# Defensor precisa pra saber quando clicar de novo.
_RE_RESET = re.compile(
    r"(?i)resets?\s+("
    r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day\s+)?"   # limite semanal
    r"(?:at\s+)?"
    r"\d{1,2}(?::\d{2})?\s*(?:am|pm)?"
    r"(?:\s*\([^)]{1,40}\))?"                                # fuso, quando vem
    r")"
)

MSG_FALHA_AUTH = (
    "Falha de autenticação do Claude CLI — não há sessão de login válida. "
    "Para resolver: dê duplo clique no atalho \"Login Claude (painel)\" na área "
    "de trabalho (ou rode `login-claude.bat` na pasta do painel) e conclua a "
    "autenticação no navegador. NÃO abra como administrador — o painel roda sem "
    "elevação. Depois feche e reabra o painel para o subprocesso usar a "
    "credencial nova."
)


def detectar_falha_cli(returncode: int | None, texto: str) -> str:
    """Mensagem acionavel se a saida do CLI indicar falha de infraestrutura
    (autenticacao, limite de uso) em vez de resposta do modelo. "" se estiver ok.
    """
    saida = texto or ""
    if _RE_FALHA_AUTH.search(saida):
        return MSG_FALHA_AUTH
    if _RE_FALHA_CREDITO.search(saida):
        m = _RE_RESET.search(saida)
        # A redacao do reset varia ("1:30pm (America/Fortaleza)", "Monday 9am",
        # "at 4pm"), entao entra como citacao em vez de virar frase em portugues.
        quando = f" Reset informado pelo CLI: {m.group(1).strip()}." if m else ""
        return (
            "Limite de uso do plano atingido: o Claude CLI recusou a "
            f"requisição, então NENHUMA peça foi gerada.{quando} Quando "
            "resetar, clique em Elaborar novamente. Nada do que já estava na "
            "pasta do PAJ foi perdido. "
            f"Mensagem do CLI: {saida.strip()[-200:]}"
        )
    if returncode not in (0, None):
        trecho = saida.strip()[:200] or "(sem saida)"
        return f"O Claude CLI encerrou com código {returncode}: {trecho}"
    return ""


def _tem_peca_gerada(pasta: Path) -> bool:
    """True se a pasta do PAJ tem ao menos um arquivo-peça (fora os de sistema).

    Mesma regra de `ler_elaboracao_disco`: qualquer arquivo na raiz que não
    esteja em `ARQUIVOS_NAO_PECAS` (IGNORAR) é produto do defensor/Claude."""
    try:
        return any(
            x.is_file() and x.name not in ARQUIVOS_NAO_PECAS
            for x in pasta.iterdir()
        )
    except Exception:
        return False


def _formatar_plano_aprovado(plano: dict) -> str:
    """Formata um plano de atuacao (aprovado no fluxo Planejar) como bloco de texto
    para injetar na instrucao do Claude. Vazio se o plano nao tiver conteudo util."""
    if not plano or not isinstance(plano, dict):
        return ""
    linhas = ["PLANO DE ATUACAO APROVADO PELO DEFENSOR (SIGA-O):"]
    if plano.get("tipo_atuacao"):
        linhas.append(f"- Tipo de atuacao: {plano['tipo_atuacao']}")
    if plano.get("tipo_peca"):
        linhas.append(f"- Peca a elaborar: {plano['tipo_peca']}")
    if plano.get("decisao_recorrida_descricao"):
        linhas.append(f"- Decisao/ato sob analise: {plano['decisao_recorrida_descricao']}")
    if plano.get("decisao_recorrida_arquivo"):
        linhas.append(f"- Arquivo da decisao: {plano['decisao_recorrida_arquivo']}")
    if plano.get("analise_completa"):
        linhas.append(f"- Analise do Defensor: {plano['analise_completa']}")
    fontes = plano.get("fontes_auxiliares") or []
    if fontes:
        linhas.append("- Fontes a considerar:")
        for fonte in fontes:
            ref = fonte.get("ref", "")
            tipo = fonte.get("tipo", "")
            arq = fonte.get("arquivo", "")
            sufixo = f" [arquivo: {arq}]" if arq else ""
            linhas.append(f"    - ({tipo}) {ref}{sufixo}")
    alertas = plano.get("alertas") or []
    if alertas:
        linhas.append("- Alertas:")
        for a in alertas:
            linhas.append(f"    - {a}")
    linhas.append(
        "\nEste plano foi revisado e aprovado por um humano. Respeite o tipo de "
        "atuacao e a peca definidos; nao reabra a decisao se o Defensor ja optou "
        "por nao atuar ou arquivar."
    )
    return "\n".join(linhas) + "\n\n"


def _montar_instrucao(
    paj_pasta,
    prompt_content: str,
    skill_slug: str | None,
    plano: dict | None = None,
) -> str:
    """Monta o prompt inicial enviado ao Claude Code CLI.

    Se `skill_slug` vier preenchida, instrui o Claude a invocar a skill correspondente
    do Oficio Geral (ex: `/peticoes-iniciais`). A skill ja sabe estrutura, tom,
    checklists e bases — o painel so fornece o contexto do PAJ e pede o texto pronto.

    Se `skill_slug` vier None (fallback), mantem o comportamento antigo de decisao
    autonoma pelo Claude.

    Se `plano` vier preenchido (fluxo Planejar -> aprovar -> elaborar), o plano
    aprovado pelo Defensor e' injetado no topo para guiar a elaboracao.
    """
    bloco_plano = _formatar_plano_aprovado(plano) if plano else ""
    if skill_slug:
        desc = skill_descricao(skill_slug)
        cabecalho = (
            f"Use a skill `/{skill_slug}` do workspace Oficio Geral para elaborar "
            f"o que for cabivel para este PAJ.\n"
            f"  Skill escolhida: {desc}\n\n"
            "A skill ja contem as regras de estrutura, tom, checklists e bases de "
            "conhecimento. Siga-as. Siga tambem todas as regras gerais do "
            "`CLAUDE.md` do workspace (terminologia DPU, estilo, endereçamento, "
            "assinatura etc).\n\n"
            "Nao me pergunte nada; execute a skill ate o fim com base no contexto "
            "do PAJ fornecido abaixo. Se faltar informacao critica, faca a melhor "
            "hipotese e sinalize no resumo final.\n\n"
        )
        tipo_saida = "<TIPO DE PRODUTO — conforme a skill>"
    else:
        cabecalho = (
            "Analise o PAJ abaixo seguindo o `CLAUDE.md` deste workspace (Oficio Geral) "
            "e **decida autonomamente** (sem me perguntar) o proximo passo processual adequado: "
            "despacho no SISDPU, peticao, recurso, manifestacao, memoriais, contestacao, etc. "
            "Use as skills/bases de conhecimento disponiveis no workspace conforme apropriado.\n\n"
            "**NUNCA se limite a um despacho determinando remessa a assessoria (ou a outrem) "
            "quando o caso exigir a elaboracao de uma peca.** Se a conclusao for que cabe "
            "peticao/manifestacao/recurso/contestacao etc., REDIJA a peca por completo agora "
            "mesmo — despacho so' e' produto final quando NAO ha' nenhuma peca judicial a "
            "fazer (mero acompanhamento, ciencia, arquivamento). NAO aguarde a assessoria: "
            "se ela ja' entregou algo, leia e use; se ainda nao entregou e a peca e' cabivel, "
            "a minuta e' sua.\n\n"
            "**PAJ DE PRIMEIRO CONTATO:** se o PAJ chega ao defensor pela primeira vez "
            "(abertura, redistribuicao, PAJ novo na caixa), analise o MERITO antes de decidir "
            "— qualifique o direito pleiteado, confronte os requisitos legais um a um com o "
            "que os documentos provam, levante obstaculos (prescricao, prévio requerimento, "
            "coisa julgada, competencia, tese contraria) e conclua VIAVEL / AINDA NAO VIAVEL "
            "(dizendo qual prova falta) / INVIAVEL. Consulte a base da CCR/DPU em "
            "`~/.claude/conhecimento-dpu/` (via `INDICE.md`), citando apenas o que estiver "
            "literalmente nela. Sendo viavel, produza a peca.\n\n"
        )
        tipo_saida = "[DESPACHO | PETICAO | RECURSO | MANIFESTACAO | OFICIO | ORIENTACAO | OUTRO — <tipo>]"

    return (
        bloco_plano
        + cabecalho
        + "**OBRIGATORIO**: produzir o TEXTO da peca/despacho/oficio/orientacao, em "
        "linguagem apropriada, pronto pra copiar no SISDPU / protocolar / expedir. "
        "Nao basta dizer o que fazer — redija o produto final.\n\n"
        "**REDACAO — MODO DPU (em vigor):** o `CLAUDE.md` deste ambiente traz o "
        "registro, as regras e os conectivos liberados. SIGA-O. Acrescentos:\n\n"
        "1. TAMANHO e o erro que eu mais cometo: os despachos dele tem 245 "
        "palavras de media, os meus tinham 973, quatro vezes mais. Caso SIMPLES "
        "(um requisito objetivo resolve, materia pacificada, arquivamento padrao, "
        "diligencia, mero expediente): 200 a 300 palavras, paragrafo de UMA "
        "frase, ~21 palavras por frase. Caso TRABALHOSO (requisitos a confrontar "
        "um a um, prova a conferir, primeiro contato com merito): 400 a 700 "
        "palavras, 2 a 3 frases por paragrafo. Na duvida, o mais seco. Diga o "
        "nivel no resumo final.\n"
        "2. DESPACHO NAO TEM TITULO DE SECAO NENHUM, nem na forma numerada "
        "embutida no paragrafo ('1. DO ESCLARECIMENTO. Esclarecido que...'). Eu "
        "divido 20 vezes mais que ele. Peca judicial leva no maximo quatro "
        "titulos romanos.\n"
        "3. CONECTIVO: eu uso dez vezes menos que ele. Use 'Outrossim', 'Com "
        "efeito', 'Todavia', 'Nesse cenario', 'Em resumo' sem medo.\n"
        "4. Use o bloco `Atendimento:` sempre que a parte tiver de ser informada: "
        "o que dizer a ela em LINGUAGEM DE LEIGO, o que a Defensoria vai fazer, "
        "os prazos dela (10 dias uteis para advogado, 10 dias corridos para "
        "recorrer da propria Defensoria, quando couber) e a orientacao pratica. "
        "Esta em 29% dos despachos dele e em nenhum dos meus.\n"
        "5. No despacho, data/valor/prazo exatos, mas SEM ancora de documento: "
        "quem le tem o PAJ aberto. Em PECA JUDICIAL a ancora e obrigatoria, "
        "colada ao fato, com ID no PJe e mov. no SISDPU, nunca 'fl.'.\n"
        "6. NAO leia `~/.claude/manual-redacao.md` para despacho: o CLAUDE.md "
        "basta. Abra-o so' para peca judicial.\n\n"
        "**EMBARGOS A EXECUCAO FISCAL — criterio antes da minuta (regra do "
        "Defensor, 20/09/2026):** so' redija embargos se houver tese REALMENTE "
        "viavel. Verifique uma a uma e diga no resumo o que examinou: prescricao "
        "pelas datas de inscricao das CDAs; legitimidade do corresponsavel, que "
        "so' existe se o devedor principal for pessoa juridica com personalidade "
        "autonoma (razao social do CNPJ igual ao nome da pessoa natural, sem "
        "LTDA/ME/EIRELI, e EMPRESARIO INDIVIDUAL: CNPJ e CPF sao o mesmo sujeito "
        "e o art. 135, III, do CTN nao tem objeto); nulidade da CDA; excesso de "
        "execucao; e impenhorabilidade, que NAO e tese nova se ja foi ventilada e "
        "rejeitada antes.\n"
        "NAO havendo tese viavel, o produto NAO e peticao: e DESPACHO sustentando "
        "a inviabilidade tese por tese, ressaltando as dificuldades inerentes a "
        "CURADORIA ESPECIAL (o curador nao tem nem pode ter contato com o "
        "executado revel citado por edital, nao dispoe dos documentos nem conhece "
        "a origem dos creditos), registrando o prazo dos embargos e a "
        "consequencia de deixa-lo correr, e manifestando ciencia. A negativa "
        "geral (Sumula 196 do STJ) e faculdade, nao dever de embargar.\n\n"
        "**HONORARIOS EM FAVOR DA DPU (so' em CUMPRIMENTO DE SENTENCA):** se a "
        "peca for de cumprimento de sentenca e houver honorarios devidos a' DPU, "
        "o pedido tem tres partes obrigatorias: (1) pagamento conforme o RITO "
        "aplicavel, dizendo QUAL e' — RPV se o credito estiver no limite legal, "
        "PRECATORIO se exceder, ou deposito judicial/pagamento espontaneo (art. "
        "523 do CPC) se o executado for particular; nao peca 'RPV ou precatorio' "
        "genericamente; (2) pedido EXPRESSO de TRANSFERENCIA das quantias para a "
        "conta do Fundo de Aparelhamento APOS o deposito em conta judicial — sem "
        "esse pedido o valor nao chega ao Fundo; (3) os dados abaixo, transcritos "
        "literalmente:\n"
        "    DADOS PARA DEPOSITO\n"
        "    Banco: Caixa Economica Federal\n"
        "    Operacao: 1292\n"
        "    Agencia n 0002\n"
        "    Conta Corrente n 576952567-0\n"
        "    CNPJ n 58.053.223/0001-05\n"
        "Em QUALQUER outra peca (agravo, apelacao, contestacao, embargos, "
        "manifestacao), peca a condenacao em honorarios em favor da DPU com "
        "reversao ao Fundo (art. 4, XXI, da LC 80/94), mas NAO transcreva a "
        "conta — ali o credito ainda nao existe.\n\n"
        "**DENOMINACAO DA ACAO:** quando a peca NOMEIA a acao proposta (caso "
        "tipico da peticao inicial, entre a qualificacao do autor e o 'em face "
        "de ...'), escreva essa linha com o marcador `[DENOMINACAO]` — o "
        "gerador a renderiza em CAIXA destacada: centralizada, negrito, quatro "
        "bordas externas e sombreamento cinza. Ex.: `[DENOMINACAO] ACAO DE "
        "RESTABELECIMENTO DE BENEFICIO DE PRESTACAO CONTINUADA (BPC/LOAS)`. "
        "Uma linha so', em caixa alta, sem ponto final. NAO use em peticao "
        "intercorrente (essas nao levam nome nenhum).\n\n"
        "**ASSINATURA:** no FIM da peca nao escreva assinatura — o gerador "
        "acrescenta sozinho (centralizada, nome numa linha e cargo na "
        "seguinte). Na PAGINA DE APRESENTACAO das pecas recursais (apelacao, "
        "contrarrazoes, agravo), que assinam a folha de interposicao, use o "
        "marcador `[ASSINATURA]` numa linha sozinha. NAO escreva o nome e o "
        "cargo em linhas seguidas na mao: o processador junta linhas "
        "consecutivas e eles saiam grudados numa linha justificada.\n\n"
        "**AGRAVO DE INSTRUMENTO — sempre DUAS pecas, em DOIS arquivos:**\n"
        "1. O agravo em si, com DUAS FOLHAS: a 1a de interposicao, endereçada "
        "AO EXMO. DESEMBARGADOR RELATOR do TRF5 (com a dispensa de documentos "
        "do art. 1.017, §5º, do CPC); depois o marcador `[NOVA PAGINA]` numa "
        "linha sozinha; e a 2a folha com as RAZOES, endereçada a' Corte "
        "(`EGRÉGIO TRIBUNAL REGIONAL FEDERAL DA 5ª REGIÃO,` / `EMINENTES "
        "DESEMBARGADORES FEDERAIS,` / `DOUTO RELATOR.`), seguida de "
        "Autos na origem / Agravante / Agravado.\n"
        "2. Uma peticao curta AO JUIZO DE ORIGEM informando a interposicao do "
        "agravo e pugnando pela retratacao (art. 1.018, §1º, do CPC), em "
        "arquivo separado (ex: `peticao_informa_agravo.txt`).\n"
        "A estrutura completa, com as secoes e os pedidos de praxe, esta na "
        "skill `formatacao-docx` (secao \"Agravo de Instrumento\") — SIGA-A.\n\n"
        "**FORMATACAO — depende do produto:**\n"
        "- **DESPACHO** (e qualquer texto para colar no DPU Digital / SISDPU): "
        "TEXTO PURO. NADA de `*`, `**`, `#`, `##`, `>`, `-` de lista, backticks "
        "ou tabelas — o editor da DPU nao interpreta esses caracteres e eles "
        "aparecem literalmente no despacho. Para enfase use CAIXA ALTA; para "
        "enumerar, 'a)', 'b)' ou '1.' no corpo do paragrafo.\n"
        "- **PECA JUDICIAL** (peticao, manifestacao, recurso, contestacao, "
        "memoriais): mantenha os marcadores normais (`##`, `###`, `>`, "
        "`**negrito**`) — o gerador de DOCX/PDF depende deles.\n\n"
        "**REVISAO DE MINUTA DA ASSESSORIA**: se o contexto abaixo tiver a secao "
        "\"Minuta da assessoria aguardando revisao do Defensor\", o produto e' a "
        "MINUTA CORRIGIDA. Entao: (1) confira a minuta contra os dados do PAJ "
        "(peca cabivel, partes, numero do processo, juizo, pedidos, prazo, "
        "fundamentos); (2) liste no resumo final os erros encontrados, citando o "
        "trecho de cada um; (3) salve o .txt com o texto INTEGRAL da peca ja "
        "corrigida — nao um diff, nao apenas os trechos alterados, e nao apenas "
        "comentarios. Preserve o que estava correto e reescreva so' o que estava "
        "errado. Se a minuta nao estiver acessivel (apenas link do editor do PJe, "
        "ou arquivo ausente), NAO invente o teor: diga que precisa do texto da "
        "minuta e pare.\n\n"
        f"Salve o(s) arquivo(s) gerado(s) direto em `{paj_pasta}\\`.\n\n"
        "**NOME DO ARQUIVO — inclua o NOME e SOBRENOME da parte.** Monte o nome "
        "como `<tipo da peca> <Nome Sobrenome>.txt`, para o arquivo ser "
        "reconhecivel sem abrir. Exemplos: "
        "`Manifestacao Impugnacao Laudo Clarissa Lopes.txt`, "
        "`Peticao Cumprimento de Sentenca Joao Silva.txt`, "
        "`Recurso Inominado Maria Souza.txt`, "
        "`Despacho Arquivamento Pedro Alves.txt`.\n"
        "Regras do nome: use o PRIMEIRO nome e o PRIMEIRO sobrenome do "
        "assistido/parte (nao o nome completo inteiro, que fica longo demais); "
        "espacos e acentos sao permitidos; NAO use os caracteres "
        "`\\ / : * ? \" < > | # &` (quebram caminho ou URL). Se o produto for "
        "DESPACHO, comece o nome com a palavra `Despacho` — o painel usa esse "
        "prefixo para separar despachos de pecas judiciais nas abas.\n\n"
        f"**NAO** salve dentro de `{paj_pasta}\\pecas\\` — essa subpasta e' "
        "reservada aos anexos baixados do SISDPU pelo sincronizador; um "
        "arquivo salvo ali nao aparece na aba Pecas do painel. "
        "Esforco proporcional ao produto. "
        "Geracao de .docx/.pdf e feita depois, pelo botao do painel.\n\n"
        "Ao final, apresente um **RESUMO ESTRUTURADO CURTO**:\n\n"
        "```\n"
        f"## Produto: {tipo_saida}\n\n"
        "### Justificativa\n"
        "<3-5 linhas explicando POR QUE este e o produto cabivel agora>\n\n"
        "### Arquivos gerados\n"
        "- <caminho absoluto do arquivo .txt gerado>\n\n"
        "### Pontos-chave\n"
        "- <bullet 1>\n"
        "- <bullet 2>\n\n"
        "### Se discordar\n"
        "Me diga o que mudar e eu refaco.\n"
        "```\n\n"
        "**NAO REPITA O TEXTO DA PECA NESTE RESUMO.** A peca ja' esta no "
        "arquivo, aparece na aba Pecas do painel e pode ser aberta ou "
        "convertida em DOCX/PDF por la'. Reproduzir o texto completo aqui "
        "significa GERAR A PECA DUAS VEZES — em peca longa isso dobrava o "
        "tempo de espera do Defensor sem entregar nada de novo. Cite trecho "
        "so' se for indispensavel para explicar uma escolha (2-3 linhas).\n\n"
        "Se eu responder com discordancia, refaca conforme instruido.\n\n"
        "---\n\n"
        f"{prompt_content}"
    )


class ChatSession:
    """Sessao interativa com Claude Code CLI."""

    def __init__(self, paj_norm: str, skill_slug: str | None = None):
        self.paj_norm = paj_norm
        # Skill do Oficio Geral a ser invocada (ex: "peticoes-iniciais").
        # Se None, o Claude decide autonomamente (comportamento antigo).
        self.skill_slug: str | None = skill_slug if skill_slug and skill_valida(skill_slug) else None
        self.output_queue: queue.Queue[dict] = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._alive = False
        # Estado pra UI de background:
        # "idle" | "running" | "done" | "error"
        self.status: str = "idle"
        self.last_action: str = ""       # "Usando Glob", "Escrevendo peca", etc.
        self.accumulated_text: str = ""  # texto acumulado da resposta atual
        self.summary: str = ""           # resumo final (ultima resposta do Claude)
        self.error: str = ""

    def _start_subprocess(self) -> bool:
        """Inicia o subprocess Claude Code CLI e a thread leitora.

        Retorna True se o processo foi aberto com sucesso; em caso de falha,
        preenche self.error e enfileira os eventos de erro/done.
        """
        claude_cmd = resolver_claude_cmd()
        cmd = [
            *claude_cmd,
            "-p",
            "--verbose",
            "--output-format", "stream-json",
            "--input-format", "stream-json",
            "--include-partial-messages",
            "--permission-mode", "bypassPermissions",
        ]
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(OFICIO_GERAL),
            )
            self._alive = True
            self._reader_thread = threading.Thread(target=self._read_output, daemon=True)
            self._reader_thread.start()
            return True
        except FileNotFoundError:
            self.status = "error"
            self.error = (
                f"Comando Claude CLI não encontrado (tentou: {' '.join(claude_cmd)}). "
                "Verifique se o `claude` está instalado e no PATH do processo do servidor."
            )
            self.output_queue.put({"type": "error", "text": self.error})
            self.output_queue.put({"type": "done"})
            return False
        except Exception as e:
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
            self.output_queue.put({"type": "error", "text": self.error})
            self.output_queue.put({"type": "done"})
            return False

    @staticmethod
    def _carregar_plano_aprovado(paj_pasta: Path) -> dict | None:
        """Le o plano aprovado (plano_elaboracao.json) da pasta do PAJ, se existir.

        Retorna o dict do plano (campo `plano` do payload) ou None. Nunca levanta —
        elaboracao sem plano e' o caminho padrao e deve continuar funcionando.
        """
        f = paj_pasta / "plano_elaboracao.json"
        if not f.exists():
            return None
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
            plano = payload.get("plano") if isinstance(payload, dict) else None
            return plano if isinstance(plano, dict) else None
        except Exception:
            return None

    def start(self) -> bool:
        """Inicia o subprocess Claude Code em modo stream-json."""
        prompt_path = PAJS_DIR / self.paj_norm / "PROMPT_MAX.md"
        if not prompt_path.exists():
            self.output_queue.put({"type": "error", "text": "PROMPT_MAX.md nao encontrado."})
            self.output_queue.put({"type": "done"})
            return False

        if not self._start_subprocess():
            return False

        # Envia PROMPT_MAX como prompt inicial
        prompt_content = prompt_path.read_text(encoding="utf-8", errors="replace")
        paj_pasta = PAJS_DIR / self.paj_norm
        # Plano aprovado no fluxo Planejar (se houver) — guia a elaboracao.
        plano = self._carregar_plano_aprovado(paj_pasta)
        instrucao = _montar_instrucao(
            paj_pasta=paj_pasta,
            prompt_content=prompt_content,
            skill_slug=self.skill_slug,
            plano=plano,
        )
        # NAO fecha stdin — mantem aberto pra multi-turn
        self.status = "running"
        self.last_action = "iniciando..."
        self.accumulated_text = ""
        self.send_message(instrucao)
        return True

    def start_correcao(self, correcao: str) -> bool:
        """Reinicia a sessao para aplicar uma correcao ao produto anterior.

        Como o Claude CLI sai apos cada rodada (-p), este metodo cria um novo
        subprocess e envia um prompt que instrui o Claude a:
          1. Ler os arquivos ja gerados na pasta do PAJ
          2. Aplicar a correcao solicitada
          3. Salvar a versao corrigida
          4. Apresentar o RESUMO ESTRUTURADO padrao
        """
        if not self._start_subprocess():
            return False

        paj_pasta = PAJS_DIR / self.paj_norm
        instrucao = (
            f"Voce elaborou anteriormente uma peca/despacho para o PAJ {self.paj_norm}. "
            f"O(s) arquivo(s) gerado(s) estao salvos em `{paj_pasta}\\`.\n\n"
            f"O defensor solicita a seguinte **CORRECAO**:\n\n"
            f"{correcao}\n\n"
            f"Por favor:\n"
            f"1. Leia o(s) arquivo(s) ja gerados em `{paj_pasta}\\` para recuperar "
            f"   o texto elaborado anteriormente\n"
            f"2. Aplique a correcao solicitada\n"
            f"3. Salve a versao atualizada sobrescrevendo o arquivo anterior\n"
            f"4. Apresente o **RESUMO ESTRUTURADO** ao final no mesmo formato padrao\n\n"
            f"Siga o `CLAUDE.md` do workspace Oficio Geral (terminologia DPU, estilo, "
            f"assinatura etc). Nao pergunte nada — refaca diretamente."
        )
        self.status = "running"
        self.last_action = "aplicando correção..."
        self.accumulated_text = ""

        # Registra ANTES de enviar — assim o evento aparece no historico mesmo
        # que a sessao falhe na sequencia. O `elaborar` posterior cobrira o
        # resultado.
        with contextlib.suppress(Exception):
            historico.registrar(
                self.paj_norm,
                "correcao",
                texto=correcao,
            )

        self.send_message(instrucao)
        return True

    def send_message(self, text: str):
        """Envia mensagem do usuario pro Claude via stdin (formato stream-json)."""
        if not self.proc or not self._alive:
            return
        msg = {
            "type": "user",
            "message": {"role": "user", "content": text},
        }
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        try:
            self.proc.stdin.write(line.encode("utf-8"))
            self.proc.stdin.flush()
            # Reset estado pra novo turno
            self.status = "running"
            self.last_action = "processando mensagem..."
            self.accumulated_text = ""
        except (BrokenPipeError, OSError):
            self._alive = False
            self.status = "error"
            self.error = "Subprocess morto."

    def _read_output(self):
        """Le stdout do Claude e coloca eventos na queue."""
        try:
            for line in iter(self.proc.stdout.readline, b""):
                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                    parsed = self._parse_event(event)
                    if parsed:
                        self.output_queue.put(parsed)
                except json.JSONDecodeError:
                    self.output_queue.put({"type": "text", "text": text + "\n"})

            self.proc.wait()
            self._alive = False
            # O CLI em stream-json emite falha de autenticacao como TEXTO no
            # stdout e sai com codigo != 0 — sem esta checagem a sessao era
            # marcada como "done" com sucesso e a mensagem de erro em ingles
            # aparecia no lugar da peca produzida.
            falha = detectar_falha_cli(self.proc.returncode, self.accumulated_text)
            if falha:
                self.status = "error"
                self.error = falha
                self.summary = ""
                self.output_queue.put({"type": "error", "text": falha})
            self.output_queue.put({"type": "done"})
        except Exception as e:
            self.output_queue.put({"type": "error", "text": str(e)})
            self.output_queue.put({"type": "done"})
            self._alive = False
        finally:
            # Subprocess morreu — libera slot e promove proximo da fila
            with contextlib.suppress(Exception):
                _process_queue()

    def _parse_event(self, event: dict) -> dict | None:
        """Converte evento stream-json do Claude em formato simplificado pro frontend."""
        etype = event.get("type", "")

        # stream_event — wrapper dos eventos da API Anthropic
        if etype == "stream_event":
            inner = event.get("event", {})
            inner_type = inner.get("type", "")

            # Texto parcial (streaming em tempo real)
            if inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta":
                    chunk = delta.get("text", "")
                    self.accumulated_text += chunk
                    self.last_action = "escrevendo resposta..."
                    return {"type": "text", "text": chunk}

            # Tool use start
            if inner_type == "content_block_start":
                block = inner.get("content_block", {})
                if block.get("type") == "tool_use":
                    tool_name = block.get("name", "?")
                    self.last_action = f"usando {tool_name}"
                    return {"type": "tool", "text": f"[usando: {tool_name}]"}

            # Tool use input — captura o comando/arquivo sendo acessado
            if inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "input_json_delta":
                    # Concatena partial inputs (Claude vai mandando em chunks)
                    partial = delta.get("partial_json", "")
                    # Simples heuristica: se parece com comando/file path, atualiza last_action
                    if partial and len(partial) > 3:
                        snippet = partial.strip().strip('{},:"').strip()[:60]
                        if snippet:
                            self.last_action = (self.last_action or "") + " " + snippet
                            self.last_action = self.last_action[-120:]  # limita tamanho

            return None

        # Resultado final de um turno (Claude terminou de responder)
        if etype == "result":
            result_text = event.get("result", "")
            if isinstance(result_text, dict):
                result_text = result_text.get("text", "")
            # Falha de infraestrutura do CLI (login expirado, limite de uso) chega
            # AQUI, como texto do proprio `result` — a sessao segue viva, entao a
            # deteccao tem que ser neste ponto, e nao no encerramento do processo.
            # Sem isso o turno era marcado como "done" e o erro em ingles ficava
            # no lugar da peca produzida.
            bruto = result_text if isinstance(result_text, str) else ""
            falha = detectar_falha_cli(0, f"{self.accumulated_text}\n{bruto}")
            if falha:
                self.status = "error"
                self.error = falha
                self.summary = ""
                self.last_action = "falha de autenticação/limite do Claude CLI"
                self._persist()
                return {"type": "error", "text": falha}

            # Guarda o texto acumulado como summary (e o texto final desse turno)
            if self.accumulated_text.strip():
                self.summary = self.accumulated_text
            elif isinstance(result_text, str) and result_text:
                self.summary = result_text
            self.status = "done"
            self.last_action = "aguardando sua resposta"
            session_id = event.get("session_id", "")[:8]
            # Persiste em disco pra sobreviver reinicio do servidor
            self._persist()
            return {
                "type": "result",
                "text": result_text if isinstance(result_text, str) else "",
                "session_id": session_id,
            }

        # assistant_full — ignora (ja temos via deltas)
        if etype == "assistant":
            return None

        # System events — ignora
        if etype == "system":
            return None

        # rate_limit_event — ignora
        if etype == "rate_limit_event":
            return None

        return None

    def is_alive(self) -> bool:
        return self._alive

    def stop(self):
        """Encerra o subprocess."""
        self._alive = False
        if self.proc:
            with contextlib.suppress(Exception):
                self.proc.terminate()

    def _persist(self) -> None:
        """Salva status + summary em PAJs/{paj}/elaboracao.json e registra
        evento no historico.jsonl.

        Assim o resultado sobrevive a reinicio do servidor — a UI le do disco
        quando nao ha sessao em memoria. O historico mantem o rastro de
        TODAS as elaboracoes/correcoes feitas no PAJ ao longo do tempo,
        diferente do elaboracao.json que so guarda a ultima.
        """
        try:
            pasta = PAJS_DIR / self.paj_norm
            if not pasta.exists():
                return
            import datetime as _dt
            data = {
                "status": self.status,
                "summary": self.summary,
                # Sem gravar o `error`, uma falha de infraestrutura (login,
                # limite de uso) virava na UI um "erro" sem motivo nenhum
                # depois que a sessao em memoria morria.
                "error": self.error,
                "last_action": self.last_action,
                "concluido_em": _dt.datetime.now().isoformat(),
            }
            (pasta / "elaboracao.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

        # Historico estruturado — best-effort, nao bloqueia o fluxo se falhar.
        with contextlib.suppress(Exception):
            historico.registrar(
                self.paj_norm,
                "elaborar",
                skill=self.skill_slug or "",
                status=self.status,
                resumo=historico._primeira_linha_util(self.summary),
            )

        # Fase 4 do fluxo (docs/FLUXO_DE_TRABALHO.md): elaboração concluída com
        # peça/despacho/mensagem gravada na pasta → tira o evento da Caixa de
        # triagem. Idempotente; uma movimentação nova reabre o evento no sync.
        with contextlib.suppress(Exception):
            if self.status == "done" and _tem_peca_gerada(PAJS_DIR / self.paj_norm):
                from services.triagem_service import concluir_evento

                if concluir_evento(self.paj_norm):
                    historico.registrar(
                        self.paj_norm, "triagem_concluida", motivo="elaboracao"
                    )


def ler_elaboracao_disco(paj_norm: str) -> dict | None:
    """Le o estado persistido da elaboracao (ou None se nao existe).

    Precedencia:
    1. elaboracao.json (salvo automaticamente por _persist — tem resumo completo)
    2. Se nao tem elaboracao.json mas TEM arquivo gerado (despacho.txt, *.docx,
       *.pdf na raiz), considera "done" sem resumo detalhado.
    """
    try:
        pasta = PAJS_DIR / paj_norm
        if not pasta.exists():
            return None

        f = pasta / "elaboracao.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))

        # Fallback: tem arquivo gerado na raiz?
        # ARQUIVOS_NAO_PECAS reusa a constante canonica `IGNORAR` definida em
        # paj_service — fonte unica de verdade. Sem isso, a lista local ficava
        # defasada e produzia falsos avisos em PAJs recem-sincronizados que
        # tinham sisdpu.txt/NOTAS.md mas nenhuma peça gerada pela IA.
        gerados = [
            x for x in pasta.iterdir()
            if x.is_file() and x.name not in ARQUIVOS_NAO_PECAS
        ]
        if gerados:
            nomes = ", ".join(sorted(x.name for x in gerados))
            return {
                "status": "done",
                "last_action": "arquivos já gerados",
                "summary": (
                    "(Resumo detalhado não está disponível — este PAJ foi "
                    "elaborado antes da implementação da persistência em disco.)\n\n"
                    f"Arquivos gerados na pasta: {nomes}\n\n"
                    "Abra a aba 'Peças Geradas' do PAJ pra ver/baixar os arquivos, "
                    "ou clique em 'Elaborar' de novo pra regerar o resumo."
                ),
                "concluido_em": "",
            }
        return None
    except Exception:
        return None


# Sessoes ativas (in-memory, single user) + fila de espera
_sessions: dict[str, ChatSession] = {}
_queue: list[str] = []  # paj_norms aguardando slot livre
MAX_PARALLEL = 5


def _count_running() -> int:
    return sum(1 for s in _sessions.values() if s.status == "running")


def _process_queue() -> None:
    """Promove proximos da fila enquanto houver slots livres."""
    while _queue and _count_running() < MAX_PARALLEL:
        next_paj = _queue.pop(0)
        session = _sessions.get(next_paj)
        if not session:
            continue
        # Promove: inicia o subprocess agora
        session.status = "idle"  # reset pra start() funcionar
        session.start()


def get_or_create_session(paj_norm: str, skill_slug: str | None = None) -> ChatSession:
    """Retorna sessao existente ou cria nova (sem iniciar)."""
    if paj_norm in _sessions and _sessions[paj_norm].is_alive():
        return _sessions[paj_norm]
    if paj_norm in _sessions:
        _sessions[paj_norm].stop()
    session = ChatSession(paj_norm, skill_slug=skill_slug)
    _sessions[paj_norm] = session
    return session


def start_or_queue(paj_norm: str, skill_slug: str | None = None) -> dict:
    """Inicia sessao se houver slot, senao enfileira. Retorna status atual."""
    existing = _sessions.get(paj_norm)
    # Se ja esta rodando, nao faz nada
    if existing and existing.is_alive() and existing.status == "running":
        return {"status": "running", "last_action": existing.last_action}
    # Se esta na fila, permanece
    if paj_norm in _queue:
        return {"status": "queued", "last_action": "aguardando slot"}

    # Recria sessao limpa (com a skill escolhida — pode ser diferente da anterior)
    if existing:
        existing.stop()
    session = ChatSession(paj_norm, skill_slug=skill_slug)
    _sessions[paj_norm] = session

    if _count_running() >= MAX_PARALLEL:
        # Enfileira
        session.status = "queued"
        session.last_action = f"aguardando slot (fila: {len(_queue) + 1})"
        _queue.append(paj_norm)
        return {"status": "queued", "last_action": session.last_action}

    # Ha slot livre — inicia imediatamente
    session.start()
    return {"status": session.status, "last_action": session.last_action}


def stop_session(paj_norm: str):
    if paj_norm in _queue:
        _queue.remove(paj_norm)
    if paj_norm in _sessions:
        _sessions[paj_norm].stop()
        del _sessions[paj_norm]
    _process_queue()


def get_stats() -> dict:
    return {
        "running": _count_running(),
        "queued": len(_queue),
        "max_parallel": MAX_PARALLEL,
    }
