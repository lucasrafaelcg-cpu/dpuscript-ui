#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESCRITA no SISDPU: inclusao de movimentacao no PAJ (com anexo opcional).

Este e o UNICO modulo do painel que ALTERA o SISDPU. Todo o resto e leitura.
Uma movimentacao gravada nao e removivel pelo Defensor, e um anexo no PAJ
errado e documento na pasta de outro assistido. O Defensor definiu que o
PEDIDO dele ja vale como autorizacao (nao se reconfirma a cada vez), entao
as travas abaixo existem para impedir gravacao ERRADA — nao para pedir
permissao:

  1. roda em DRY-RUN por padrao (`confirmar=False`): preenche tudo, tira
     screenshot e PARA antes de clicar em "Movimentar";
  2. confere que o cabecalho "Movimentacao do PAJ: <paj>" e o PAJ pretendido
     ANTES de preencher, e aborta se divergir;
  3. exige exatamente 1 PAJ na lista de selecionados;
  4. resolve a Fase pelo TEXTO — o `value` do option carrega um hash de objeto
     Java (`...FaseDTO@822 - Id: 57`) que muda entre sessoes; hardcodar
     quebraria silenciosamente ou, pior, escolheria outra fase;
  5. confere que o anexo entrou em `tabelaArquivos` (os anexos de fato da
     movimentacao) DEPOIS de clicar em "Anexar" — a fila `arquivosSalvar`
     nao serve de prova: ela mostra o arquivo apenas selecionado, e fechar
     o modal nesse estado descarta o upload (aconteceu em 2026-09-03);
  6. depois de submeter, RELE as movimentacoes e confirma que a nova entrada
     existe — sem isso nao ha como afirmar que gravou;
  7. com `assistido_esperado`, confere o NOME do assistido na tela contra o
     que o painel registrou e aborta se divergir — trava da fila de
     Diligencias, onde se marca por linha e linha trocada e' documento na
     pasta de outro assistido.

Mapa da tela (verificado em 2026-09-02, SISDPU producao):
  entrada .......... detalhamentoForm:LnkMovimentar  (na tela do PAJ)
  form ............. formHonorario
  tipo ............. formHonorario:MovId    (11 = MOVIMENTACAO MANUAL)
  fase ............. formHonorario:faseId   -> adiciona linha em
                     formHonorario:dataTableFasesSelecionadas
  anexo ............ link "Adicionar Anexo" na linha da fase -> modal
                     formHonorario:dlgModalArquivos, input
                     formHonorario:arquivosFase_input (type=file); o arquivo
                     cai na FILA formHonorario:arquivosSalvar, onde se escolhe
                     Descricao + Tipo de arquivo e se clica "Anexar" para ele
                     passar a formHonorario:tabelaArquivos (anexo real)
  descricao ........ CKEditor, instancia formHonorario_editorValue
  visivel na web ... formHonorario:mostrarDescricaoNaInternet (vem MARCADO)
  submit ........... formHonorario:btnMovimentarTopo / btnMovimentarRodape
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ingestao import sisdpu_client as sc

_log = logging.getLogger(__name__)

FORM = "formHonorario"
TIPO_MOVIMENTACAO_MANUAL = "11"

# Fases mais usadas (por TEXTO, nao por id — ver docstring, item 4).
FASE_PETICAO_CONTEUDO_JURIDICO = "Petição diversa com conteúdo jurídico"
FASE_PETICAO_SIMPLES = "Petição simples"
FASE_PETICAO_INICIAL = "Petição inicial"
FASE_PETICAO_RECURSO = "Petição. Recurso"
FASE_DESPACHO = "Despacho. Impulso do paj"

# Tipos de arquivo do modal de anexo (por TEXTO — o value carrega hash Java).
TIPO_ARQUIVO_PETICOES = "Petições"
TIPO_ARQUIVO_DESPACHOS = "Despachos do Defensor"


class MovimentacaoAbortada(RuntimeError):
    """Uma trava de seguranca reprovou a operacao — nada foi gravado."""


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip()


def _e_fase_peticao(fase_texto: str) -> bool:
    """True se a fase e de PETICAO (nao despacho, decurso, arquivamento...).

    Usado para decidir o padrao de `mostrar_na_internet`: o Defensor definiu
    que peca com conteudo juridico entra SEM exibir a descricao ao assistido
    no acompanhamento pela internet.
    """
    t = _norm(fase_texto).lower()
    t = t.replace("ção", "cao").replace("çã", "ca").replace("ç", "c")
    t = t.replace("í", "i").replace("é", "e").replace("ú", "u").replace("á", "a")
    return t.startswith("peticao")


