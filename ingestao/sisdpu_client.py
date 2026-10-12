"""Cliente SISDPU via Playwright headless (async).

Portado de dpu-workspace-main/dpuscript/mcp_servers/sisdpu/client.py.
Mantido como funcoes modulo-level com estado global de browser/page para
simplificar uso; concorrencia de sincronizacao e' serializada por um
asyncio.Lock em services/sync_service.py.

Credenciais vem das env vars SISDPU_USERNAME e SISDPU_PASSWORD (carregadas do
.env pelo config.py).
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from playwright.async_api import Browser, Page, async_playwright
from playwright.async_api import TimeoutError as PWTimeoutError
import contextlib


SISDPU_URL = "https://sisdpu.dpu.def.br/sisdpu"

# Logger dedicado — os logs `[busca-paj]` vao para logs/app.log (handler
# configurado em app.py com rotacao diaria). Tambem aparecem no console
# quando o painel e' iniciado num terminal visivel.
_log = logging.getLogger("sisdpu.busca")

# Diretorio onde despejamos screenshot + HTML quando a busca via campo global
# falha — facilita o diagnostico (DOM real do SISDPU vs nossa heuristica).
_DEBUG_DIR = Path(__file__).resolve().parents[1] / "logs" / "sisdpu_debug"


class CredenciaisInvalidas(Exception):
    """SISDPU rejeitou usuario/senha no login."""
    pass


_playwright: Any = None
_browser: Browser | None = None
_page: Page | None = None


# JS que espera o PrimeFaces terminar todos os AJAX pendentes.
# Predicado para `wait_for_function`: verdadeiro quando nao ha AJAX PrimeFaces
# pendente. O Playwright reavalia sozinho ate ser verdadeiro (ou estourar o
# timeout), entao aqui NAO se usa Promise/setTimeout — basta a condicao.
_PF_AJAX_OCIOSO = """
() => typeof PrimeFaces === 'undefined'
      || !PrimeFaces.ajax
      || !PrimeFaces.ajax.Queue
      || PrimeFaces.ajax.Queue.isEmpty()
