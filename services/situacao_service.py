"""Situação do PAJ — análise FIRAC EXECUTADA (o resultado, não o prompt).

A aba "Situação do PAJ" exibe o conteúdo de `SITUACAO.md`: um relatório curto
no molde definido pelo Defensor (resumo da demanda → razão do encaminhamento e
análise → sugestão de skill/plugin → sugestão de despacho). O relatório é
produzido pelo Claude CLI em modo headless (mesmo padrão do planejar_service —
sem API paga), usando como contexto o `prompt_builder.montar_contexto()`.

Após gravar SITUACAO.md, o PROMPT_MAX.md é regenerado — ele passa a ABRIR com
essa análise (ordem definida pelo Defensor: primeiro a situação, depois o
restante do prompt max para a elaboração).
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import subprocess
import threading

from config import OFICIO_UNIDADE, PAJS_DIR
from services.chat_service import resolver_claude_cmd
from services.planejar_service import _env_sem_claudecode, classificar_erro_claude
from services.prompt_builder import SITUACAO_FILE, gerar_prompt_max, montar_contexto

logger = logging.getLogger("situacao")

# Uma análise por PAJ por vez (duplo clique não pode abrir dois Claude).
_em_andamento: set[str] = set()
_lock = threading.Lock()

# --- Fila automática (análise sem botão) --------------------------------------
# O sincronizador enfileira cada PAJ com evento de triagem NOVO; um worker
# único processa em série (1 Claude CLI por vez) em segundo plano, sem
# atrasar a sincronização. Dedup: PAJ já na fila ou em análise não re-entra.
_fila_auto: asyncio.Queue[str] | None = None
_na_fila: set[str] = set()
_worker_task: asyncio.Task | None = None


def analise_cega_intimacao_trf3(metadata: dict) -> bool:
    """True se a análise FIRAC automática do sync seria CEGA para este PAJ.

    O sync não abre o Chrome, então uma FIRAC automática de intimação roda sem
    as peças do processo. Para intimação a ação certa é sempre o fluxo de 1
    clique (Fase 3c): baixa as peças + OCR e só então roda a FIRAC (com o
    processo em mãos). Adiamos a análise automática nesses casos, evitando
    marcar "análise pronta" — ou pior, SOBRESCREVER uma FIRAC boa — sobre uma
    leitura cega. Vide docs/FLUXO_DE_TRABALHO.md (Fase 3b × 3c).

    Adia quando o evento é intimação E:
    - `pje_intimacao_pendente` — peças ainda não baixadas (intimação nova); ou
    - `pje_ultima_intimacao` / `pje_pecas_puxadas_em` — peças JÁ puxadas: a FIRAC
      informada por elas não pode ser substituída por uma releitura cega do sync.
    """
    from services.triagem_service import TIPO_INTIMACAO

    ev = metadata.get("evento_triagem") or {}
    if ev.get("tipo") != TIPO_INTIMACAO:
        return False
    return bool(
        metadata.get("pje_intimacao_pendente")
        or metadata.get("pje_ultima_intimacao")
        or metadata.get("pje_pecas_puxadas_em")
    )


def agendar_analise(paj_norm: str) -> bool:
    """Enfileira a análise FIRAC automática do PAJ. True se entrou na fila.

    Deve ser chamada de contexto async (o sincronizador roda no event loop
    do painel). Fora de um loop (ex.: pipeline standalone), retorna False
    sem quebrar — a análise fica para o botão manual.
    """
    global _fila_auto, _worker_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    with _lock:
        if paj_norm in _na_fila or paj_norm in _em_andamento:
            return False
        _na_fila.add(paj_norm)
    if _fila_auto is None:
        _fila_auto = asyncio.Queue()
    _fila_auto.put_nowait(paj_norm)
    if _worker_task is None or _worker_task.done():
        _worker_task = loop.create_task(_worker_fila())
    return True


async def _worker_fila() -> None:
    """Consome a fila em série; termina quando ela esvazia (religa no próximo
    agendar_analise). Falha em um PAJ não derruba os demais."""
    while True:
        try:
            paj_norm = _fila_auto.get_nowait()
        except asyncio.QueueEmpty:
            return
        with _lock:
            _na_fila.discard(paj_norm)
        try:
            logger.info("[situacao-auto] analisando %s ...", paj_norm)
            res = await gerar_situacao(paj_norm)
            if res.get("ok"):
                logger.info("[situacao-auto] %s pronta (%s)", paj_norm,
                            res.get("gerada_em", ""))
            else:
                logger.warning("[situacao-auto] %s falhou: %s", paj_norm,
                               res.get("erro", ""))
        except Exception:
            logger.exception("[situacao-auto] erro inesperado em %s", paj_norm)


def fila_status() -> dict:
    """Visibilidade da fila automática (para UI/diagnóstico)."""
    with _lock:
        return {"na_fila": sorted(_na_fila), "em_analise": sorted(_em_andamento)}

_SYSTEM_PROMPT = (
    f"Voce e' Defensor(a) Publico(a) Federal experiente atuando na "
    f"{OFICIO_UNIDADE} (metodo FIRAC: Fatos, Questoes, Regras, Aplicacao, "
    "Conclusao). Executor de tarefa: NAO se apresente, NAO converse, NAO "
    "mostre raciocinio intermediario. Responda APENAS com o relatorio markdown "
    "no molde pedido."
)

_INSTRUCAO_SITUACAO = """
---