async def _abrir_tela_movimentacao(page, paj_texto: str) -> None:
    """Clica em Movimentar e valida que a tela aberta e do PAJ pretendido."""
    # Sessao bloqueada por login em outra estacao? O modal cobre a tela e
    # nenhum clique chega ao destino. Desbloqueia antes de tentar.
    if await sc.sessao_bloqueada(page):
        if not await sc.desbloquear_sessao(page):
            raise MovimentacaoAbortada(
                "sessao do SISDPU bloqueada (login em outra estacao) e nao "
                "consegui desbloquear — feche o SISDPU no navegador e repita"
            )

    # O link existe sempre, mas nem sempre e' "clicavel" para o Playwright
    # (fora da area visivel ou coberto por overlay, conforme o estado da tela).
    # Tenta o clique normal e, se falhar, rola ate ele e dispara o onclick por
    # JS. Isso e' seguro porque quem garante o alvo nao e' o clique, e' a
    # validacao do cabecalho logo abaixo — se cair na tela errada, aborta.
    sel = '[id="detalhamentoForm:LnkMovimentar"]'
    try:
        await page.locator(sel).scroll_into_view_if_needed(timeout=10000)
        await page.click(sel, timeout=10000)
    except Exception as e:
        _log.warning("clique normal em Movimentar falhou (%s); via JS", type(e).__name__)
        disparou = await page.evaluate(
            """() => {
                const el = document.getElementById('detalhamentoForm:LnkMovimentar');
                if (!el) return false;
                el.click();
                return true;
            }"""
        )
        if not disparou:
            raise MovimentacaoAbortada(
                "nao encontrei o link 'Movimentar' na tela do PAJ — abortado"
            )
    await page.wait_for_timeout(2500)
    await sc._wait_pf_ajax(page, timeout=20000)
    await page.wait_for_timeout(1500)

    # A lista autoritativa de PAJs a movimentar e o <select> escondido do
    # PrimeFaces (`processosSelecionados_input`) — e' ele que vai no submit.
    # Nao usar `querySelector('textarea')`: o unico textarea da pagina e o do
    # CKEditor da descricao, que esta vazio e produzia falso positivo.
    info = await page.evaluate(
        """
        () => {
            const corpo = document.body.innerText || '';
            const m = corpo.match(/Movimenta[cç][aã]o do PAJ:\\s*([0-9/\\-]+)/i);
            const sel = document.getElementById(
                'formHonorario:processosSelecionados_input');
            return {
                cabecalho: m ? m[1].trim() : '',
                selecionados: sel
                    ? Array.from(sel.options).map(o => (o.text || '').trim())
                    : null,
            };
        }
        """
    )

    if info["cabecalho"] != paj_texto:
        raise MovimentacaoAbortada(
            f"a tela aberta e do PAJ {info['cabecalho']!r}, mas o alvo e "
            f"{paj_texto!r} — abortado sem gravar nada"
        )
    lista = info["selecionados"]
    if lista is None:
        raise MovimentacaoAbortada(
            "nao localizei a lista de PAJs selecionados na tela — abortado"
        )
    if lista != [paj_texto]:
        raise MovimentacaoAbortada(
            f"a lista de PAJs a movimentar e {lista!r}; esperava exatamente "
            f"[{paj_texto!r}] — abortado para nao movimentar PAJ errado"
        )
    _log.info("tela de movimentacao confirmada para o PAJ %s", paj_texto)


async def _selecionar_fase(page, fase_texto: str) -> str:
    """Seleciona a fase casando pelo TEXTO do option. Retorna o texto casado."""
    achado = await page.evaluate(
        """
        (alvo) => {
            const s = document.getElementById('formHonorario:faseId');
            if (!s) return null;
            const norm = t => (t || '').replace(/\\s+/g, ' ').trim().toLowerCase();
            const a = norm(alvo);
            for (const o of s.options) {
                const t = norm(o.text);
                if (t === a || t.startsWith(a)) {
                    return {value: o.value, text: o.text.trim()};
                }
            }
            return null;
        }
        """,
        fase_texto,
    )
    if not achado:
        opcoes = await page.evaluate(
            """() => Array.from(
                   document.getElementById('formHonorario:faseId').options
               ).map(o => o.text.trim())"""
        )
        raise MovimentacaoAbortada(
            f"fase {fase_texto!r} nao existe na lista. Disponiveis: {opcoes}"
        )

    await page.select_option(f'[id="{FORM}:faseId"]', achado["value"])
    await page.wait_for_timeout(2500)
    await sc._wait_pf_ajax(page, timeout=20000)
    await page.wait_for_timeout(1500)

    entrou = await page.evaluate(
        """
        (txt) => {
            const trs = document.querySelectorAll(
                '[id^="formHonorario:dataTableFasesSelecionadas"] tbody tr');
            for (const tr of trs)
                if ((tr.innerText || '').includes(txt)) return true;
            return false;
        }
        """,
        achado["text"],
    )
    if not entrou:
        raise MovimentacaoAbortada(
            f"a fase {achado['text']!r} foi escolhida mas nao entrou na tabela "
            "de fases selecionadas — abortado"
        )
    _log.info("fase selecionada: %s", achado["text"])
    return achado["text"]