"""


def _sel(element_id: str) -> str:
    """Gera seletor CSS para IDs JSF (que contem ':')."""
    return f'[id="{element_id}"]'


# Ordem de preferencia de navegador para o Playwright.
#
# O Chromium EMPACOTADO vem primeiro de proposito: com ele o flag
# `--disable-features=PDFViewerUpdate,PdfUnseasoned` realmente faz os PDFs
# virarem download (evento `download`), que e' como `listar_arquivos_paj`
# captura os anexos. No Chrome/Edge instalados o PDF abre no visualizador
# interno e o download FALHA — por isso eles nao podem ser o padrao.
#
# Chrome/Edge entram apenas como rede de seguranca: o binario empacotado fica
# em %LOCALAPPDATA%\ms-playwright, nao e' assinado, e o Smart App Control do
# Windows 11 (VerifiedAndReputablePolicyState=1 nesta maquina) as vezes o
# bloqueia — tipicamente logo depois de a politica ser reaplicada, o que
# invalida o veredito de reputacao em cache. O Playwright traduz esse bloqueio
# na mensagem enganosa "Executable doesn't exist" (seu `canAccessFile()`
# engole o erro real). Nesse cenario, cair para o Chrome assinado deixa a
# sincronizacao de movimentacoes/prazos funcionar; so' o download de anexos
# fica prejudicado, e o log avisa disso.
_CANAIS_PREFERIDOS: tuple[str | None, ...] = (None, "chrome", "msedge")

# Canal que funcionou por ultimo — tentado primeiro nas chamadas seguintes,
# pra nao pagar o custo de descobrir de novo a cada launch.
_INDEFINIDO = object()
_canal_em_uso: Any = _INDEFINIDO


def _ordem_de_canais() -> list[str | None]:
    """Canais a tentar, sempre na ordem de _CANAIS_PREFERIDOS.

    NAO memoriza o canal que funcionou por ultimo de proposito: o empacotado
    (unico que baixa anexos corretamente) tem que ser retentado sempre, senao
    um unico bloqueio do Smart App Control deixaria o painel preso no Chrome
    — e sem download de anexos — mesmo depois de o bloqueio passar.
    """
    forcado = os.getenv("PLAYWRIGHT_CHANNEL", "").strip()
    if forcado:
        # "chromium" (ou "bundled") = usar explicitamente o Chromium empacotado
        return [None] if forcado.lower() in ("chromium", "bundled", "none") else [forcado]
    return list(_CANAIS_PREFERIDOS)


def _memorizar_canal(canal: str | None, rodada: int, houve_falha: bool) -> None:
    """Registra o canal em uso. Avisa alto quando cai para um substituto,
    porque nesse modo o download de anexos nao funciona."""
    global _canal_em_uso
    _canal_em_uso = canal
    if canal is None:
        if houve_falha:
            _log.warning("playwright.launch: Chromium empacotado OK na rodada %d", rodada + 1)
        else:
            _log.info("playwright.launch: Chromium empacotado")
        return
    _log.warning(
        "playwright.launch: Chromium empacotado indisponivel (provavel bloqueio do "
        "Smart App Control) — usando '%s' como substituto. ATENCAO: neste modo o "
        "DOWNLOAD DE ANEXOS falha (PDF abre no visualizador em vez de baixar); "
        "movimentacoes/prazos/triagem funcionam normalmente.",
        canal,
    )


def _diagnosticar_falha_launch(erro: Exception, rodada: int, canal: str | None) -> None:
    """Loga diagnostico concreto quando `chromium.launch()` falha.

    O driver Node do Playwright reporta QUALQUER falha de acesso ao
    executavel (permissao negada, bloqueio por politica de seguranca,
    antivirus etc.) com a mesma mensagem generica "Executable doesn't exist"
    (ver `canAccessFile()`, que engole o erro real). Aqui chamamos
    `os.stat()` no MESMO arquivo, no MESMO instante, e registramos a excecao
    de verdade — inclusive o errno — pra distinguir "arquivo ausente" de
    "acesso bloqueado". Note que `Path.exists()` NAO serve pra isso: ele
    tambem retorna False quando o stat falha por permissao.
    """
    msg = str(erro)
    primeira = msg.splitlines()[0] if msg else ""
    detalhes = [f"rodada {rodada + 1} canal={canal or 'chromium-empacotado'}",
                f"{type(erro).__name__}: {primeira}"]

    m = re.search(r"Executable doesn't exist at (.+?)(?:\r?\n|$)", msg)
    if m:
        p = Path(m.group(1).strip())
        try:
            st = os.stat(p)
            detalhes.append(
                f"os.stat OK (arquivo PRESENTE): tamanho={st.st_size} "
                f"mtime={_dt.datetime.fromtimestamp(st.st_mtime).isoformat()}"
            )
            try:
                with open(p, "rb") as f:
                    f.read(4)
                detalhes.append("leitura OK -> bloqueio e' de EXECUCAO, nao de leitura")
            except OSError as e_open:
                detalhes.append(f"leitura FALHOU: {type(e_open).__name__} errno={e_open.errno}: {e_open}")
        except OSError as e_stat:
            detalhes.append(
                f"os.stat FALHOU: {type(e_stat).__name__} errno={e_stat.errno} "
                f"winerror={getattr(e_stat, 'winerror', None)}: {e_stat}"
            )

    _log.warning("playwright.launch falhou — %s", " | ".join(detalhes))


async def _get_page() -> Page:
    """Retorna a page Playwright, criando browser se necessario.

    O Chromium e' iniciado com flags que FORCAM download de PDFs em vez de
    abrir o preview interno — importante pro `listar_arquivos_paj`, ja que
    queremos capturar o arquivo bruto via evento `download`, nao previsualizar.
    """
    global _playwright, _browser, _page
    if _page is not None:
        try:
            # Acessa atributo so para verificar que a page ainda esta viva;
            # se foi fechada, levanta exception e caimos no reset abaixo.
            _ = _page.url
            return _page
        except Exception:
            _page = None
            _browser = None

    # Tenta os canais em ordem de confiabilidade (ver _CANAIS_PREFERIDOS), com
    # backoff entre rodadas caso TODOS falhem — cobre bloqueio transitorio.
    canais = _ordem_de_canais()
    ESPERAS = [2, 5, 10]  # backoff entre rodadas completas de canais
    ultimo_erro: Exception | None = None

    for rodada in range(len(ESPERAS) + 1):
        for canal in canais:
            if _playwright is None:
                _playwright = await async_playwright().start()
            try:
                _browser = await _playwright.chromium.launch(
                    headless=True,
                    channel=canal,  # None => Chromium empacotado do Playwright
                    args=[
                        # Desabilita o PDF viewer interno: PDFs viram download
                        "--disable-features=PDFViewerUpdate,PdfUnseasoned",
                    ],
                )
                _memorizar_canal(canal, rodada, ultimo_erro is not None)
                break
            except Exception as e:
                ultimo_erro = e
                _diagnosticar_falha_launch(e, rodada, canal)
                with contextlib.suppress(Exception):
                    await _playwright.stop()
                _playwright = None
                _browser = None
        if _browser is not None:
            break
        if rodada < len(ESPERAS):
            await asyncio.sleep(ESPERAS[rodada])

    if _browser is None:
        raise ultimo_erro

    context = await _browser.new_context(
        viewport={"width": 1280, "height": 1024},
        accept_downloads=True,
    )
    _page = await context.new_page()
    return _page


# Sessao logada de verdade? Exige o titulo da unidade e o botao Pesquisar do
# header — ambos presentes em toda tela autenticada do SIS. Usado pelas duas
# tentativas de `buscar_paj_global` (sessao reusada e sessao nova).
_JS_SESSAO_VIVA = """() => {
            const corpo = (document.body.innerText || '').toLowerCase();
            const temUnidade = corpo.includes('unidade dpu');
            const cands = document.querySelectorAll(
                'button, input[type="submit"], input[type="button"], input[type="image"], a, span[role="button"]'
            );
            let temBtnPesquisar = false;
            for (const el of cands) {
                const txt = ((el.textContent || el.value || el.title || el.getAttribute('aria-label') || '') + '').trim().toLowerCase();
                if (txt === 'pesquisar' || txt === 'buscar' || txt.includes('pesquis')) {
                    temBtnPesquisar = true; break;
                }
            }
            return {
                ok: temUnidade && temBtnPesquisar,
                temUnidade, temBtnPesquisar,
                trecho_inicio_body: corpo.substring(0, 200)
            };
        }"""


async def _wait_pf_ajax(page: Page, timeout: int = 10000) -> None:
    """Espera o PrimeFaces terminar o AJAX pendente, com timeout de seguranca.

    Usa `wait_for_function` (que ACEITA timeout) em vez de `evaluate`. A versao
    anterior chamava `page.evaluate(js, timeout=...)`, mas `evaluate` so' aceita
    `(expression, arg)`: o kwarg levantava TypeError em TODA chamada, caia no
    `except` e dormia 1s as cegas. Ou seja, nunca esperava o AJAX de fato —
    era lentidao (1s fixo por chamada) e risco de ler a pagina antes de ela
    terminar de atualizar. Agora retorna assim que a fila esvazia (ms).
    """
    try:
        await page.wait_for_function(_PF_AJAX_OCIOSO, timeout=timeout)
    except Exception:
        # Fila nunca esvaziou dentro do timeout: segue em frente, como antes.
        # Quem chama tem verificacao propria do conteudo esperado.
        pass


async def _login() -> None:
    """Faz login no SISDPU."""
    user = os.environ.get("SISDPU_USERNAME", "")
    senha = os.environ.get("SISDPU_PASSWORD", "")
    if not user or not senha:
        raise RuntimeError(
            "SISDPU_USERNAME/SISDPU_PASSWORD não definidos no ambiente (.env)"
        )
    page = await _get_page()
    await page.goto(f"{SISDPU_URL}/login.xhtml", wait_until="domcontentloaded")
    await page.wait_for_selector(_sel("frmLogin:epaj_input_usuario"), timeout=15000)
    await page.fill(_sel("frmLogin:epaj_input_usuario"), user)
    await page.fill(_sel("frmLogin:epaj_input_senha"), senha)
    await page.evaluate('PrimeFaces.ab({s:"frmLogin:loginButton",f:"frmLogin"})')
    try:
        await page.wait_for_url("**/caixaEntrada**", timeout=15000)
    except PWTimeoutError:
        # Nao chegou na caixa — checar se SISDPU recusou as credenciais.
        # PrimeFaces exibe erros em .ui-messages-error, .mensagem-erro, ou
        # um <div class="ui-growl-message"> com texto de usuario/senha.
        msg_recusa = await page.evaluate(
            """() => {
                const seletores = [
                    '.ui-messages-error-detail',
                    '.ui-messages-error',
                    '.mensagem-erro',
                    '.ui-growl-message',
                    '#frmLogin .ui-message-error',
                ];
                for (const s of seletores) {
                    const el = document.querySelector(s);
                    if (el && el.innerText && el.innerText.trim()) {
                        return el.innerText.trim();
                    }
                }
                // fallback: varrer body por frase caracteristica
                const body = (document.body.innerText || '').toLowerCase();
                const pistas = [
                    'usu\u00e1rio ou senha', 'usuario ou senha',
                    'senha incorreta', 'senha inv\u00e1lida', 'senha invalida',
                    'credenciais inv\u00e1lidas', 'credenciais invalidas',
                    'login inv\u00e1lido', 'login invalido',
                ];
                for (const p of pistas) {
                    const i = body.indexOf(p);
                    if (i >= 0) return body.substr(Math.max(0, i - 20), 120);
                }
                return null;
            }"""
        )
        if msg_recusa:
            raise CredenciaisInvalidas(msg_recusa[:200]) from None
        # Nao foi login fail explicito — repropaga como timeout.
        raise


async def _ensure_logged_in() -> None:
    """Garante que estamos logados. Refaz login se sessao expirou."""
    global _browser, _page
    page = await _get_page()
    try:
        url = page.url
        if "login" in url or not url.startswith("http"):
            await _login()
            return
        await page.goto(
            f"{SISDPU_URL}/pages/caixaentrada/caixaEntrada.xhtml",
            wait_until="domcontentloaded",
            timeout=10000,
        )
        await page.wait_for_timeout(500)
        if "login" in page.url:
            await _login()
    except Exception:
        try:
            if _browser:
                await _browser.close()
        except Exception:
            pass
        _browser = None
        _page = None
        await _login()


async def caixa_de_entrada() -> dict:
    """Navega para a caixa de entrada e extrai os itens listados."""
    await _ensure_logged_in()
    page = await _get_page()
    await page.goto(
        f"{SISDPU_URL}/pages/caixaentrada/caixaEntrada.xhtml",
        wait_until="domcontentloaded",
    )
    await page.wait_for_timeout(2000)
    await _wait_pf_ajax(page, timeout=10000)

    body = await page.inner_text("body")

    table_data = await page.evaluate(
        """
        () => {
            const tables = document.querySelectorAll(
                '.ui-datatable-data tr, .ui-datalist-content .ui-datalist-item'
            );
            if (tables.length > 0) {
                return Array.from(tables).map(tr => tr.innerText.trim())
                    .filter(t => t.length > 0);
            }
            const allTr = document.querySelectorAll('table tbody tr');
            return Array.from(allTr).map(tr => tr.innerText.trim())
                .filter(t => t.length > 0);
        }
        """
    )

    return {
        "url": page.url,
        "itens_tabela": table_data or [],
        "texto_pagina": body[:5000],
    }


def parse_item_caixa(item_raw: str) -> dict | None:
    """Extrai {paj, oficio, assistido, data, desc, etiqueta} de uma linha da caixa.

    Aceita etiquetas SISDPU (rotulos livres que o Defensor aplica na caixa, tipo
    "Aleg finais", "Urgente", etc.) presentes como prefixo antes do PAJ. O PAJ e'
    capturado com re.search (posicional), e o texto anterior vira 'etiqueta'.

    Portado de preparar_pajs.py._parse_item.
    """
    parts = [p.strip() for p in item_raw.split("\t")]
    header = parts[0] if parts else ""
    m = re.search(r"(\d{4}/\d{3}-\d+)\s*\n?\(?\s*(.*?)\s*\)?$", header, re.DOTALL)
    if not m:
        return None
    paj = m.group(1).strip()
    oficio = m.group(2).replace("E.", "").strip()
    # Etiqueta = texto ANTES do PAJ (se houver). Strip pra limpar espacos/newlines.
    etiqueta = header[: m.start(1)].strip()
    assistido = parts[1] if len(parts) > 1 else ""
    data = parts[2] if len(parts) > 2 else ""
    descricao = parts[-1] if len(parts) >= 5 else ""
    return {
        "paj": paj,
        "oficio": oficio[:120],
        "assistido": assistido[:120],
        "data": data,
        "desc": descricao,
        "etiqueta": etiqueta[:80],
    }


MAX_RETORNOS_EXPANDIR = 3


async def _expandir_atendimentos_retorno(page) -> int:
    """Expande as linhas "Atendimento de retorno" (rowExpansion do PrimeFaces).

    O TEOR CERTIFICADO do retorno (ex.: "Assistido respondeu o seguinte: ...")
    NAO vem no DOM inicial: o SISDPU so' o carrega, via ajax, quando se clica no
    toggle da linha. Sem expandir, a movimentacao de atendimento de retorno
    chega praticamente vazia e a analise nao tem como saber o que o assistido
    trouxe ou respondeu — era a causa das analises fracas nesse fluxo.

    Cada clique e' um ajax; expandimos apenas os N retornos MAIS RECENTES (sao
    os que explicam o retorno a caixa). A tabela vem do mais novo para o mais
    antigo e o toggle fechado tem a classe `ui-icon-circle-triangle-e` (ao abrir
    vira `...-s`); como sempre clicamos no PRIMEIRO ainda fechado, N cliques
    abrem exatamente os N mais recentes.

    Retorna quantas linhas foram expandidas. Falhas sao silenciosas — expandir
    e' um extra: se nao der, a sincronizacao segue com o texto normal.
    """
    expandidas = 0
    try:
        for _ in range(MAX_RETORNOS_EXPANDIR):
            tog = page.locator(
                '[id="detalhamentoForm:tableMovimentacoes"] '
                'div.ui-row-toggler.ui-icon-circle-triangle-e'
            ).first
            if await tog.count() == 0:
                break
            try:
                await tog.click(timeout=3000)
            except Exception:
                break
            await _wait_pf_ajax(page, timeout=8000)
            await page.wait_for_timeout(300)
            expandidas += 1
    except Exception:
        pass
    if expandidas:
        _log.info("atendimento de retorno: %d linha(s) expandida(s)", expandidas)
    return expandidas


async def movimentacoes_paj(numero: str, ano: str, unidade: str = "44") -> dict:
    """Retorna dados completos do PAJ incluindo MOVIMENTACOES com URLs de peca.

    Fluxo: Caixa de Entrada -> clica no TEXTO DO PAJ -> Detalhamento do Processo.
    """
    await _ensure_logged_in()
    page = await _get_page()

    await page.goto(
        f"{SISDPU_URL}/pages/caixaentrada/caixaEntrada.xhtml",
        wait_until="domcontentloaded",
    )
    await _wait_pf_ajax(page, timeout=10000)

    paj_texto = f"{ano}/{unidade.zfill(3)}-{numero}"

    # Espera o LINK do PAJ existir, em vez de dormir 2s no escuro. A tabela da
    # caixa e' preenchida por ajax: o que interessa e' o link estar la'.
    # Timeout curto porque o PAJ pode legitimamente nao estar na caixa — nesse
    # caso o codigo abaixo trata (fallback por numero e, depois, erro).
    with contextlib.suppress(Exception):
        await page.wait_for_function(
            """(alvo) => {
                for (const a of document.querySelectorAll('a'))
                    if ((a.textContent || '').includes(alvo)) return true;
                return false;
            }""",
            arg=paj_texto,
            timeout=8000,
        )

    clicked = await page.evaluate(
        """
        (pajTexto) => {
            const links = document.querySelectorAll('a');
            for (const a of links) {
                if (a.textContent.includes(pajTexto)) { a.click(); return true; }
            }
            return false;
        }
        """,
        paj_texto,
    )

    if not clicked:
        clicked = await page.evaluate(
            """
            (numero) => {
                const links = document.querySelectorAll('a');
                for (const a of links) {
                    if (a.textContent.includes(numero)) { a.click(); return true; }
                }
                return false;
            }
            """,
            numero,
        )

    if not clicked:
        return {"erro": f"PAJ {paj_texto} não encontrado na caixa de entrada"}

    await _wait_pf_ajax(page, timeout=15000)

    # Espera o DETALHAMENTO estar montado, em vez de dormir 3s. O marcador e' a
    # tabela de movimentacoes do formulario de detalhamento — e' dela que a
    # extracao abaixo depende, e e' o ultimo pedaco a chegar.
    # Se nao aparecer, segue: a extracao valida o conteudo e o chamador trata.
    with contextlib.suppress(Exception):
        await page.wait_for_selector(
            '[id="detalhamentoForm:tableMovimentacoes"]',
            state="attached",
            timeout=15000,
        )
    await _wait_pf_ajax(page, timeout=10000)

    await _expandir_atendimentos_retorno(page)

    dados = await page.evaluate(
        """
        () => {
            const r = {};
            const body = document.body.innerText;

            const assistidoMatch = body.match(
                /Assistido\\(s\\)[\\t\\s]+([^\\n]+)/
            );
            if (assistidoMatch) r.assistido = assistidoMatch[1].trim();

            const pajMatch = body.match(/(\\d{4}\\/\\d{3}-\\d+)\\s*-\\s*PAJ\\s+([^\\n]+)/);
            if (pajMatch) {
                r.paj = pajMatch[1];
                r.status_paj = pajMatch[2].trim();
            }

            const oficioMatch = body.match(/Oficio[\\t\\s]+([^\\n]+)/) ||
                                body.match(/Ofício[\\t\\s]+([^\\n]+)/);
            if (oficioMatch) r.oficio = oficioMatch[1].trim();

            // Pretensao — formato "Pretensão  Area >> Subarea >> ..."
            const pretensaoMatch = body.match(
                /Pretens[ãa]o[\\t\\s]+([^\\n]+)/
            );
            if (pretensaoMatch) r.pretensao = pretensaoMatch[1].trim();

            // Data de abertura
            const aberturaMatch = body.match(
                /(?:Data\\s+de\\s+Abertura|Dt\\.?\\s*Abertura)[\\t\\s]+([^\\n]+)/i
            );
            if (aberturaMatch) r.data_abertura = aberturaMatch[1].trim();

            const procMatch = body.match(
                /(\\d{7}-\\d{2}\\.\\d{4}\\.\\d\\.\\d{2}\\.\\d{4})/
            );
            if (procMatch) r.processo_judicial = procMatch[1];

            const juizoMatch = body.match(
                /Juízo\\/Orgão Julgador\\s*\\n\\s*([^\\n]+)/
            ) || body.match(/Juizo\\/Orgao Julgador\\s*\\n\\s*([^\\n]+)/);
            if (juizoMatch) r.juizo = juizoMatch[1].trim();

            // Tabela de movimentacoes
            const movs = [];
            const movRows = document.querySelectorAll('table tbody tr');
            for (const tr of movRows) {
                const cells = tr.querySelectorAll('td');
                if (cells.length >= 5) {
                    const seq = (cells[0]?.textContent || '').trim();
                    const dataHora = (cells[2]?.textContent || '').trim();
                    const movimentacao = (cells[3]?.textContent || '').trim();
                    const fases = (cells[4]?.textContent || '').trim();
                    // innerText preserva a quebra de paragrafo dos <br>/<p> da
                    // celula; textContent colava os paragrafos
                    // ("...curadora especial.A ultima movimentacao...").
                    const textoCompleto = (cells[5]?.innerText
                                           || cells[5]?.textContent || '');
                    const usuario = (cells[6]?.textContent || '').trim();

                    if (seq && /^\\d{1,4}$/.test(seq)
                        && (textoCompleto.trim() || movimentacao)) {
                        const urls = textoCompleto.match(/https?:\\/\\/[^\\s]+/g) || [];
                        const links_decisao = urls.filter(u =>
                            u.includes('stj.jus.br') ||
                            u.includes('stf.jus.br') ||
                            u.includes('portal.stf') ||
                            u.includes('processo.stj') ||
                            u.includes('eproc') ||
                            u.includes('downloadPeca') ||
                            u.includes('documento') ||
                            u.includes('decisao') ||
                            u.endsWith('.pdf')
                        );
                        // Teor certificado do "Atendimento de retorno": fica na
                        // linha de expansao (tr.ui-expanded-row-content) logo
                        // abaixo da linha de dados, e so' existe se o toggle
                        // tiver sido aberto (ver _expandir_atendimentos_retorno).
                        let certificado = '';
                        const prox = tr.nextElementSibling;
                        if (prox && (prox.className || '').indexOf('ui-expanded-row-content') !== -1) {
                            certificado = (prox.innerText || '').replace(/\\s+/g, ' ').trim();
                        }
                        const LIMITE_TEOR = 20000;
                        let descFinal = textoCompleto.substring(0, LIMITE_TEOR);
                        if (textoCompleto.length > LIMITE_TEOR) {
                            descFinal += '\\n[TEOR CORTADO em ' + LIMITE_TEOR
                                + ' caracteres - abra a movimentacao no SISDPU]';
                        }
                        if (certificado) {
                            descFinal += '\\n[ATENDIMENTO DE RETORNO - certificado]: ' + certificado;
                        }
                        movs.push({
                            seq: seq,
                            data: dataHora,
                            movimentacao: movimentacao,
                            fases: fases,
                            descricao: descFinal,
                            certificado: certificado,
                            links_decisao: links_decisao,
                            usuario: usuario
                        });
                    }
                }
            }
            if (movs.length > 0) r.movimentacoes = movs.slice(0, 50);

            return r;
        }
        """
    )

    if not dados:
        dados = {}
    dados["paj_numero"] = numero
    dados["paj_ano"] = ano
    dados["paj_unidade"] = unidade
    dados["url"] = page.url

    todas_urls: list[str] = []
    for m in dados.get("movimentacoes", []) or []:
        for u in m.get("links_decisao", []) or []:
            if u not in todas_urls:
                todas_urls.append(u)
    if todas_urls:
        dados["urls_decisoes"] = todas_urls

    return dados


# JS que dispara a busca rapida do SISDPU. Descobertas chave (vistas no
# page.html do debug):
#  - O botao tem onmouseup="buscarProcesso(event)" (funcao JS customizada).
#  - O resultado abre em POPUP via redirecionar(url, idProcesso) ->
#    window.open(...). Por isso a URL da janela atual nunca muda.
#  - O ano/unidade da busca vem dos hidden inputs anoAtualParaPesquisaRapida
#    e codigoUnidadeParaPesquisaRapida (defaults para a unidade do usuario).
#    Para buscar PAJ de outro ano/unidade temos que alterar esses hidden.
_JS_PESQUISAR_PAJ = """
(args) => {
    const { termo, ano, unidade } = args;
    const debug = {};

    // ----- 1) Hidden inputs ano/unidade — sobrescreve para o PAJ desejado -----
    const anoHidden = document.getElementById('anoAtualParaPesquisaRapida');
    const unidHidden = document.getElementById('codigoUnidadeParaPesquisaRapida');
    if (anoHidden) {
        debug.anoAntes = anoHidden.value;
        anoHidden.value = ano;
        debug.anoDepois = anoHidden.value;
    }
    if (unidHidden) {
        debug.unidAntes = unidHidden.value;
        unidHidden.value = unidade;
        debug.unidDepois = unidHidden.value;
    }

    // ----- 2) Input do numero -----
    const input = document.getElementById('processoPesquisaRapidaNumeroProcesso');
    if (!input) return { ok: false, erro: 'input processoPesquisaRapidaNumeroProcesso nao encontrado', debug };
    debug.inputId = input.id;

    const btn = document.getElementById('botaoPesquisarPesquisaRapida');
    if (!btn) return { ok: false, erro: 'botao botaoPesquisarPesquisaRapida nao encontrado', debug };
    debug.btnId = btn.id;

    input.focus();
    input.value = termo;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));

    // ----- 3) Aciona buscarProcesso(event) — o handler do onmouseup -----
    try {
        if (typeof buscarProcesso === 'function') {
            const ev = new MouseEvent('mouseup', { bubbles: true, cancelable: true });
            Object.defineProperty(ev, 'target', { value: btn, writable: false });
            buscarProcesso(ev);
            debug.metodo = 'buscarProcesso(event)';
            return { ok: true, debug };
        }
        debug.buscarProcesso_disponivel = false;
    } catch (e) {
        debug.busca_erro = e.message;
    }

    // Fallback: dispara mouseup real no botao
    try {
        btn.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
        debug.metodo = (debug.metodo || '') + '+mouseup';
    } catch (e) {
        debug.mouseup_erro = e.message;
    }

    return { ok: true, debug };
}
"""


async def _dump_debug_paj(
    page: Page,
    paj_texto: str,
    motivo: str,
    extras: dict | None = None,
    extra_pages: dict[str, Page] | None = None,
) -> Path:
    """Salva screenshot + HTML + body.innerText + info da pagina atual em
    logs/sisdpu_debug/ para diagnostico. Usado tanto em falhas quanto em
    sucessos durante a fase de afinacao dos seletores. Devolve a pasta criada.

    `extra_pages={"popup": page2, ...}` dumpa tambem essas paginas extras com
    sufixo no nome do arquivo (popup_screenshot.png, popup_body.txt, etc.) —
    util pra capturar popups que foram abertos mas nao bateram a verificacao.
    """
    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = paj_texto.replace("/", "-").replace(" ", "_")
    pasta = _DEBUG_DIR / f"{ts}_{slug}"
    pasta.mkdir(parents=True, exist_ok=True)

    with contextlib.suppress(Exception):
        await page.screenshot(path=str(pasta / "screenshot.png"), full_page=True)
    with contextlib.suppress(Exception):
        html = await page.content()
        (pasta / "page.html").write_text(html, encoding="utf-8")
    with contextlib.suppress(Exception):
        texto = await page.inner_text("body")
        (pasta / "body.txt").write_text(texto, encoding="utf-8")

    info = [
        f"timestamp: {ts}",
        f"paj_texto: {paj_texto}",
        f"motivo: {motivo}",
        f"url: {page.url}",
    ]
    if extras:
        for k, v in extras.items():
            info.append(f"{k}: {v}")

    if extra_pages:
        for nome, pg in extra_pages.items():
            with contextlib.suppress(Exception):
                await pg.screenshot(path=str(pasta / f"{nome}_screenshot.png"), full_page=True)
            with contextlib.suppress(Exception):
                (pasta / f"{nome}_page.html").write_text(await pg.content(), encoding="utf-8")
            with contextlib.suppress(Exception):
                (pasta / f"{nome}_body.txt").write_text(await pg.inner_text("body"), encoding="utf-8")
            with contextlib.suppress(Exception):
                info.append(f"{nome}_url: {pg.url}")

    (pasta / "info.txt").write_text("\n".join(info) + "\n", encoding="utf-8")
    return pasta


async def buscar_paj_global(
    numero: str, ano: str, unidade: str = "44",
) -> dict:
    """Busca um PAJ via campo de pesquisa global do SISDPU (header da caixa).

    Diferente de `movimentacoes_paj`, esta funcao NAO depende do PAJ estar na
    caixa de entrada do defensor — usa o campo "Pesquisar" que aceita qualquer
    PAJ da unidade. Extrai os mesmos dados de cabecalho e movimentacoes.

    Retorna `{"erro": "..."}` se a busca falhar. Em caso de falha, salva
    screenshot + HTML + info em `logs/sisdpu_debug/` para diagnostico.
    """
    paj_texto = f"{ano}/{unidade.zfill(3)}-{numero}"
    _log.info("INICIO termo='%s'", paj_texto)

    # REUSA a sessao existente. A versao anterior fechava o browser e refazia o
    # login em TODA chamada "pra garantir estado limpo" — mas o login do SIS
    # custa 22-25s medidos, pagos mesmo com a sessao perfeitamente viva. A
    # garantia continua: logo abaixo ja' existe verificacao de sessao viva e,
    # se ela reprovar, ai' sim forcamos sessao nova e tentamos de novo. Ou seja,
    # o caminho lento passou a ser excecao em vez de regra.
    async def _abrir_caixa_e_validar(forcar_sessao_nova: bool):
        if forcar_sessao_nova:
            _log.info("forcando nova sessao (fechar+login)...")
            with contextlib.suppress(Exception):
                await fechar()
        await _ensure_logged_in()
        pg = await _get_page()
        await pg.goto(
            f"{SISDPU_URL}/pages/caixaentrada/caixaEntrada.xhtml",
            wait_until="domcontentloaded",
        )
        await _wait_pf_ajax(pg, timeout=10000)
        _log.info("caixa carregada url=%s", pg.url)
        if "login" in pg.url.lower():
            return pg, {"ok": False, "motivo": "redirecionado para tela de login"}
        viva = await pg.evaluate(_JS_SESSAO_VIVA)
        return pg, viva

    page, sessao_viva = await _abrir_caixa_e_validar(forcar_sessao_nova=False)
    if not sessao_viva.get("ok"):
        _log.info("sessao reusada nao serviu (%s) — refazendo login", sessao_viva)
        page, sessao_viva = await _abrir_caixa_e_validar(forcar_sessao_nova=True)

    _log.info("sessao_viva=%s", sessao_viva)
    if not sessao_viva.get("ok"):
        msg = (
            f"sessao SIS-DPU nao confirmada como ativa — "
            f"temUnidade={sessao_viva.get('temUnidade')} "
            f"temBtnPesquisar={sessao_viva.get('temBtnPesquisar')}"
        )
        with contextlib.suppress(Exception):
            pasta = await _dump_debug_paj(
                page, paj_texto, msg, extras={"sessao": sessao_viva},
            )
            _log.warning("FIM(sessao-morta) debug salvo em: %s", pasta)
        return {"erro": msg}

    # Diagnostico inicial — lista os inputs de texto e botoes com texto
    # "Pesquisar"/"Buscar" presentes na pagina. Util pra entender se a
    # heuristica esta achando o elemento errado ou nada.
    inventario = await page.evaluate(
        """() => {
            const inputs = Array.from(document.querySelectorAll('input')).map(el => ({
                id: el.id || '',
                type: el.type || '',
                name: el.name || '',
                placeholder: el.placeholder || '',
                ariaLabel: el.getAttribute('aria-label') || ''
            })).filter(i => i.type === 'text' || i.type === '' || i.type === 'search');

            const cands = document.querySelectorAll(
                'button, input[type="submit"], input[type="button"], input[type="image"], a, span[role="button"]'
            );
            const botoes = [];
            for (const el of cands) {
                const txt = ((el.textContent || el.value || el.title || el.getAttribute('aria-label') || '') + '').trim();
                if (txt.toLowerCase().includes('pesquis') || txt.toLowerCase().includes('buscar')) {
                    botoes.push({ tag: el.tagName, id: el.id || '', texto: txt.substring(0, 40) });
                }
            }
            return {
                n_inputs_texto: inputs.length,
                inputs_amostra: inputs.slice(0, 12),
                botoes_pesquisar: botoes.slice(0, 8),
                titulo: document.title || ''
            };
        }"""
    )
    _log.info("inventario da pagina: %s", inventario)

    # Regra confirmada pelo usuario: o campo de pesquisa SEMPRE exige o numero
    # completo do PAJ (12 digitos no total: 4 ano + 3 unidade + 5 numero).
    # Caracteres especiais (`/` e `-`) sao opcionais. Pesquisar so pelo numero
    # final (ex: '00090' ou '90') NAO funciona — o SIS-DPU exige ano+unidade
    # tambem. Por isso so' tentamos as 2 formas validas:
    #   1) canonico com separadores  — `2024/003-00512`
    #   2) 12 digitos puros          — `202400300512`
    numero_z = numero.zfill(5)
    unidade_z = unidade.zfill(3)
    tentativas = [
        f"{ano}/{unidade_z}-{numero_z}",          # 2024/003-00512 (formato PAJ canonico)
        f"{ano}{unidade_z}{numero_z}",            # 202400300512 (12 digitos puros)
    ]
    vistos: set[str] = set()
    tentativas = [t for t in tentativas if not (t in vistos or vistos.add(t))]

    # Page do detalhamento — pode ser a propria janela atual (se buscarProcesso
    # navegar) ou um POPUP novo (descobrimos no markup que redirecionar() faz
    # window.open). Comeca como None — a primeira tentativa que abrir popup
    # OU navegar a janela atual sera capturada.
    page_detalhe: Page | None = None
    sucesso = False
    erro_ultimo = ""
    debug_acumulado: list[dict] = []
    # Regex que confirma "estou na tela de detalhamento do PAJ". O SIS-DPU
    # tem mais de uma variante visual de cabecalho — aceitamos qualquer pista:
    #  - "AAAA/UUU-NNNNN - PAJ STATUS" (formato compacto, presente em algumas paginas)
    #  - "Numero do PAJ\tAAAA/UUU-NNNNN" (formato tabular, mais comum na tela atual)
    #  - "Detalhamento do Processo" (titulo do breadcrumb — pista robusta)
    re_pag_detalhe = re.compile(
        r"\d{4}/\d{3}-\d+\s*-\s*PAJ\s"
        r"|N[úu]mero\s+do\s+PAJ\s+\d{4}/\d{3}-\d+"
        r"|Detalhamento\s+do\s+Processo"
    )
    contexto = page.context

    for termo in tentativas:
        _log.info("tentando termo='%s'", termo)

        # Escuta um novo "page" (popup) sendo aberto no contexto. Se a
        # buscarProcesso navegar na janela atual, esse expect_page nao captura
        # nada e cai no fallback abaixo.
        popup_capturado: Page | None = None
        try:
            async with contexto.expect_page(timeout=12000) as popup_info:
                res = await page.evaluate(
                    _JS_PESQUISAR_PAJ,
                    {"termo": termo, "ano": ano, "unidade": unidade_z},
                )
                if not isinstance(res, dict) or not res.get("ok"):
                    erro_ultimo = (res or {}).get("erro", "falha ao localizar campo de pesquisa")
                    debug_acumulado.append({"termo": termo, "res": res})
                    _log.warning("  FALHA: %s debug=%s", erro_ultimo, res)
                    if "campo" in erro_ultimo or "botao" in erro_ultimo:
                        # nao adianta tentar outros termos
                        raise StopIteration
            popup_capturado = await popup_info.value
            _log.info("  popup capturado url=%s", popup_capturado.url)
        except StopIteration:
            break
        except PWTimeoutError:
            _log.info("  nenhum popup aberto neste termo (timeout do expect_page)")
        except Exception as e:
            _log.warning("  erro ao esperar popup: %s: %s", type(e).__name__, e)

        # Se capturou popup, estrategia em 2 etapas:
        #
        # ETAPA 1 — tentar usar o popup direto. Espera load + polling do regex.
        # ETAPA 2 (fallback) — pega URL do popup e NAVEGA a janela principal
        # pra ela. Isso funciona porque `redirecionar(url, idProcesso)` no
        # SIS-DPU e' so' `window.open(url + idProcesso)` — sem state JSF, e a
        # URL e' totalmente stateless (so' precisa de cookie de sessao).
        # Como a janela principal ja tem PrimeFaces carregado da caixa, o load
        # completa de forma previsivel.
        # JS que detecta "estou na tela de detalhamento do PAJ" — aceita 3
        # padroes de cabecalho que o SIS-DPU usa em telas diferentes (mesmos
        # padroes do regex Python `re_pag_detalhe` acima). Compartilhado entre
        # ETAPA 1 (popup) e ETAPA 2 (janela principal pos-goto).
        js_detect_header = r"""() => {
            const txt = (document.body && document.body.innerText) || '';
            return /\d{4}\/\d{3}-\d+\s*-\s*PAJ\s/.test(txt)
                || /N[úu]mero\s+do\s+PAJ\s+\d{4}\/\d{3}-\d+/.test(txt)
                || /Detalhamento\s+do\s+Processo/.test(txt);
        }"""

        if popup_capturado is not None:
            popup_url_inicial = popup_capturado.url
            with contextlib.suppress(Exception):
                await popup_capturado.wait_for_load_state(
                    "domcontentloaded", timeout=15000,
                )

            tem_header = False
            # ETAPA 1: tentar ler do popup (10s)
            with contextlib.suppress(PWTimeoutError, Exception):
                await popup_capturado.wait_for_function(
                    js_detect_header,
                    timeout=10000,
                    polling=250,
                )
                tem_header = True

            if tem_header:
                with contextlib.suppress(Exception):
                    await _wait_pf_ajax(popup_capturado, timeout=10000)
                await popup_capturado.wait_for_timeout(500)
                _log.info("  popup OK url=%s", popup_capturado.url)

                # O detalhamento renderizou no POPUP, mas todo o resto do
                # cliente (`listar_arquivos_paj`, `baixar_anexo_por_indice`)
                # opera sobre `_get_page()`, que e' a JANELA PRINCIPAL — ainda
                # na caixa de entrada. Deixar o detalhamento so' no popup fazia
                # o download de anexos falhar em silencio na sincronizacao via
                # busca global: `listar_arquivos_paj` procurava o botao
                # "Arquivos" na caixa, achava so' o menu "Banco de Arquivos -
                # CCRs", e o sync gravava o PAJ com zero anexos.
                #
                # Entao migra pra janela principal, o que e' seguro porque a URL
                # do detalhamento e' stateless (so' depende do cookie de sessao),
                # como a ETAPA 2 abaixo ja' explorava.
                url_detalhe = popup_capturado.url
                migrou = False
                if "detalhamentoProcesso" in url_detalhe:
                    try:
                        await page.goto(
                            url_detalhe, wait_until="domcontentloaded", timeout=20000,
                        )
                        with contextlib.suppress(Exception):
                            await _wait_pf_ajax(page, timeout=15000)
                        await page.wait_for_function(
                            js_detect_header, timeout=15000, polling=250,
                        )
                        migrou = True
                    except Exception as e:
                        _log.warning(
                            "  migracao do popup pra janela principal falhou: %s: %s",
                            type(e).__name__, e,
                        )

                if migrou:
                    with contextlib.suppress(Exception):
                        await popup_capturado.close()
                    _log.info(
                        "  detalhamento na janela principal url=%s", page.url,
                    )
                    page_detalhe = page
                else:
                    # Sem migracao, o PAJ abre e os dados de cabecalho/movimentacao
                    # sao extraidos, mas os anexos NAO poderao ser baixados.
                    # Registrado como WARNING pra nao virar falha silenciosa.
                    _log.warning(
                        "  detalhamento ficou SO' no popup: os anexos deste PAJ "
                        "nao poderao ser listados nem baixados nesta passagem",
                    )
                    page_detalhe = popup_capturado
                sucesso = True
                break

            # ETAPA 2: fallback — navega janela principal pra popup_url
            popup_url_final = popup_capturado.url
            url_alvo = popup_url_final if "detalhamentoProcesso" in popup_url_final else popup_url_inicial
            _log.info(
                "  popup nao renderizou em 10s — fallback: navegar janela principal pra %s",
                url_alvo,
            )

            # Fecha o popup antes de mexer na janela principal
            with contextlib.suppress(Exception):
                await popup_capturado.close()

            if not url_alvo or "detalhamentoProcesso" not in url_alvo:
                erro_ultimo = (
                    f"popup '{termo}' nao renderizou e URL inesperada: {url_alvo!r}"
                )
                debug_acumulado.append({"termo": termo, "popup_url": url_alvo})
                continue

            try:
                await page.goto(url_alvo, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                _log.warning("  fallback goto falhou: %s: %s", type(e).__name__, e)
                erro_ultimo = f"popup '{termo}' + fallback navegacao falhou: {e}"
                debug_acumulado.append({"termo": termo, "popup_url": url_alvo})
                continue

            with contextlib.suppress(Exception):
                await _wait_pf_ajax(page, timeout=15000)
            # Polling do cabecalho na janela principal — 15s
            # Usa o mesmo `js_detect_header` (3 padroes aceitos)
            with contextlib.suppress(PWTimeoutError, Exception):
                await page.wait_for_function(
                    js_detect_header,
                    timeout=15000,
                    polling=250,
                )
                tem_header = True
            await page.wait_for_timeout(500)

            if tem_header:
                _log.info(
                    "  fallback OK — janela principal carregou detalhamento de %s",
                    page.url,
                )
                page_detalhe = page
                sucesso = True
                break

            # Mesmo o fallback falhou — dumpa tudo pra diagnostico
            with contextlib.suppress(Exception):
                pasta_dbg = await _dump_debug_paj(
                    page, paj_texto,
                    f"popup '{termo}' nao renderizou + fallback nao carregou cabecalho",
                    extras={
                        "termo": termo,
                        "popup_url_inicial": popup_url_inicial,
                        "popup_url_final": popup_url_final,
                        "url_alvo": url_alvo,
                        "page_url_pos_goto": page.url,
                    },
                )
                _log.warning("  dump salvo em %s", pasta_dbg)

            erro_ultimo = (
                f"popup '{termo}' nao renderizou e fallback (goto {url_alvo}) "
                f"tambem nao mostrou cabecalho"
            )
            debug_acumulado.append({"termo": termo, "popup_url": url_alvo})
            # Volta pra caixa antes de proxima tentativa
            with contextlib.suppress(Exception):
                await page.goto(
                    f"{SISDPU_URL}/pages/caixaentrada/caixaEntrada.xhtml",
                    wait_until="domcontentloaded",
                )
                await _wait_pf_ajax(page, timeout=10000)
            continue

        # Fallback: a janela atual pode ter navegado para o detalhamento
        # (caso raro, mas defensivo). Da uns segundos pro PrimeFaces AJAX.
        with contextlib.suppress(Exception):
            await _wait_pf_ajax(page, timeout=15000)
        await page.wait_for_timeout(2000)
        body = ""
        with contextlib.suppress(Exception):
            body = await page.inner_text("body")
        tem_header_detalhe = bool(re_pag_detalhe.search(body))
        _log.info(
            "  pos-pesquisa (janela atual) url=%s tem_header_detalhe=%s",
            page.url, tem_header_detalhe,
        )
        if tem_header_detalhe:
            page_detalhe = page
            sucesso = True
            break
        erro_ultimo = (
            f"pesquisa por '{termo}' nao abriu popup nem navegou — "
            f"PAJ pode nao existir nessa unidade/ano"
        )
        debug_acumulado.append({"termo": termo, "url": page.url})

        # Volta pra caixa antes da proxima tentativa
        with contextlib.suppress(Exception):
            await page.goto(
                f"{SISDPU_URL}/pages/caixaentrada/caixaEntrada.xhtml",
                wait_until="domcontentloaded",
            )
            await _wait_pf_ajax(page, timeout=10000)

    if not sucesso or page_detalhe is None:
        msg = erro_ultimo or "PAJ nao encontrado via pesquisa global"
        with contextlib.suppress(Exception):
            pasta = await _dump_debug_paj(
                page, paj_texto, msg,
                extras={"tentativas": debug_acumulado},
            )
            _log.warning("FIM(falha) debug salvo em: %s", pasta)
        return {"erro": msg}

    # A partir daqui a extracao roda em `page_detalhe`, que pode ser a janela
    # atual OU um popup aberto por window.open. Substituimos a referencia
    # `page` localmente para que o resto do codigo continue limpo.
    page = page_detalhe

    # Caso o popup tenha sido capturado, promove ele a "page global" — assim
    # operacoes posteriores que dependem de `_get_page()` (ex: listar_arquivos_paj
    # → baixar anexos) atuam no detalhamento do PAJ, e nao na caixa de entrada
    # antiga. Sem isso, sincronizar um PAJ da watchlist via busca global nao
    # conseguiria baixar anexos. Quando `page_detalhe` ja e' a propria `_page`
    # (busca navegou a janela atual em vez de abrir popup), a atribuicao e' no-op.
    global _page
    _page = page_detalhe

    # Mesmo tratamento do fluxo pela caixa: abre as linhas de "Atendimento de
    # retorno" para o teor certificado entrar no DOM antes da extracao.
    await _expandir_atendimentos_retorno(page_detalhe)

    # Extrai os campos do cabecalho do detalhamento. Estrategia hibrida:
    # (1) DOM-based para label/valor (mais robusto que regex no innerText)
    # (2) regex residual para padroes posicionais (numero CNJ, linha PAJ).
    # (3) filtros para descartar valores que sao claramente cabecalhos de tabela.
    dados = await page.evaluate(
        """
        () => {
            const r = {};
            const body = document.body.innerText;

            // ---------- Helper: encontra valor adjacente a um label ----------
            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim()
                                          .toLowerCase().replace(/[:：]$/, '');

            // Lixo conhecido — cabecalhos de tabelas do SISDPU que aparecem
            // proximos a labels e foram capturados por engano antes.
            const LIXO_TABELA = /^(data de envio|remetente|prazo|descri[çc][ãa]o|tipo|status|data|seq|usu[áa]rio|fases|movimenta[çc][ãa]o|seq\\.?)\\b/i;

            function valorParaLabel(rotulos) {
                const alvos = rotulos.map(norm);
                const candidatos = document.querySelectorAll(
                    'td, th, label, span, dt, dd, li, b, strong, div, p'
                );
                for (const el of candidatos) {
                    const txt = norm(el.textContent || '');
                    if (!alvos.includes(txt)) continue;

                    // 1) Proximo sibling com texto util.
                    let next = el.nextElementSibling;
                    while (next) {
                        const v = (next.textContent || '').trim();
                        if (v) {
                            const linha = v.split('\\n')[0].trim();
                            if (linha && !LIXO_TABELA.test(linha) && linha.length < 250) {
                                return linha;
                            }
                        }
                        next = next.nextElementSibling;
                    }

                    // 2) Pai contendo label e valor juntos no innerText.
                    const pai = el.parentElement;
                    if (pai) {
                        const fullPai = (pai.textContent || '').trim();
                        const idx = fullPai.toLowerCase().indexOf(txt);
                        if (idx >= 0) {
                            const depois = fullPai.substring(idx + (el.textContent || '').length).trim();
                            const linha = depois.split('\\n')[0].trim().replace(/^[:\\-\\s]+/, '');
                            if (linha && !LIXO_TABELA.test(linha) && linha.length < 250) {
                                return linha;
                            }
                        }
                    }
                }
                return '';
            }

            // ---------- Campos do cabecalho (todos os que aparecem na aba Resumo) ----------
            r.assistido = valorParaLabel(['Assistido(s)', 'Assistido', 'Assistidos']);
            r.pretensao = valorParaLabel(['Pretensão', 'Pretensao']);
            r.data_abertura = valorParaLabel([
                'Data de Abertura', 'Dt. Abertura', 'Dt Abertura', 'Dt.Abertura', 'Abertura'
            ]);
            r.oficio = valorParaLabel([
                'Ofício', 'Oficio', 'Ofício Responsável', 'Oficio Responsavel',
                'Ofício responsável', 'Ofício atual'
            ]);
            r.juizo = valorParaLabel([
                'Juízo/Orgão Julgador', 'Juizo/Orgao Julgador',
                'Juízo/Órgão Julgador', 'Juízo', 'Juizo',
                'Órgão Julgador', 'Orgao Julgador'
            ]);
            r.foro_detalhado = valorParaLabel([
                'Foro Detalhado', 'Foro detalhado', 'Foro'
            ]);
            r.decurso = valorParaLabel([
                'Decurso', 'Decurso agendado', 'Decurso Agendado'
            ]);

            // ---------- PAJ + status — duas variantes da tela ----------
            //  a) Formato compacto: "AAAA/UUU-NNNNN - PAJ STATUS"
            //  b) Formato tabular:  "Número do PAJ\tAAAA/UUU-NNNNN"  (nesta tela,
            //     o status vem em outra linha, ex: "Urgente" / "Tutela Coletiva".
            //     Deixamos status vazio se nao houver formato compacto.)
            let pajMatch = body.match(/(\\d{4}\\/\\d{3}-\\d+)\\s*-\\s*PAJ\\s+([^\\n]+)/);
            if (pajMatch) {
                r.paj = pajMatch[1];
                r.status_paj = pajMatch[2].trim();
            } else {
                pajMatch = body.match(/N[úu]mero\\s+do\\s+PAJ[\\s\\t]+(\\d{4}\\/\\d{3}-\\d+)/);
                if (pajMatch) {
                    r.paj = pajMatch[1];
                    r.status_paj = '';
                }
            }

            // ---------- Numero do processo judicial (padrao CNJ) ----------
            const procMatch = body.match(
                /(\\d{7}-\\d{2}\\.\\d{4}\\.\\d\\.\\d{2}\\.\\d{4})/
            );
            if (procMatch) r.processo_judicial = procMatch[1];

            // ---------- Movimentacoes (tabela; mesma logica de antes) ----------
            const movs = [];
            const movRows = document.querySelectorAll('table tbody tr');
            for (const tr of movRows) {
                const cells = tr.querySelectorAll('td');
                if (cells.length >= 5) {
                    const seq = (cells[0]?.textContent || '').trim();
                    const dataHora = (cells[2]?.textContent || '').trim();
                    const movimentacao = (cells[3]?.textContent || '').trim();
                    const fases = (cells[4]?.textContent || '').trim();
                    // innerText preserva a quebra de paragrafo dos <br>/<p> da
                    // celula; textContent colava os paragrafos
                    // ("...curadora especial.A ultima movimentacao...").
                    const textoCompleto = (cells[5]?.innerText
                                           || cells[5]?.textContent || '');
                    const usuario = (cells[6]?.textContent || '').trim();

                    if (seq && /^\\d{1,4}$/.test(seq)
                        && (textoCompleto.trim() || movimentacao)) {
                        // Teor certificado do "Atendimento de retorno" — mesma
                        // logica de movimentacoes_paj (linha de expansao logo
                        // abaixo da linha de dados).
                        let certificado = '';
                        const prox = tr.nextElementSibling;
                        if (prox && (prox.className || '').indexOf('ui-expanded-row-content') !== -1) {
                            certificado = (prox.innerText || '').replace(/\\s+/g, ' ').trim();
                        }
                        const LIMITE_TEOR = 20000;
                        let descFinal = textoCompleto.substring(0, LIMITE_TEOR);
                        if (textoCompleto.length > LIMITE_TEOR) {
                            descFinal += '\\n[TEOR CORTADO em ' + LIMITE_TEOR
                                + ' caracteres - abra a movimentacao no SISDPU]';
                        }
                        if (certificado) {
                            descFinal += '\\n[ATENDIMENTO DE RETORNO - certificado]: ' + certificado;
                        }
                        movs.push({
                            seq: seq,
                            data: dataHora,
                            movimentacao: movimentacao,
                            fases: fases,
                            descricao: descFinal,
                            certificado: certificado,
                            links_decisao: [],
                            usuario: usuario
                        });
                    }
                }
            }
            if (movs.length > 0) r.movimentacoes = movs.slice(0, 50);

            // ---------- Filtro final: descarta qualquer campo que tenha vazado lixo ----------
            for (const k of ['assistido', 'pretensao', 'oficio', 'juizo', 'foro_detalhado', 'decurso', 'data_abertura']) {
                if (r[k] && LIXO_TABELA.test(r[k])) {
                    r[k] = '';
                }
            }

            return r;
        }
        """
    )

    if not dados:
        dados = {}

    n_movs = len(dados.get("movimentacoes", []) or [])
    _log.info(
        "extracao: assistido=%s paj=%s movs=%d",
        bool(dados.get("assistido")), dados.get("paj", "?"), n_movs,
    )

    # Validacao rigorosa: precisa do `paj` extraido pelo regex
    # "AAAA/UUU-NNNNN - PAJ STATUS", que so' aparece na tela de detalhamento.
    # Sem ele, ainda estamos na caixa ou em pagina inesperada.
    if not dados.get("paj"):
        msg = (
            "extracao falhou — cabecalho do PAJ nao encontrado na pagina "
            "(provavelmente nao estamos na tela de detalhamento)"
        )
        with contextlib.suppress(Exception):
            pasta = await _dump_debug_paj(
                page, paj_texto, msg,
                extras={"dados_parciais": {k: v for k, v in dados.items() if k != "movimentacoes"}},
            )
            _log.warning("FIM(sem-paj) debug salvo em: %s", pasta)
        return {"erro": msg}

    dados["paj_numero"] = numero
    dados["paj_ano"] = ano
    dados["paj_unidade"] = unidade
    dados["url"] = page.url

    # Dump tambem em caso de sucesso durante esta fase de afinacao — ajuda
    # diagnosticar campos vazios sem precisar retentar. Pode ser desligado
    # depois que a extracao estiver estavel.
    with contextlib.suppress(Exception):
        pasta = await _dump_debug_paj(
            page, paj_texto, "sucesso (dump pra afinacao)",
            extras={
                "campos_extraidos": {
                    k: v for k, v in dados.items()
                    if k not in ("movimentacoes", "sisdpu_raw")
                },
            },
        )
        _log.info("dump de sucesso salvo em: %s", pasta)
    _log.info("FIM(ok) %s", paj_texto)
    return dados


async def baixar_arquivo(url: str, destino) -> bool:
    """Baixa arquivo reaproveitando a sessao autenticada (cookies) do SISDPU.

    Retorna True se o arquivo foi gravado com tamanho > 0.
    """
    try:
        import httpx
    except ImportError:
        return False

    page = await _get_page()
    context = page.context
    cookies = await context.cookies()
    cookie_jar = {c["name"]: c["value"] for c in cookies}

    try:
        async with httpx.AsyncClient(
            cookies=cookie_jar,
            timeout=60,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/127.0 Safari/537.36"
                ),
                "Accept": "application/pdf,*/*;q=0.8",
            },
        ) as c:
            resp = await c.get(url)
            resp.raise_for_status()
            if not resp.content:
                return False
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(resp.content)
            return destino.stat().st_size > 0
    except Exception:
        return False


async def listar_arquivos_paj(debug: bool = False) -> dict:
    """Clica no botao "Arquivos" do PAJ atualmente aberto e extrai a lista.

    PRE-CONDICAO: a page ja deve estar no detalhamento do PAJ (chamar
    `movimentacoes_paj(...)` antes). Nao navega — so interage com a pagina atual.

    Retorna dict:
        {
            "ok": bool,
            "itens": [{tipo, descricao, arquivo, row_index, todas_celulas}, ...],
            "diag": {...}   # sempre presente; use pra debug quando itens == []
        }
    `diag` inclui: candidatos_botao_arquivos, clicou, dialogs_visiveis,
    dialog_escolhido, total_linhas, linhas_filtradas_por_texto, html_snippet.
    """
    page = await _get_page()

    # 1) Inventariar candidatos ao botao "Arquivos" ANTES de clicar
    diag: dict = {}
    diag["candidatos_botao_arquivos"] = await page.evaluate(
        """
        () => {
            const out = [];
            const els = Array.from(document.querySelectorAll('a, button, span[role="button"], .ui-button'));
            for (const el of els) {
                const txt = (el.textContent || '').trim();
                if (txt && /arquivo/i.test(txt) && txt.length < 40) {
                    out.push({
                        tag: el.tagName,
                        texto: txt,
                        id: el.id || '',
                        classes: el.className || '',
                        onclick_has: !!el.getAttribute('onclick'),
                    });
                }
            }
            return out;
        }
        """
    )

    # 2) Clica no link "Arquivos" — agora mais tolerante
    clicked = await page.evaluate(
        """
        () => {
            const els = Array.from(document.querySelectorAll('a, button, span[role="button"], .ui-button'));
            // Preferencia: match EXATO por "Arquivos" depois de trim
            for (const el of els) {
                const txt = (el.textContent || '').trim();
                if (txt === 'Arquivos' || txt === 'Arquivo(s)') {
                    el.click();
                    return 'exato';
                }
            }
            // Fallback: contem "Arquivos" (mas nao "Arquivo anexo" de movimentacao)
            for (const el of els) {
                const txt = (el.textContent || '').trim();
                if (/^Arquivos?$/i.test(txt) || /^Arquivos\\s*\\(\\d+\\)$/.test(txt)) {
                    el.click();
                    return 'regex';
                }
            }
            // Fallback extremo: qualquer elemento com "Arquivo" curto
            for (const el of els) {
                const txt = (el.textContent || '').trim();
                if (/arquivo/i.test(txt) && txt.length < 15) {
                    el.click();
                    return 'fuzzy:' + txt;
                }
            }
            return '';
        }
        """
    )
    diag["clicou"] = clicked or "NADA"
    if not clicked:
        return {"ok": False, "itens": [], "diag": diag}

    # Aguarda AJAX + eventual navegacao (o link "Arquivos" navega para outra tela).
    # Tenta networkidle primeiro; se falhar, cai pra wait_pf_ajax + sleep.
    #
    # NAO trocar por espera condicional generica aqui. Tentei esperar por
    # "tabela visivel com botao Visualizar" e a condicao casava com uma tabela
    # ANTERIOR ao dialogo de arquivos: a lista vinha truncada (um PAJ com 96
    # anexos passou a reportar 4). Anexo faltando = documento invisivel para a
    # analise, entao aqui a espera generosa fica de proposito.
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        await _wait_pf_ajax(page, timeout=15000)
    await page.wait_for_timeout(1500)

    # 3) Inventariar dialogs REALMENTE visiveis (filtra aria-hidden=true)
    diag["dialogs_visiveis"] = await page.evaluate(
        """
        () => {
            const dialogs = document.querySelectorAll('.ui-dialog');
            return Array.from(dialogs)
                .filter(d => {
                    if (d.getAttribute('aria-hidden') === 'true') return false;
                    if (d.classList.contains('ui-overlay-hidden')) return false;
                    const st = window.getComputedStyle(d);
                    if (st.display === 'none' || st.visibility === 'hidden') return false;
                    return true;
                })
                .map(d => ({
                    id: d.id || '',
                    titulo: (d.querySelector('.ui-dialog-title')?.textContent || '').trim(),
                    linhas_tabela: d.querySelectorAll('table tbody tr').length,
                }));
        }
        """
    )

    # Registra URL pra saber se navegou
    with contextlib.suppress(Exception):
        diag["url_apos_click"] = page.url

    # 4) Extrai linhas — a pagina de Arquivos do SISDPU tem MULTIPLAS tabelas,
    # uma por categoria ("Juntada de documento", "Concluso ao defensor",
    # "Oficio/Carta/Comunicacao expedida", etc.). Iteramos TODAS as tabelas
    # visiveis com botoes "Visualizar" em ordem do DOM e concatenamos as linhas
    # com indice global. A funcao baixar_anexo_por_indice usa a MESMA estrategia
    # de flatten para que `row_index` seja consistente.
    extrato = await page.evaluate(
        """
        () => {
            const diag = {estrategia: '', total_linhas: 0, linhas_filtradas: 0,
                          tabelas_analisadas: 0, tabelas_com_visualizar: 0,
                          categorias: []};

            const isVisivel = (el) => {
                let cur = el;
                while (cur) {
                    if (cur.nodeType === 1) {
                        if (cur.getAttribute && cur.getAttribute('aria-hidden') === 'true') return false;
                        if (cur.classList && (
                            cur.classList.contains('ui-overlay-hidden') ||
                            cur.classList.contains('ui-hidden-container')
                        )) {
                            if (cur.getAttribute('aria-hidden') === 'true') return false;
                        }
                    }
                    cur = cur.parentElement;
                }
                try {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) return false;
                } catch (e) {}
                return true;
            };

            // Tenta extrair o rotulo da categoria de uma tabela: o texto curto
            // mais proximo (header/legend/div) que aparece imediatamente antes.
            const detectaCategoria = (tbl) => {
                let prev = tbl.previousElementSibling;
                let tentativas = 0;
                while (prev && tentativas < 6) {
                    const t = (prev.textContent || '').trim();
                    if (t && t.length < 100 && t.length > 2 && !/^(Seq\\.|Nenhum registro)/i.test(t)) {
                        return t.split('\\n')[0].trim().slice(0, 80);
                    }
                    prev = prev.previousElementSibling;
                    tentativas++;
                }
                // Fallback: legend de fieldset ancestral
                let p = tbl.parentElement;
                while (p) {
                    const lg = p.querySelector(':scope > legend, :scope > .ui-fieldset-legend');
                    if (lg) {
                        const t = (lg.textContent || '').trim();
                        if (t) return t.slice(0, 80);
                    }
                    p = p.parentElement;
                }
                return '';
            };

            const tables = document.querySelectorAll('table');
            diag.tabelas_analisadas = tables.length;

            // Coleta todas as tabelas uteis (visiveis, com >= 1 linha "Visualizar")
            const uteis = [];
            for (const tbl of tables) {
                const rows = tbl.querySelectorAll('tbody tr');
                if (rows.length === 0) continue;
                let comVis = 0;
                for (const r of rows) {
                    const alvos = r.querySelectorAll('a, button, span[role="button"]');
                    for (const a of alvos) {
                        if (/visualizar/i.test((a.textContent || '').trim())) { comVis++; break; }
                    }
                }
                if (comVis === 0) continue;
                if (!isVisivel(tbl)) continue;
                uteis.push(tbl);
            }
            diag.tabelas_com_visualizar = uteis.length;

            if (uteis.length === 0) {
                // Fallback: tabelas visiveis cujos headers mencionem "arquivo"
                for (const tbl of tables) {
                    const ths = Array.from(tbl.querySelectorAll('th')).map(th => (th.textContent || '').toLowerCase());
                    if (!/arquivo|documento/.test(ths.join('|'))) continue;
                    if (!tbl.querySelector('tbody tr')) continue;
                    if (!isVisivel(tbl)) continue;
                    uteis.push(tbl);
                }
                if (uteis.length > 0) diag.estrategia = 'tabela_por_header';
            } else {
                diag.estrategia = uteis.length > 1
                    ? `multi_tabela_visualizar (${uteis.length})`
                    : 'tabela_com_visualizar';
            }

            if (uteis.length === 0) {
                diag.erro = 'nenhuma_tabela_util_encontrada';
                return {resultado: [], diag};
            }

            // Flatten: percorre todas as tabelas em ordem do DOM e concatena as
            // linhas com indice global crescente. A categoria de cada tabela e'
            // anexada a cada linha — util pra naming/diagnostico.
            const resultado = [];
            let idx = 0;
            const snippets = [];
            for (const tbl of uteis) {
                const categoria = detectaCategoria(tbl);
                diag.categorias.push({categoria: categoria, linhas: 0});
                const catIdx = diag.categorias.length - 1;
                const rows = tbl.querySelectorAll('tbody tr');
                diag.total_linhas += rows.length;
                for (const tr of rows) {
                    if (tr.classList.contains('ui-widget-header')) continue;
                    const cells = tr.querySelectorAll('td');
                    if (cells.length === 0) continue;
                    const textos = Array.from(cells).map(c => (c.textContent || '').trim());
                    const preenchidas = textos.filter(t => t.length > 0).length;
                    if (preenchidas < 1) continue;
                    const alvos = tr.querySelectorAll('a, button, span[role="button"]');
                    let temVis = false;
                    for (const a of alvos) {
                        if (/visualizar/i.test((a.textContent || '').trim())) { temVis = true; break; }
                    }
                    if (!temVis) continue;
                    resultado.push({
                        row_index: idx++,
                        tipo: textos[0] || '',
                        descricao: textos[1] || '',
                        arquivo: textos[2] || '',
                        categoria: categoria,
                        todas_celulas: textos,
                    });
                    diag.categorias[catIdx].linhas++;
                }
                try { snippets.push((tbl.outerHTML || '').slice(0, 800)); } catch (e) {}
            }
            diag.linhas_filtradas = resultado.length;
            diag.html_snippet = snippets.join('\\n---\\n').slice(0, 2000);
            return {resultado, diag};
        }
        """
    )

    diag.update(extrato.get("diag", {}))
    itens = extrato.get("resultado", []) or []
    return {"ok": True, "itens": itens, "diag": diag}


async def baixar_anexo_por_indice(row_index: int, destino):
    """Clica em "Visualizar" da linha `row_index` e salva o arquivo baixado.

    Com o preview de PDF desabilitado no Chromium, todos os tipos disparam
    evento `download`. Usa expect_download com timeout generoso.

    `destino` pode ser:
      - Path com extensao: salva exatamente ali.
      - Path SEM extensao (stem): a extensao e' detectada do
        `download.suggested_filename` (Content-Disposition do SISDPU) e
        apensa ao stem. E' a forma recomendada pra nao forcar `.bin` quando
        o scraper nao tinha a extensao do arquivo na tela.

    Retorna Path do arquivo salvo (com extensao final) ou None se falhou.
    """
    from pathlib import Path as _Path
    destino = _Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)

    page = await _get_page()

    # Identifica o botao "Visualizar" da linha `idx` usando a MESMA estrategia
    # de flatten de listar_arquivos_paj: itera TODAS as tabelas visiveis com
    # linhas "Visualizar" em ordem do DOM e seleciona a `idx`-esima linha
    # (indice global). Para PAJs com multiplas categorias na pagina de Arquivos
    # (ex: "Concluso ao defensor", "Juntada de documento", "Despacho", etc.),
    # cada tabela contribui suas linhas na ordem em que aparece no DOM.
    found = await page.evaluate(
        """
        (idx) => {
            const isVisivel = (el) => {
                let cur = el;
                while (cur) {
                    if (cur.nodeType === 1) {
                        if (cur.getAttribute && cur.getAttribute('aria-hidden') === 'true') return false;
                    }
                    cur = cur.parentElement;
                }
                try {
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) return false;
                } catch (e) {}
                return true;
            };

            const tables = document.querySelectorAll('table');
            // Coleta tabelas uteis em ordem do DOM (mesma logica de listar_arquivos_paj)
            const uteis = [];
            for (const tbl of tables) {
                const rows = tbl.querySelectorAll('tbody tr');
                if (rows.length === 0) continue;
                let comVis = 0;
                for (const r of rows) {
                    const alvos = r.querySelectorAll('a, button, span[role="button"]');
                    for (const a of alvos) {
                        if (/visualizar/i.test((a.textContent || '').trim())) { comVis++; break; }
                    }
                }
                if (comVis === 0) continue;
                if (!isVisivel(tbl)) continue;
                uteis.push(tbl);
            }
            if (uteis.length === 0) return false;

            // Flatten: concatena linhas de todas as tabelas em ordem
            const linhas = [];
            for (const tbl of uteis) {
                const rows = Array.from(tbl.querySelectorAll('tbody tr'))
                    .filter(tr => {
                        if (tr.classList.contains('ui-widget-header')) return false;
                        if (tr.querySelectorAll('td').length === 0) return false;
                        const alvos = tr.querySelectorAll('a, button, span[role="button"]');
                        for (const a of alvos) {
                            if (/visualizar/i.test((a.textContent || '').trim())) return true;
                        }
                        return false;
                    });
                for (const r of rows) linhas.push(r);
            }
            if (idx >= linhas.length) return false;
            const row = linhas[idx];
            const alvos = row.querySelectorAll('a, button, span[role="button"]');
            for (const el of alvos) {
                if (/visualizar/i.test((el.textContent || '').trim())) {
                    el.setAttribute('data-dpu-pick', '1');
                    return true;
                }
            }
            return false;
        }
        """,
        row_index,
    )
    if not found:
        return None

    def _limpar_marker():
        try:
            return page.evaluate(
                "() => document.querySelectorAll('[data-dpu-pick]')"
                ".forEach(el => el.removeAttribute('data-dpu-pick'))"
            )
        except Exception:
            pass

    def _destino_com_ext(nome_sugerido: str):
        """Resolve a extensao final a partir do nome sugerido pelo SISDPU."""
        ext = _Path(nome_sugerido).suffix.lower() if nome_sugerido else ""
        if not ext:
            ext = ".bin"
        # Se o destino passado NAO tem extensao (ou tem .bin como placeholder),
        # usa a extensao detectada. Caso contrario respeita o que veio.
        if destino.suffix == "" or destino.suffix.lower() == ".bin":
            return destino.with_suffix(ext)
        return destino

    # Captura as URLs REST de download que passarem pela rede. Necessario para
    # o plano B: em navegadores com visualizador de PDF interno (Chrome/Edge
    # instalados), clicar em "Visualizar" ABRE o PDF em vez de baixa-lo, e o
    # evento `download` nunca dispara. Como a URL do SISDPU e' um GET simples
    # (.../rest/download/<tipo>/<id>/<nome>), da' pra rebuscar os bytes pela
    # propria sessao do navegador (mesmos cookies) via APIRequestContext.
    # O listener fica no CONTEXTO, nao na page: o SISDPU pode abrir o arquivo
    # numa aba nova, e nesse caso a resposta pertence a outra page.
    urls_rest: list[str] = []
    contexto = page.context

    def _capturar_url(resp) -> None:
        if "/rest/download/" in resp.url:
            urls_rest.append(resp.url)

    baixados: list = []

    def _capturar_download(dl) -> None:
        baixados.append(dl)

    page.on("download", _capturar_download)

    contexto.on("response", _capturar_url)
    paginas_antes = set(contexto.pages)
    try:
        await page.click('[data-dpu-pick="1"]')

        # Corre os dois caminhos em paralelo e usa o que chegar primeiro, em
        # vez de esperar o timeout inteiro do evento `download` (que nunca vem
        # quando o navegador exibe o PDF no visualizador interno).
        LIMITE_S, PASSO_S = 60, 0.25
        for _ in range(int(LIMITE_S / PASSO_S)):
            if baixados or urls_rest:
                break
            await asyncio.sleep(PASSO_S)

        # Se so' a URL apareceu, ainda da' uma folga curta para um eventual
        # evento `download` — ele e' o caminho preferencial por trazer o nome
        # do arquivo no Content-Disposition.
        if urls_rest and not baixados:
            for _ in range(8):
                await asyncio.sleep(PASSO_S)
                if baixados:
                    break

        if baixados:
            download = baixados[-1]
            destino_final = _destino_com_ext((download.suggested_filename or "").strip())
            await download.save_as(str(destino_final))
        elif urls_rest:
            url = urls_rest[-1]
            resp = await page.request.get(url)
            if not resp.ok:
                raise RuntimeError(f"refetch HTTP {resp.status}")
            corpo = await resp.body()
            if not corpo:
                raise RuntimeError("refetch devolveu corpo vazio")
            destino_final = _destino_com_ext(unquote(url.rsplit("/", 1)[-1].split("?")[0]))
            destino_final.write_bytes(corpo)
            _log.info(
                "anexo obtido via refetch da sessao (navegador exibiu o arquivo "
                "em vez de baixar): %s", destino_final.name,
            )
        else:
            raise PWTimeoutError("nem evento download nem URL REST em 60s")
    except Exception:
        await _limpar_marker()
        return None
    finally:
        with contextlib.suppress(Exception):
            contexto.remove_listener("response", _capturar_url)
        with contextlib.suppress(Exception):
            page.remove_listener("download", _capturar_download)
        # Fecha abas que o visualizador tenha aberto, senao elas se acumulam
        # ao longo da sincronizacao.
        for pg in contexto.pages:
            if pg not in paginas_antes and pg is not page:
                with contextlib.suppress(Exception):
                    await pg.close()

    await _limpar_marker()

    if destino_final.exists() and destino_final.stat().st_size > 0:
        return destino_final
    return None


async def fechar_dialogo_arquivos() -> None:
    """Fecha o dialogo 'Arquivos' se estiver aberto (para nao interferir em outro PAJ)."""
    page = await _get_page()
    try:
        await page.evaluate(
            """
            () => {
                const dialogs = document.querySelectorAll('.ui-dialog:not(.ui-overlay-hidden)');
                for (const d of dialogs) {
                    const titulo = d.querySelector('.ui-dialog-title');
                    if (titulo && /arquivo/i.test(titulo.textContent || '')) {
                        const btn = d.querySelector('.ui-dialog-titlebar-close');
                        if (btn) btn.click();
                    }
                }
            }
            """
        )
        await page.wait_for_timeout(500)
    except Exception:
        pass


async def fechar() -> None:
    """Fecha o navegador headless."""
    global _playwright, _browser, _page
    if _browser:
        with contextlib.suppress(Exception):
            await _browser.close()
        _browser = None
        _page = None
    if _playwright:
        with contextlib.suppress(Exception):
            await _playwright.stop()
        _playwright = None


if __name__ == "__main__":
    import asyncio
    import json

    async def _smoke() -> None:
        # Carrega .env do projeto para expor SISDPU_USERNAME/PASSWORD
        from pathlib import Path

        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")

        try:
            data = await caixa_de_entrada()
            itens = data.get("itens_tabela", [])[:5]
            print(json.dumps(itens, ensure_ascii=False, indent=2))
            print(f"(+{len(data.get('itens_tabela', [])) - len(itens)} itens)")
        finally:
            await fechar()

    asyncio.run(_smoke())
