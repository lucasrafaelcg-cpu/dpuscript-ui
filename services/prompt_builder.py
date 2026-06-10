"""Gera PROMPT_MAX.md dinamicamente por PAJ — a "Situação do PAJ".

E' o guia do fluxo de trabalho do Defensor (docs/FLUXO_DE_TRABALHO.md):
alem do contexto (cabecalho, movimentacoes, pecas, texto do SISDPU), o prompt
instrui a analise FIRAC a identificar POR QUE o PAJ foi encaminhado ao
defensor (olhando as ultimas movimentacoes, nao so a ultima — ha ruido de
duplicidade/conclusoes posteriores), classificar o evento num dos 5 fluxos de
entrada e propor o proximo passo com uma breve analise.

Concatena:
- cabecalho estruturado (identificacao, prazo, processo)
- ultimas movimentacoes + evento detectado (heuristica de triagem_service)
- lista de pecas anteriores do mesmo assistido em `Pecas Feitas/`
- texto completo do SISDPU
- instrucao de analise FIRAC (razao do encaminhamento + fluxo + proximo passo)
"""

from __future__ import annotations

import json
from pathlib import Path

from config import PAJS_DIR


# Quantidade de movimentacoes no resumo. 12 (e nao so a ultima) porque o
# evento que efetivamente encaminhou o PAJ ao defensor pode estar atras de
# conclusoes/encaminhamentos em duplicidade posteriores.
MAX_MOVIMENTACOES_RESUMO = 12

# O digest do PJe (_situacao_pje.md) contém o OCR integral das peças baixadas —
# pode passar de centenas de páginas. No PROMPT_MAX entra só o início; o texto
# completo continua disponível no arquivo, e o aviso aponta para ele.
MAX_PJE_DIGEST_CHARS = 30_000


def _ler_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def gerar_prompt_max(paj_norm: str) -> Path | None:
    """Monta PROMPT_MAX.md dentro da pasta do PAJ e retorna o Path."""
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
        for mov in movs_ord[:MAX_MOVIMENTACOES_RESUMO]:
            data = mov.get("data_original") or mov.get("data") or "?"
            descr = (mov.get("descricao") or "").strip()
            if len(descr) > 400:
                descr = descr[:400].rstrip() + "..."
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
    # deterministica de triagem_service. E' uma DICA para a analise FIRAC
    # abaixo, nao um veredito.
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
            "analise FIRAC abaixo antes de seguir o fluxo."
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

    partes.append("")
    partes.append("---")
    partes.append("")
    partes.append("## Texto completo do SISDPU")
    partes.append("")
    partes.append(sisdpu_texto.strip() or "(sem texto de SISDPU)")
    partes.append("")
    partes.append("---")
    partes.append("")
    partes.append("## Analise solicitada — skill FIRAC")
    partes.append("")
    partes.append(
        "Aplique a skill `firac` (Sistema Integrado de Analise Juridica da DPU) "
        "sobre este PAJ, nesta ordem:"
    )
    partes.append("""
1. **Razao do encaminhamento.** Leia as ULTIMAS MOVIMENTACOES acima (nao apenas
   a ultima) e identifique qual movimentacao EFETIVAMENTE encaminhou este PAJ
   ao defensor. Cuidado com os ruidos conhecidos do SISDPU:
   - PAJs chegam em duplicidade na caixa: a ultima movimentacao pode ser uma
     "conclusao" posterior — o evento real esta em movimentacao anterior.
   - Descricao "Fase incluida automaticamente, verificar fase anterior": o
     sinal esta na FASE da propria movimentacao ou na movimentacao anterior.

2. **Classifique o evento** em um destes 5 fluxos de entrada:
   1. Abertura de PAJ (ou redistribuicao a unidade de Osasco)
   2. Retorno do Assistido
   3. Intimacao judicial
   4. Resposta de oficio
   5. Controle de prazo (envio automatico pelo sistema ao encerrar um prazo de controle)

3. **Siga a orientacao do fluxo identificado:**
   - **Retorno do Assistido** — leia o que o assistido solicitou ou apresentou a DPU:
     (a) requerimento, reclamacao ou pedido de informacao → analise e minute
         resposta educada ao assistido em linguagem acessivel (skill `mensagem`);
     (b) apresentacao de documentacao pendente → audite a completude (FIRAC
         Modulo 2 — Auditoria Documental): se COMPLETA, siga ao proximo passo
         da analise; se INCOMPLETA, minute mensagem ao assistido informando que
         os documentos foram recebidos mas ainda estao incompletos, listando
         exatamente o que falta.
   - **Abertura de PAJ** — leia a narrativa e os documentos, aplique a triagem
     da area e o checklist DPU, aponte lacunas e viabilidade (FIRAC Modulo 2).
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
TEXTO pronto da peca/despacho/mensagem na pasta do PAJ.""".strip("\n"))

    prompt_path = pasta / "PROMPT_MAX.md"
    prompt_path.write_text("\n".join(partes), encoding="utf-8")
    return prompt_path
