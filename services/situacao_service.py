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

from config import PAJS_DIR
from services.chat_service import CLAUDE_CMD
from services.planejar_service import _env_sem_claudecode
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
    "Voce e' Defensor(a) Publico(a) Federal experiente atuando na Justica "
    "Federal de Osasco (metodo FIRAC: Fatos, Questoes, Regras, Aplicacao, "
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
- **Retorno do Assistido** — o que o assistido solicitou ou apresentou? Se
  documentação: confira contra o que foi pedido nas movimentações anteriores —
  completa (pronta para minuta) ou incompleta (liste EXATAMENTE o que falta).
  Se requerimento/reclamação/pedido de informação: resuma e indique a resposta
  educada cabível.
- **Abertura de PAJ** — narrativa da demanda, NB/DER se houver, renda declarada
  vs. limite de atuação da DPU, documentos juntados vs. checklist da demanda,
  lacunas.
- **Intimação judicial** — id e teor do ato, favorável ou desfavorável ao
  assistido, prazo e peça cabível (considere a seção do PJe, se presente).
- **Resposta de ofício** — a demanda foi solucionada? Próximos passos.
- **Controle de prazo** — o que o prazo controlava e a providência.

## MOLDE DA RESPOSTA (obrigatório — 4 seções numeradas, markdown)

1. **Resumo da demanda** — 2-4 frases: quem é o assistido e o que busca.
2. **Razão do encaminhamento e situação atual** — comece com "PAJ encaminhado
   ao defensor em razão de ..." e desenvolva a análise do fluxo identificado.
3. **Sugestão** — skill/plugin a utilizar no próximo passo (ex.: plugin
   previdenciário para minuta da inicial; skill de mensagem ao assistido;
   plugin previdenciário + skill BPC-LOAS para viabilidade de recurso).
4. **Sugestão de despacho no PAJ** — texto PRONTO do despacho administrativo,
   curto e objetivo, para colar no DPU Digital.

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
    cmd = [
        *CLAUDE_CMD,
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
        return {"ok": False, "erro": f"Claude CLI não encontrado: {' '.join(CLAUDE_CMD)}"}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}

    if proc.returncode != 0:
        return {"ok": False,
                "erro": f"Claude saiu com código {proc.returncode}: {proc.stderr[-400:]}"}

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

    return {"ok": True, "texto": cabecalho + texto,
            "gerada_em": agora.isoformat(timespec="seconds")}