# SUA TAREFA — análise FIRAC da situação atual do PAJ

Analise o contexto ACIMA (movimentações, prazos, peças, texto do SISDPU) e
produza um RELATÓRIO CURTO da situação atual do PAJ. NÃO repita as
movimentações (há aba própria para isso) — entregue o RESULTADO da análise.

## PRIORIDADE — o que olhar primeiro

Comece pelas ÚLTIMAS movimentações, com atenção especial aos **apontamentos da
assessoria e do Núcleo Assistencial**: é ali que normalmente está dito, de
forma direta, o que precisa ser feito AGORA (minutar determinada peça,
despachar, oficiar, aguardar, arquivar). Extraia essa orientação e trate-a como
o eixo da análise. Se a assessoria já indicou a providência, sua tarefa é
confirmá-la contra os autos e dizer o próximo passo concreto — **DESPACHO ou
PEÇA, e qual** —, não reabrir a análise do zero nem propor caminho diverso sem
motivo expresso.

Pendência de documentação NÃO é achado padrão. Avalie-a somente se ela
IMPEDIR a providência apontada; nesse caso diga o que falta e por que bloqueia.
Se a documentação não impede o próximo passo, no máximo registre uma
observação de uma linha. Nunca substitua a indicação da providência por uma
lista de documentos faltantes, e não use "documentação incompleta" como
conclusão quando as movimentações já apontam o que fazer.

## REGRA DE PRIORIDADE — se cabe PEÇA, a peça é o produto

Se a análise concluir que cabe **petição intercorrente ou recurso** (ou
qualquer manifestação ao juízo), então a providência é ELABORAR A MINUTA —
não despachar, não aguardar, não encaminhar a ninguém. Especificamente:

- **NÃO** aguarde a assessoria e **NÃO** proponha despacho remetendo o caso à
  assessoria, ao gabinete ou ao apoio para que outra pessoa minute a peça.
  Fórmulas como "encaminhe-se à assessoria para minuta", "ao apoio para
  minutar" ou "aguarde-se a minuta" estão PROIBIDAS como providência quando a
  peça já é cabível.
- Diga QUAL é a peça cabível e o prazo, e registre que a minuta será elaborada
  agora (o Defensor a produz pelo botão de elaborar peça do painel).
- O despacho do item 4 do molde, nesse cenário, serve apenas para REGISTRAR no
  PAJ a providência adotada (ex.: ciência da intimação e elaboração da peça),
  nunca para transferir a tarefa a outrem.

Isso não conflita com a prioridade dada aos apontamentos da assessoria: quando
a assessoria JÁ ENTREGOU algo (minuta, relatório, informação), leia e use;
quando ela ainda NÃO entregou e a peça é cabível, faça você a minuta em vez de
esperar.

## QUEM JUNTA A PETIÇÃO — divisão de trabalho no ofício

A juntada de **petição intercorrente** é do DEFENSOR, não do Cartório. O
Cartório faz o pré-cadastro e a juntada da **petição inicial**, apenas.