async def _anexar_arquivos(
    page, arquivos: list[Path], tipo_arquivo: str = TIPO_ARQUIVO_PETICOES
) -> list[str]:
    """Sobe os arquivos pelo modal da fase e CONFIRMA cada um em "Anexar".

    O modal tem DUAS tabelas, e confundi-las custou um anexo perdido em
    2026-09-03 (movimentacao gravada sem arquivo):

      formHonorario:arquivosSalvar ... FILA do upload. O nome do arquivo
          aparece aqui logo depois do set_input_files, junto dos campos
          "Descricao" e "Tipo de arquivo" e do botao "Anexar" da propria linha.
      formHonorario:tabelaArquivos .. anexos de FATO ligados a movimentacao.
          Comeca em "Nenhum registro recuperado".

    Fechar o modal com a fila cheia DESCARTA o upload — a movimentacao grava
    sem anexo e nao ha como remove-la depois. Por isso, para cada item da fila
    escolhe-se o Tipo de arquivo e clica-se em "Anexar", e a validacao final
    le `tabelaArquivos` (nao a fila, que sempre casaria).
    """
    abriu = await page.evaluate(
        """
        () => {
            const ls = document.querySelectorAll(
                '[id^="formHonorario:dataTableFasesSelecionadas"] a');
            for (const a of ls)
                if (/adicionar anexo/i.test(a.textContent || '')) {
                    a.click();
                    return true;
                }
            return false;
        }
        """
    )
    if not abriu:
        raise MovimentacaoAbortada("nao encontrei o link 'Adicionar Anexo'")
    await page.wait_for_timeout(2500)
    await sc._wait_pf_ajax(page, timeout=20000)
    await page.wait_for_timeout(1500)

    await page.set_input_files(
        f'[id="{FORM}:arquivosFase_input"]', [str(a) for a in arquivos]
    )
    await page.wait_for_timeout(3000)
    await sc._wait_pf_ajax(page, timeout=60000)
    await page.wait_for_timeout(2500)

    # A fila tem de ter recebido os arquivos antes de tentar confirmar.
    fila = await page.evaluate(
        """() => {
            const d = document.getElementById('formHonorario:arquivosSalvar_data');
            return d ? (d.innerText || '') : '';
        }"""
    )
    faltando = [a.name for a in arquivos if a.name not in fila]
    if faltando:
        raise MovimentacaoAbortada(
            f"os arquivos {faltando} nao entraram na fila do modal — abortado. "
            f"Fila: {_norm(fila)[:300]!r}"
        )

    # Cada clique em "Anexar" consome a linha 0 da fila via ajax e a manda para
    # tabelaArquivos; por isso trabalha-se sempre sobre a primeira linha.
    linhas = f'[id="{FORM}:arquivosSalvar_data"] tr[data-ri]'
    pendentes = list(arquivos)
    for _ in range(len(arquivos) + 2):
        if await page.locator(linhas).count() == 0:
            break
        linha = page.locator(linhas).first
        atual = pendentes.pop(0) if pendentes else None
        nome = atual.name if atual else _norm(await linha.inner_text())[:80]

        desc = linha.locator('input[id$=":desc"]')
        if await desc.count() and atual:
            await desc.first.fill(Path(atual.name).stem[:100])
            await page.wait_for_timeout(800)
            await sc._wait_pf_ajax(page, timeout=20000)

        sel = linha.locator('select[id$=":tipoArquivo"]')
        if await sel.count():
            await sel.first.select_option(label=tipo_arquivo)
            await page.wait_for_timeout(1200)
            await sc._wait_pf_ajax(page, timeout=20000)

        botao = linha.locator('button:has-text("Anexar")')
        if not await botao.count():
            raise MovimentacaoAbortada(
                f"nao encontrei o botao 'Anexar' na linha da fila ({nome!r}) "
                "— abortado para nao gravar movimentacao sem anexo"
            )
        await botao.first.click()
        await page.wait_for_timeout(2500)
        await sc._wait_pf_ajax(page, timeout=60000)
        await page.wait_for_timeout(1500)
        _log.info("'Anexar' concluido para %s", nome)

    # Validacao que importa: a tabela de anexos da movimentacao.
    tabela = await page.evaluate(
        """() => {
            const d = document.getElementById('formHonorario:tabelaArquivos_data');
            return d ? (d.innerText || '') : '';
        }"""
    )
    confirmados, faltando = [], []
    for a in arquivos:
        visto = a.name in tabela or Path(a.name).stem[:60].upper() in tabela.upper()
        (confirmados if visto else faltando).append(a.name)
    if faltando:
        raise MovimentacaoAbortada(
            f"os arquivos {faltando} nao apareceram em tabelaArquivos apos o "
            f"'Anexar' — abortado. Tabela: {_norm(tabela)[:300]!r}"
        )
    _log.info("anexos confirmados em tabelaArquivos: %s", confirmados)

    # Agora o modal pode fechar: a gravacao final e no botao "Movimentar".
    await page.evaluate(
        """() => {
            const d = document.getElementById('formHonorario:dlgModalArquivos');
            if (!d) return;
            for (const b of d.querySelectorAll('button,a'))
                if (/fechar/i.test(b.textContent || '')) { b.click(); return; }
        }"""
    )
    await page.wait_for_timeout(1500)
    await sc._wait_pf_ajax(page, timeout=20000)
    return confirmados


