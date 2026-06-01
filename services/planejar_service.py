"""Planejamento pre-elaboracao — o Claude analisa o PAJ e propoe a estrutura da peca.

Antes de o Claude executar a elaboracao completa (que gera o .txt da peca/despacho),
ele primeiro gera um PLANO em JSON estruturado. O Defensor revisa, corrige se preciso,
e SO entao aprova -> elaboracao real.

Adaptado do dpuscript-ui original para o fork local (TRF3/Osasco):
- usa PAJS_DIR e o schema do SISDPU deste fork (metadata.json + sisdpu.txt +
  detalhes_sisdpu.movimentacoes), nao resumo_curto.md/decisoes_superiores;
- prompt generico de 1a instancia (JF/JEF), sem regras de TNU/STJ/PUIL;
- prazos sao calculados automaticamente pelo modulo prazo_processual, entao o
  plano nao precisa raciocinar sobre dobra/contagem.

Plano (JSON):
{
  "tipo_atuacao": "RECURSO" | "DESPACHO_INTERNO" | "ARQUIVAMENTO" | "NAO_ATUAR",
  "tipo_peca": "<peca cabivel — ex: contestacao, replica, apelacao, ...>",
  "decisao_recorrida_descricao": "1-2 frases identificando a decisao/ato analisado",
  "decisao_recorrida_arquivo": "<nome do .txt local que contem a decisao, se houver>",
  "analise_completa": "texto narrativo corrido (500-2000 chars)",
  "fontes_auxiliares": [{"tipo": "...", "ref": "...", "arquivo": "..."}],
  "confianca": "alta" | "media" | "baixa",
  "alertas": ["..."]
}
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import subprocess
from pathlib import Path

from config import OFICIO_GERAL, PAJS_DIR
from services.chat_service import CLAUDE_CMD
from services.paj_service import ler_texto_robusto, listar_pecas_assistido

# Regras de atuacao acumuladas/editadas pelo Defensor. Lidas a cada chamada —
# basta editar o arquivo que a proxima geracao de plano ja considera. Opcional:
# se nao existir, simplesmente nao injeta nada.
REGRAS_ATUACAO_FILE = OFICIO_GERAL / "memory" / "regras_atuacao.md"

MAX_MOVIMENTACOES = 8


def _carregar_regras_atuacao() -> str:
    if not REGRAS_ATUACAO_FILE.exists():
        return ""
    return ler_texto_robusto(REGRAS_ATUACAO_FILE)


def _env_sem_claudecode() -> dict:
    """Clone do env sem CLAUDECODE — evita erro 'Claude dentro de outro Claude'."""
    env = os.environ.copy()
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
        env.pop(k, None)
    return env


def _ler_movimentacoes(meta: dict) -> str:
    det = meta.get("detalhes_sisdpu", {}) or {}
    movs = det.get("movimentacoes") or []
    movs_ord = sorted(movs, key=lambda m: int(m.get("seq", 0) or 0), reverse=True)
    if not movs_ord:
        return "  (sem movimentacoes registradas)"
    linhas = []
    for mov in movs_ord[:MAX_MOVIMENTACOES]:
        data = mov.get("data_original") or mov.get("data") or "?"
        descr = (mov.get("descricao") or "").strip()
        if len(descr) > 400:
            descr = descr[:400].rstrip() + "..."
        linhas.append(f"  - [{data}] {descr}")
    return "\n".join(linhas)


def _listar_arquivos_locais(pasta: Path) -> str:
    """Lista nomes de .txt em pecas/ e na raiz do PAJ, para o Claude poder
    apontar em decisao_recorrida_arquivo / fontes_auxiliares.arquivo."""
    linhas: list[str] = []
    for sub in ("pecas", "peças", "."):
        d = pasta / sub if sub != "." else pasta
        if not d.exists() or not d.is_dir():
            continue
        arqs = sorted(
            f.name for f in d.iterdir()
            if f.is_file() and f.suffix.lower() == ".txt"
        )
        if arqs:
            prefixo = f"{sub}/" if sub != "." else ""
            linhas.append(f"  {prefixo or '(raiz)'}:")
            for a in arqs:
                linhas.append(f"    - {prefixo}{a}")
    return "\n".join(linhas) if linhas else "  (nenhum arquivo .txt local)"


def _listar_pecas_anteriores(meta: dict) -> str:
    assistido = meta.get("assistido_caixa") or meta.get("assistido") or ""
    pecas = listar_pecas_assistido(assistido)
    if not pecas:
        return "  (nenhuma peca anterior do mesmo assistido encontrada)"
    return "\n".join(f"  - {p['nome']}" for p in pecas[:20])


def _montar_prompt(paj: str, meta: dict, pasta: Path) -> str:
    det = meta.get("detalhes_sisdpu", {}) or {}
    regras = _carregar_regras_atuacao()
    bloco_regras = (
        f"\n\nREGRAS DE ATUACAO DO DEFENSOR (correcoes acumuladas — RESPEITE):\n{regras}\n"
        if regras else ""
    )
    sisdpu_path = pasta / "sisdpu.txt"
    sisdpu_texto = ler_texto_robusto(sisdpu_path) if sisdpu_path.exists() else ""

    return f"""Voce e' assistente juridico de um(a) Defensor(a) Publico(a) Federal da DPU,