Logo, nunca proponha despacho mandando o Cartório juntar manifestação,
réplica, recurso, embargos, impugnação, memoriais ou qualquer peça no curso do
processo. Fórmulas como "ao Cartório para juntada" ou "Cartório: proceder à
juntada da petição" só cabem em petição inicial. Na intercorrente, o despacho
registra que o próprio Defensor protocola.

Primeiro identifique qual movimentação EFETIVAMENTE encaminhou o PAJ ao
defensor, com cuidado com os ruídos do SISDPU:
- PAJs chegam em duplicidade: a última movimentação pode ser uma "conclusão"
  posterior — o evento real está antes;
- "Fase incluída automaticamente, verificar fase anterior": o sinal está na
  FASE da movimentação ou na anterior;
- Decurso de prazo com situação "PREVISTO" é programação futura — ignore;
  só o decurso "EFETIVADO" caracteriza envio ao defensor.

Depois classifique o evento (Abertura de PAJ/redistribuição · Retorno do
Assistido · Intimação judicial · Resposta de ofício · Controle de prazo) e
analise conforme o fluxo:
- **Retorno do Assistido** — o que o assistido solicitou ou apresentou, e o que
  a assessoria apontou a respeito. Se apresentou documentação: diga se ela já
  viabiliza a providência indicada; liste o que falta APENAS se isso bloquear o
  próximo passo. Se requerimento/reclamação/pedido de informação: resuma e
  indique a resposta educada cabível.
- **Abertura de PAJ** — narrativa da demanda, NB/DER se houver, renda declarada
  vs. limite de atuação da DPU e a providência apontada pela assessoria.
  Lacunas documentais somente se impedirem a atuação agora. **Neste fluxo é
  OBRIGATÓRIA a análise de mérito descrita abaixo.**
- **Intimação judicial** — id e teor do ato, favorável ou desfavorável ao
  assistido, prazo e peça cabível (considere a seção do PJe, se presente).
- **Resposta de ofício** — a demanda foi solucionada? Próximos passos.
- **Controle de prazo** — o que o prazo controlava e a providência.

## PAJ DE PRIMEIRO CONTATO — ANÁLISE DE MÉRITO OBRIGATÓRIA

Quando o PAJ chega ao defensor pela PRIMEIRA VEZ (abertura de PAJ,
redistribuição à unidade, ou PAJ novo na caixa sem movimentação classificável),
a análise NÃO se limita a conferir presença ou ausência de documentos. É
obrigatório examinar o MÉRITO da pretensão e concluir sobre sua VIABILIDADE.

Para isso, acrescente ao molde uma seção **"5. Análise de mérito e
viabilidade"** com:

- **O direito pleiteado** — qualifique juridicamente o que a parte busca (não
  repita a narrativa: diga o instituto, ex.: restabelecimento de auxílio por
  incapacidade temporária; BPC/LOAS por deficiência; fornecimento de
  medicamento fora da RENAME; revisão de benefício).
- **Requisitos legais** — os requisitos do direito pleiteado, um a um, e o que
  os autos/documentos demonstram sobre CADA um (atendido · não atendido ·
  indefinido). É aqui que a documentação entra: não como checklist burocrático,
  mas como prova de requisito.
- **Obstáculos e teses contrárias** — prescrição/decadência, prévio
  requerimento administrativo, coisa julgada, competência, litispendência,
  ausência de interesse, entendimento consolidado desfavorável. Consulte a base
  local de entendimentos da CCR/DPU (`~/.claude/conhecimento-dpu/`, começando
  pelo `INDICE.md`) e cite enunciado, tese de arquivamento ou precedente
  APENAS se estiver literalmente na base — nunca invente.
- **Conclusão de viabilidade**, escolhendo uma destas: **VIÁVEL** (a
  documentação já sustenta a pretensão — indique a peça cabível); **AINDA NÃO
  VIÁVEL** (a tese é boa, mas falta prova de requisito determinado — diga
  exatamente qual prova e como obtê-la); **INVIÁVEL** (obstáculo jurídico
  insuperável ou pretensão sem amparo — explique e indique o encaminhamento,
  inclusive orientação ao assistido ou arquivamento fundamentado).

Se a conclusão for VIÁVEL, aplica-se a regra de prioridade acima: a
providência é elaborar a peça, não encaminhá-la a terceiros.

## CASO ESPECIAL — minuta da assessoria aguardando revisão