async def _preencher_descricao(page, descricao_html: str) -> str:
    """Escreve no CKEditor da descricao e devolve o que ficou nele."""
    await page.evaluate(
        """
        (html) => {
            const inst = window.CKEDITOR
                && CKEDITOR.instances['formHonorario_editorValue'];
            if (inst) { inst.setData(html); return; }
            const ifr = document.querySelector('iframe.cke_wysiwyg_frame');
            if (ifr && ifr.contentDocument) {
                ifr.contentDocument.body.innerHTML = html;
            }
        }
        """,
        descricao_html,
    )
    await page.wait_for_timeout(1200)
    atual = await page.evaluate(
        """() => {
            const i = window.CKEDITOR
                && CKEDITOR.instances['formHonorario_editorValue'];
            return i ? i.getData() : '';
        }"""
    )
    if descricao_html.strip() and not _norm(re.sub(r"<[^>]+>", " ", atual)):
        raise MovimentacaoAbortada(
            "a descricao nao entrou no editor (CKEditor vazio) — abortado"
        )
    return atual


async def inserir_movimentacao(
    *,
    numero: str,
    ano: str,
    unidade: str = "56",
    fase: str = FASE_PETICAO_CONTEUDO_JURIDICO,
    descricao_html: str = "",
    anexos: list[str | Path] | None = None,
    tipo_arquivo: str = TIPO_ARQUIVO_PETICOES,
    mostrar_na_internet: bool | None = None,
    tipo_movimentacao: str = TIPO_MOVIMENTACAO_MANUAL,
    assistido_esperado: str = "",
    confirmar: bool = False,
) -> dict:
    """Inclui movimentacao no PAJ. Com `confirmar=False` (padrao) NAO grava.

    Retorna dict com o que foi preenchido, o screenshot e, quando
    `confirmar=True`, a verificacao pos-gravacao.
    """
    paj_texto = f"{ano}/{unidade.zfill(3)}-{numero}"
    caminhos = [Path(a) for a in (anexos or [])]
    for c in caminhos:
        if not c.is_file():
            raise MovimentacaoAbortada(f"anexo inexistente: {c}")

    resultado: dict = {
        "paj": paj_texto,
        "fase": None,
        "anexos": [],
        "descricao_no_editor": "",
        "gravado": False,
        "dry_run": not confirmar,
        "screenshot": None,
    }

    det = await sc.buscar_paj_global(numero, ano, unidade)
    if det.get("erro"):
        raise MovimentacaoAbortada(f"nao abri o PAJ {paj_texto}: {det['erro']}")
    resultado["assistido"] = det.get("assistido") or "?"

    # Trava 7: o PAJ aberto e' o do assistido que o painel registrou? O numero
    # do PAJ ja' foi conferido no cabecalho, mas quem anexa em lote marca por
    # linha, e linha trocada e' documento na pasta de outro assistido. Confere
    # antes de preencher qualquer campo.
    if assistido_esperado:
        from services.despacho_firac import mesmo_assistido

        vivo = det.get("assistido") or ""
        if not mesmo_assistido(assistido_esperado, vivo):
            raise MovimentacaoAbortada(
                f"assistido divergente no PAJ {paj_texto}: o painel esperava "
                f"{assistido_esperado!r} e o SISDPU mostra {vivo!r}"
            )
    movs_antes = len(det.get("movimentacoes") or [])
    resultado["movs_antes"] = movs_antes

    page = await sc._get_page()
    await _abrir_tela_movimentacao(page, paj_texto)

    await page.select_option(f'[id="{FORM}:MovId"]', tipo_movimentacao)
    await page.wait_for_timeout(1500)
    await sc._wait_pf_ajax(page, timeout=20000)

    resultado["fase"] = await _selecionar_fase(page, fase)

    if caminhos:
        resultado["anexos"] = await _anexar_arquivos(
            page, caminhos, tipo_arquivo=tipo_arquivo
        )

    if descricao_html:
        resultado["descricao_no_editor"] = await _preencher_descricao(
            page, descricao_html
        )

    # Padrao definido pelo Defensor: em movimentacao de PETICAO, a descricao
    # NAO fica visivel ao assistido na internet (o SISDPU marca por padrao).
    # Nas demais fases mantem-se o comportamento nativo da tela.
    if mostrar_na_internet is None and _e_fase_peticao(resultado["fase"]):
        mostrar_na_internet = False
        _log.info("fase de peticao: desmarcando exibicao na internet")

    if mostrar_na_internet is not None:
        await page.evaluate(
            """(marcar) => {
                const c = document.getElementById(
                    'formHonorario:mostrarDescricaoNaInternet');
                if (c && c.checked !== marcar) c.click();
            }""",
            mostrar_na_internet,
        )
        await page.wait_for_timeout(800)
    resultado["mostrar_na_internet"] = await page.evaluate(
        """() => {
            const c = document.getElementById(
                'formHonorario:mostrarDescricaoNaInternet');
            return c ? c.checked : null;
        }"""
    )

    shot = Path("logs") / f"movimentacao_{paj_texto.replace('/', '-')}.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(shot), full_page=True)
    resultado["screenshot"] = str(shot)

    if not confirmar:
        _log.info("DRY-RUN: formulario preenchido, NAO submetido")
        resultado["aviso"] = (
            "DRY-RUN — nada foi gravado. Revise o screenshot e rode de novo "
            "com confirmar=True para efetivar."
        )
        return resultado

    # O SIS pode ter bloqueado a sessao enquanto a tela era preenchida: basta
    # o Defensor entrar no SISDPU pelo navegador. O modal de desbloqueio engole
    # o clique, e o sintoma seria um timeout de 30s sobre um botao descrito
    # como visivel e habilitado. Trata-se antes de submeter.
    if await sc.sessao_bloqueada(page):
        if not await sc.desbloquear_sessao(page):
            raise MovimentacaoAbortada(
                "sessao do SISDPU bloqueada (login em outra estacao) e nao "
                "consegui desbloquear — feche o SISDPU no navegador e repita"
            )

    _log.warning("SUBMETENDO movimentacao no PAJ %s", paj_texto)
    await page.click(f'[id="{FORM}:btnMovimentarTopo"]')
    await page.wait_for_timeout(4000)
    await sc._wait_pf_ajax(page, timeout=60000)
    await page.wait_for_timeout(3000)

    resultado["mensagem_tela"] = _norm(
        await page.evaluate(
            """() => {
                const m = document.querySelector('.ui-messages, .ui-growl, .alert');
                return m ? (m.innerText || '') : '';
            }"""
        )
    )[:300]

    # Verificacao independente: rele o PAJ e compara a contagem.
    depois = await sc.buscar_paj_global(numero, ano, unidade)
    movs = depois.get("movimentacoes") or []
    resultado["movs_depois"] = len(movs)
    resultado["gravado"] = len(movs) > movs_antes
    if movs:
        resultado["ultima_movimentacao"] = _norm(movs[0].get("descricao") or "")[:220]
    if not resultado["gravado"]:
        resultado["aviso"] = (
            "SUBMETI, mas a contagem de movimentacoes nao aumentou — confira "
            "manualmente no SISDPU antes de repetir, para nao duplicar."
        )
    return resultado