1o Oficio Geral em Osasco/SP (atuacao perante a Justica Federal — TRF3, 1a instancia
e Juizados Especiais Federais).{bloco_regras}

TAREFA: analisar o PAJ e propor um PLANO DE ATUACAO. O Defensor vai revisar antes
de executar. NAO redija a peca agora — apenas planeje.

CONTEXTO DO PAJ:
- PAJ: {paj}
- Assistido: {meta.get('assistido_caixa') or meta.get('assistido') or '?'}
- Pretensao: {meta.get('pretensao') or '?'}
- Oficio responsavel: {meta.get('oficio_caixa') or '?'}
- Processo judicial: {meta.get('processo_judicial') or '(nao cadastrado)'}
- Foro/area: {meta.get('foro_detalhado') or meta.get('foro_detectado') or '?'}
- Status: {det.get('status_paj') or 'Ativo'}

ULTIMAS MOVIMENTACOES (mais recentes primeiro):
{_ler_movimentacoes(meta)}

ARQUIVOS LOCAIS DA PASTA DO PAJ (use estes nomes em decisao_recorrida_arquivo e
fontes_auxiliares.arquivo):
{_listar_arquivos_locais(pasta)}

PECAS ANTERIORES DO MESMO ASSISTIDO (em "Pecas Feitas/", podem servir de modelo):
{_listar_pecas_anteriores(meta)}

TEXTO DO SISDPU (caixa/andamento):
{sisdpu_texto[:6000]}

ORIENTACOES:
- Atuacao perante a Justica Federal de 1o grau (TRF3) e JEFs. NAO assuma TNU/STJ.
- Os PRAZOS sao calculados automaticamente pelo painel (dobra da DPU no rito comum
  do CPC; sem dobra nos Juizados; prazos corridos no processo penal). NAO e' preciso
  raciocinar sobre contagem de prazo no plano.
- Distinga vitoria, derrota e ato neutro: uma decisao de mero impulso/saneamento,
  citacao, juntada ou intimacao NAO e' "favoravel" — classifique como neutra.
- So chame de favoravel/desfavoravel o que efetivamente julga ou decide o merito
  ou um incidente relevante.

ATUACAO POSSIVEL:
- RECURSO + peca recursal especifica (ex: apelacao, agravo de instrumento, agravo
  interno, embargos de declaracao, recurso inominado no JEF)
- DESPACHO_INTERNO + tipo (despacho_acompanhamento, despacho_arquivamento) — apenas
  registro no SISDPU, sem peca judicial