Se o contexto tiver a seção "Minuta da assessoria aguardando revisao do
Defensor", a tarefa principal é REVISAR essa minuta. Nesse caso, acrescente ao
molde abaixo uma seção final **"5. Revisão da minuta"** com:

- **Veredito:** "de acordo" · "de acordo com ajustes" · "não serve — refazer".
- **Aderência ao PAJ:** a minuta corresponde ao que este PAJ pede AGORA (peça
  cabível, pedidos, partes, número do processo, juízo, prazo)? Aponte cada
  divergência contra os dados do PAJ acima.
- **Erros encontrados:** lista objetiva e concreta (dispositivo legal errado,
  data/valor/nome incorreto, pedido faltante ou incompatível, tese inadequada,
  citação de jurisprudência inexistente ou impertinente, endereçamento errado).
  Cite o trecho. Se não houver erro, diga "nenhum erro identificado".
- **O que fazer:** se houver o que corrigir, avise que a versão corrigida deve
  ser gerada na elaboração (botão de elaborar peça) — não escreva a peça
  inteira aqui.

Se a minuta NÃO estiver acessível (só link do editor do PJe, ou arquivo
ausente), NÃO adivinhe o conteúdo: registre que a revisão está impossibilitada
e o que é preciso para viabilizá-la.


REGRA ESPECIAL — EXECUCAO FISCAL COM CURADORIA ESPECIAL:
Antes de sugerir a minuta de EMBARGOS A EXECUCAO FISCAL, verifique uma a uma
as teses e diga na analise o que examinou: (a) prescricao/decadencia, pelas
datas de inscricao de cada CDA; (b) legitimidade do corresponsavel, que SO
existe se o devedor principal for pessoa juridica com personalidade autonoma
— se a razao social do CNPJ for o proprio nome da pessoa natural, sem LTDA/
ME/EIRELI, e EMPRESARIO INDIVIDUAL, CNPJ e CPF sao o mesmo sujeito e o art.
135, III, do CTN nao tem objeto; (c) nulidade da CDA; (d) excesso de
execucao; (e) impenhorabilidade — que NAO e tese nova se ja foi ventilada e
rejeitada em manifestacao anterior.
NAO havendo tese viavel, NAO sugira minutar embargos. Sugira DESPACHO que
sustente a inviabilidade tese por tese, ressalte as dificuldades inerentes a
CURADORIA ESPECIAL (sem contato com o executado revel citado por edital, sem
acesso aos documentos e a origem dos creditos), registre o prazo dos embargos
e a consequencia de deixa-lo correr, e manifeste ciencia.
NAO cite skill que nao exista no workspace: confira antes.

## MOLDE DA RESPOSTA (obrigatório — 4 seções numeradas, markdown)

1. **Resumo da demanda** — 2-4 frases: quem é o assistido e o que busca.
2. **Razão do encaminhamento e situação atual** — comece com "PAJ encaminhado
   ao defensor em razão de ..." e desenvolva a análise do fluxo identificado.
3. **Sugestão** — skill/plugin a utilizar no próximo passo (ex.: plugin
   previdenciário para minuta da inicial; skill de mensagem ao assistido;
   plugin previdenciário + skill BPC-LOAS para viabilidade de recurso).
4. **Sugestão de despacho no PAJ** — texto PRONTO do despacho administrativo,
   curto e objetivo, para colar no DPU Digital. O TEXTO DO DESPACHO em si vai
   em TEXTO PURO, sem nenhuma marcação (`*`, `**`, `#`, `>`, `-` de lista,
   backticks): o editor da DPU não interpreta esses caracteres e eles apareceriam
   literalmente. Enfase em CAIXA ALTA; enumeração com 'a)', 'b)' ou '1.' no
   corpo do parágrafo. (As demais seções deste relatório seguem em markdown
   normal — a restrição é só para o texto do despacho.)

## EXEMPLOS DE TOM E FORMATO (ilustrativos — adapte ao caso concreto)

Exemplo A (retorno com documentação completa):
"1. [resumo da demanda em 2-3 frases]
2. PAJ encaminhado ao defensor em razão de atendimento de retorno. O assistido
apresentou os documentos X, Y e Z. Analisando as movimentações anteriores,
todas as documentações solicitadas foram juntadas — demanda pronta para
análise e minuta de petição.
3. Sugestão: utilizar o plugin previdenciário para a minuta da petição inicial.
4. Sugiro o seguinte despacho no PAJ: [texto do despacho]"

Exemplo B (intimação de sentença desfavorável):
"1. [resumo da demanda]
2. PAJ encaminhado ao defensor em razão da intimação id. NNN — sentença
improcedente que negou o BPC/LOAS por ausência de miserabilidade (renda da
genitora). [análise do fundamento e do prazo]
3. Sugestão: plugin previdenciário com a skill BPC-LOAS para análise de
viabilidade de recurso inominado.
4. Sugiro o seguinte despacho no PAJ: [texto do despacho]"

Responda SOMENTE com o relatório (as 4 seções), sem preâmbulo nem fechamento.
""".strip()


def _montar_prompt_situacao(paj_norm: str) -> str | None:
    contexto = montar_contexto(paj_norm)
    if contexto is None:
        return None
    return contexto + "\n\n" + _INSTRUCAO_SITUACAO


async def gerar_situacao(paj_norm: str, timeout: int = 300) -> dict:
    """Roda a análise FIRAC e grava SITUACAO.md. Retorna {ok, texto|erro}."""
    pasta = PAJS_DIR / paj_norm
    prompt = _montar_prompt_situacao(paj_norm)
    if prompt is None:
        return {"ok": False, "erro": "PAJ não encontrado."}

    with _lock:
        if paj_norm in _em_andamento:
            return {"ok": False, "erro": "Já existe uma análise em andamento para este PAJ."}
        _em_andamento.add(paj_norm)
    try:
        return await _gerar_situacao_exclusivo(paj_norm, pasta, prompt, timeout)
    finally:
        with _lock:
            _em_andamento.discard(paj_norm)


async def _gerar_situacao_exclusivo(paj_norm: str, pasta, prompt: str,
                                    timeout: int) -> dict:
    # --print: nao-interativo; --setting-sources user: ignora o CLAUDE.md do
    # projeto (tom conversacional). Prompt via stdin (limite de 32k chars no
    # command line do Windows). cwd na pasta do PAJ: o Claude pode ler os .txt
    # locais (pecas/OCR) se precisar de detalhe.
    claude_cmd = resolver_claude_cmd()
    cmd = [
        *claude_cmd,
        "--print",
        "--setting-sources", "user",
        "--append-system-prompt", _SYSTEM_PROMPT,
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
        return {"ok": False, "erro": f"Timeout ({timeout}s) na análise — tente de novo."}
    except FileNotFoundError:
        return {"ok": False, "erro": f"Claude CLI não encontrado: {' '.join(claude_cmd)}"}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}

    if proc.returncode != 0:
        return {"ok": False, "erro": classificar_erro_claude(proc)}

    texto = (proc.stdout or "").strip()
    if len(texto) < 80:
        return {"ok": False, "erro": f"Análise vazia/curta demais: {texto[:200]!r}"}

    agora = datetime.datetime.now()
    cabecalho = (
        f"_Análise FIRAC gerada em {agora.strftime('%d/%m/%Y %H:%M')} pelo painel "
        f"(Claude CLI). Atualize após novas movimentações._\n\n"
    )
    (pasta / SITUACAO_FILE).write_text(cabecalho + texto + "\n", encoding="utf-8")

    # PROMPT_MAX passa a abrir com a análise (ordem definida pelo Defensor).
    gerar_prompt_max(paj_norm)

    # Fase 3 do fluxo: a seção 4 da análise vira despacho de verdade, na aba
    # Despachos. Best-effort: falha aqui não pode derrubar a análise, que é o
    # produto caro.
    #
    # NÃO entra na fila de Diligências. Decisão do Defensor em 12/10/2026: a
    # fila é só o que ele já revisou e aprovou na tela do PAJ. Quem põe lá é o
    # botão "Pôr na fila", nunca o painel por conta própria.
    despacho = {}
    try:
        from services import despacho_firac

        despacho = despacho_firac.criar_do_firac(paj_norm)
    except Exception as e:
        logger.warning("despacho do FIRAC falhou em %s: %s", paj_norm, e)

    return {"ok": True, "texto": cabecalho + texto,
            "despacho": despacho,
            "gerada_em": agora.isoformat(timespec="seconds")}