- ARQUIVAMENTO + despacho_arquivamento (exito definitivo ou nada mais a fazer)
- NAO_ATUAR + "nenhuma" — apenas ciencia, aguardar

CAMPO tipo_peca — escolha a peca CABIVEL agora, em minusculas e com underscores.
Exemplos (nao e' lista fechada): peticao_inicial, contestacao, replica, manifestacao,
impugnacao, apelacao, contrarrazoes, agravo_instrumento, agravo_interno,
embargos_declaracao, recurso_inominado, memoriais, alegacoes_finais, cumprimento_sentenca,
despacho_acompanhamento, despacho_arquivamento, nenhuma.

CAMPO analise_completa — escreva UMA ANALISE NARRATIVA CORRIDA (500-2000 caracteres):
o que aconteceu no processo, por que voce escolheu essa atuacao e qual o caminho
recomendado. Portugues juridico claro, sem floreio, sem bullets.

CAMPO decisao_recorrida_descricao — 1-2 frases identificando a decisao/ato sob analise.
CAMPO decisao_recorrida_arquivo — nome do .txt local que contem essa decisao (so o nome;
vazio se nao houver arquivo claro).

CAMPO fontes_auxiliares — outras fontes citadas (jurisprudencia, lei, sumula, tese,
decisao paradigma), cada uma com `tipo`, `ref` e `arquivo` (se houver arquivo local)."""


PLANO_JSON_SCHEMA = {
    "type": "object",
    "required": [
        "tipo_atuacao", "tipo_peca",
        "decisao_recorrida_descricao", "decisao_recorrida_arquivo",
        "analise_completa", "fontes_auxiliares",
        "confianca",
    ],
    "properties": {
        "tipo_atuacao": {
            "type": "string",
            "enum": ["RECURSO", "DESPACHO_INTERNO", "ARQUIVAMENTO", "NAO_ATUAR"],
        },
        # Peca cabivel — string livre (a atuacao na 1a instancia e' variada demais
        # para um enum fechado). O prompt orienta o vocabulario.
        "tipo_peca": {
            "type": "string",
            "description": "Peca cabivel, em minusculas com underscores (ex: contestacao, apelacao, despacho_arquivamento, nenhuma)",
        },
        "decisao_recorrida_descricao": {
            "type": "string",
            "description": "1-2 frases identificando a decisao/ato sob analise",
        },
        "decisao_recorrida_arquivo": {
            "type": "string",
            "description": "Nome do .txt local que contem a decisao. Vazio se nao houver.",
        },
        "analise_completa": {
            "type": "string",
            "description": "Texto narrativo corrido (500-2000 chars) explicando o caso e a atuacao proposta",
        },
        "fontes_auxiliares": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "enum": ["juris", "sumula", "tese", "regimento", "lei", "decisao_paradigma"]},
                    "ref": {"type": "string"},
                    "arquivo": {
                        "type": "string",
                        "description": "Nome do arquivo local que contem a fonte (se houver). Vazio se externa.",
                    },
                },
                "required": ["tipo", "ref"],
            },
        },
        "confianca": {"type": "string", "enum": ["alta", "media", "baixa"]},
        "alertas": {"type": "array", "items": {"type": "string"}},
    },
}


async def planejar_elaboracao(
    paj_norm: str,
    timeout: int = 180,
    feedback_jp: str = "",
) -> dict:
    """Chama o Claude CLI com o prompt de planejamento. Retorna JSON parseado.

    Args:
        paj_norm: PAJ normalizado (ex: PAJ-YYYY-044-NNNNN)
        timeout: maximo de segundos
        feedback_jp: instrucao adicional do Defensor para refazer com observacao
    """
    pasta = PAJS_DIR / paj_norm
    meta_f = pasta / "metadata.json"
    if not meta_f.exists():
        return {"ok": False, "erro": f"metadata.json nao encontrado em {pasta}"}

    try:
        meta = json.loads(ler_texto_robusto(meta_f))
    except Exception as e:
        return {"ok": False, "erro": f"erro lendo metadata: {e}"}

    paj_original = meta.get("paj", paj_norm)
    prompt = _montar_prompt(paj_original, meta, pasta)
    if feedback_jp.strip():
        prompt += (
            "\n\nOBSERVACAO IMPORTANTE DO DEFENSOR (refaca considerando isto):\n"
            f'"""{feedback_jp.strip()[:500]}"""'
        )

    # --print: modo nao-interativo; --output-format json: wrapper estruturado;
    # --json-schema: forca a resposta a seguir o esquema; --setting-sources user:
    # ignora o CLAUDE.md do projeto (tom conversacional). Prompt via stdin (limite
    # de 32k chars no command line do Windows).
    cmd = [
        *CLAUDE_CMD,
        "--print",
        "--output-format", "json",
        "--json-schema", json.dumps(PLANO_JSON_SCHEMA),
        "--setting-sources", "user",
        "--append-system-prompt",
        "Voce e' executor de tarefa estruturada. NAO inicie conversa nem se "
        "apresente. Apenas analise o caso e responda com JSON puro seguindo o "
        "schema. Sem markdown, sem texto antes/depois.",
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
        return {"ok": False, "erro": "Timeout chamando o Claude CLI"}
    except FileNotFoundError:
        return {"ok": False, "erro": f"Claude CLI nao encontrado: {' '.join(CLAUDE_CMD)}"}
    except Exception as e:
        return {"ok": False, "erro": f"{type(e).__name__}: {e}"}

    if proc.returncode != 0:
        return {
            "ok": False,
            "erro": f"Claude saiu com codigo {proc.returncode}: {proc.stderr[-500:]}",
            "stdout": proc.stdout[-500:],
        }

    plano = _extrair_plano_da_resposta(proc.stdout)
    if not plano:
        return {
            "ok": False,
            "erro": "Claude nao retornou JSON parseavel",
            "resp_raw": proc.stdout[-2000:],
        }

    return {"ok": True, "plano": plano, "resp_raw": proc.stdout[:300]}


def _extrair_plano_da_resposta(out: str) -> dict | None:
    """Extrai o plano (JSON estruturado) da resposta do Claude.

    Com --output-format json + --json-schema, stdout vem como:
      {"type":"result", "result":"", "structured_output": <dict>, ...}
    O plano fica em `structured_output`. Sem --json-schema, fica como string em
    `result`.
    """
    try:
        wrapper = json.loads(out.strip())
        if isinstance(wrapper, dict):
            so = wrapper.get("structured_output")
            if isinstance(so, dict) and so:
                return so
            result = wrapper.get("result", "")
            if isinstance(result, dict):
                return result
            if isinstance(result, str) and result.strip():
                parsed = _extrair_json(result)
                if parsed:
                    return parsed
    except json.JSONDecodeError:
        pass
    return _extrair_json(out)


def _extrair_json(s: str) -> dict | None:
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        clean = re.sub(r",\s*([}\]])", r"\1", m.group(0))  # trailing commas
        try:
            return json.loads(clean)
        except Exception:
            return None


def salvar_plano(paj_norm: str, plano: dict, fonte: str = "claude") -> Path:
    """Persiste o plano aprovado em disco para uso posterior pela elaboracao."""
    pasta = PAJS_DIR / paj_norm
    pasta.mkdir(parents=True, exist_ok=True)
    f = pasta / "plano_elaboracao.json"
    payload = {
        "plano": plano,
        "fonte": fonte,
        "salvo_em": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    f.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return f


def carregar_plano(paj_norm: str) -> dict | None:
    pasta = PAJS_DIR / paj_norm
    f = pasta / "plano_elaboracao.json"
    if not f.exists():
        return None
    try:
        return json.loads(ler_texto_robusto(f))
    except Exception:
        return None
