"""Acesso ao PJe (TRF3) via navegador — consulta processual SOMENTE LEITURA.

Caminho alternativo ao MNI/SOAP. Usa Playwright (mesma tecnologia do
`sisdpu_client.py`) com navegador VISIVEL + sessao persistente:

    * LOGIN MANUAL: o navegador abre visivel; VOCE faz login (senha ou
      certificado) UMA vez. O codigo NUNCA digita nem armazena sua senha.
    * SESSAO PERSISTENTE: cookies ficam em `config.PJE_WEB_USER_DATA_DIR`
      (local, fora do git). Nas proximas vezes o login ja estara valido.
    * O navegador precisa ser VISIVEL: o PJe/TRF3 fica atras do Akamai, que
      bloqueia clientes automatizados/headless. Janela real passa.

Fluxo automatizado (objetivo):
    login manual -> buscar numero (vindo do SIS) -> abrir autos -> baixar
    pecas -> OCR -> Markdown pronto para analise.

CALIBRACAO: como o DOM real do TRF3 nao pode ser inspecionado no ambiente de
desenvolvimento (Akamai bloqueia acesso automatizado de fora da sessao real do
usuario), cada etapa salva HTML + screenshot em `logs/pje_debug/`. Se um seletor
falhar, esses dumps permitem ajustar os cliques com precisao. Enquanto a
automacao nao estiver calibrada, ha o modo ASSISTIDO (`capturar_pecas`) que
captura o que voce baixar manualmente.

Escopo: navegar, abrir processo e baixar pecas (leitura). Nao peticiona.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import re
from pathlib import Path

import config

logger = logging.getLogger("pje.web")

# Sessao reutilizavel (modulo-level): abre o navegador e autentica UMA vez;
# consultas seguintes reaproveitam o mesmo contexto, sem nova assinatura. Para
# o PJe com certificado, manter o navegador aberto evita reautenticar a cada
# consulta. Serializar o uso (um asyncio.Lock) fica a cargo do chamador (SIS).
_sessao_pw = None
_sessao_ctx = None

# Flags do Chromium: forca download de PDF (em vez de preview) e desliga HTTP/2
# (alguns middleboxes/Akamai quebram h2 em automacao).
_CHROMIUM_ARGS = ["--disable-features=PDFViewerUpdate,PdfUnseasoned", "--disable-http2"]

_DEBUG_DIR = Path(__file__).resolve().parents[1] / "logs" / "pje_debug"

# Espera o PrimeFaces terminar AJAX pendente (PJe e' JSF/PrimeFaces, como o SIS).
_WAIT_PF_AJAX = """
() => new Promise((resolve) => {
    const check = () => {
        if (typeof PrimeFaces === 'undefined' || !PrimeFaces.ajax
            || !PrimeFaces.ajax.Queue || PrimeFaces.ajax.Queue.isEmpty()) {
            resolve(true);
        } else { setTimeout(check, 100); }
    };
    check();
})
"""

# Seletores CALIBRADOS contra o PJe TRF3 1o grau (Consulta Processual, form fPP).
# O numero do processo e' DIVIDIDO em campos separados (RichFaces).
_SEL_NUM_SEQUENCIAL = '[id="fPP:numeroProcesso:numeroSequencial"]'
_SEL_NUM_DV = '[id="fPP:numeroProcesso:numeroDigitoVerificador"]'
_SEL_NUM_ANO = '[id="fPP:numeroProcesso:Ano"]'
_SEL_NUM_ORGAO = '[id="fPP:numeroProcesso:NumeroOrgaoJustica"]'
_SEL_BOTAO_PESQUISAR = [
    '[id="fPP:searchProcessos"]',
    'input[type="button"][value="Pesquisar"]',
    'button:has-text("Pesquisar")',
]
# Abrir os autos a partir do resultado — candidatos (a calibrar com dump 02).
_SEL_ABRIR_PROCESSO = [
    'a[title*="Ver Detalhes"]',
    'a[title*="Detalhes"]',
    'a[title*="Visualizar"]',
    'a[id*="link"]',
    'tbody a[onclick]',
]
# Baixar autos/pecas — candidatos (a calibrar com dump 03).
_SEL_BAIXAR_AUTOS = [
    'a[title*="Baixar"]',
    'button:has-text("Baixar autos")',
    'a:has-text("Download de autos")',
    'a[title*="Download"]',
]


# --- Infra -------------------------------------------------------------------


async def _abrir_contexto():
    """Abre contexto persistente (sessao salva) e VISIVEL. Retorna (pw, context).

    O TRF3 fica atras do Akamai, que bloqueia o Chromium "de automacao" (pagina
    em branco). Para passar, dirigimos o CHROME/EDGE REAL instalado na maquina
    (canal 'chrome'/'msedge') — impressao digital legitima — e removemos as
    flags de automacao (`--enable-automation`, webdriver). Usa um perfil
    DEDICADO (PJE_WEB_USER_DATA_DIR), sem tocar no seu perfil pessoal do Chrome.
    """
    from playwright.async_api import async_playwright

    user_data_dir = config.PJE_WEB_USER_DATA_DIR
    user_data_dir.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()

    # Args minimos: forca download de PDF e esconde a marca de automacao que o
    # Akamai/bot-managers checam (navigator.webdriver).
    args = [
        "--disable-features=PDFViewerUpdate,PdfUnseasoned",
        "--disable-blink-features=AutomationControlled",
        # Forca HTTP/1.1: o TRF3/Akamai retorna ERR_HTTP2_PROTOCOL_ERROR para
        # o Chrome dirigido por automacao quando usa HTTP/2.
        "--disable-http2",
    ]
    comum = dict(
        user_data_dir=str(user_data_dir),
        headless=False,
        accept_downloads=True,
        ignore_https_errors=True,
        viewport={"width": 1366, "height": 900},
        args=args,
        # Remove o "--enable-automation" (barra amarela + webdriver=true).
        ignore_default_args=["--enable-automation"],
    )

    # Tenta o Chrome real, depois o Edge, e por fim o Chromium empacotado.
    ultimo_erro: Exception | None = None
    for canal in ("chrome", "msedge", None):
        try:
            ctx = await pw.chromium.launch_persistent_context(
                channel=canal, **comum
            ) if canal else await pw.chromium.launch_persistent_context(**comum)
            logger.info("navegador iniciado (canal=%s)", canal or "chromium")
            print(f"  [navegador] usando: {canal or 'chromium empacotado'}")
            # Reforco anti-deteccao: garante navigator.webdriver = undefined em
            # toda pagina nova, antes de qualquer script do site rodar.
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            return pw, ctx
        except Exception as e:
            ultimo_erro = e
            logger.warning("canal %s indisponivel: %s", canal, e)
    await pw.stop()
    raise RuntimeError(f"Nao consegui iniciar o navegador: {ultimo_erro}")


async def _wait_pf_ajax(page, timeout: int = 10000) -> None:
    try:
        await page.evaluate(_WAIT_PF_AJAX, timeout=timeout)
    except Exception:
        await page.wait_for_timeout(800)


# O TRF3 (atras de Akamai) as vezes demora/oscila no carregamento. Navegamos
# com wait_until="commit" (resolve assim que a navegacao inicia) e timeout
# generoso, com uma nova tentativa — evita falhas por lentidao pontual.
_NAV_TIMEOUT_MS = 90000


async def _goto_tolerante(page, url: str, *, timeout: int = _NAV_TIMEOUT_MS) -> None:
    """Navega sem FALHAR se o load demorar. ERR_ABORTED/HTTP2 sao transitorios
    (navegacao superada/oscilacao) — repete algumas vezes rapidamente. Quem
    decide se 'carregou' e' o chamador (esperando um seletor especifico)."""
    for i in range(3):
        try:
            await page.goto(url, wait_until="commit", timeout=timeout)
            await page.wait_for_timeout(2000)
            return
        except Exception as e:
            msg = str(e)
            if any(x in msg for x in ("ERR_ABORTED", "ERR_HTTP2", "ERR_NETWORK_CHANGED")):
                logger.warning("goto transitorio (%d/3): %s", i + 1, msg[:80])
                await page.wait_for_timeout(1500)
                continue
            logger.warning("goto nao completou (%s) — seguindo mesmo assim", msg[:120])
            await page.wait_for_timeout(1500)
            return
    await page.wait_for_timeout(1500)


async def _dump_dom(page, tag: str) -> Path:
    """Salva HTML + screenshot + catalogo de inputs/botoes para calibracao.

    Retorna o caminho do .html. Estes arquivos sao LOCAIS (logs/pje_debug) e
    servem para ajustar seletores — leia-os para descobrir os IDs reais.
    """
    _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = _DEBUG_DIR / f"{tag}_{ts}"
    try:
        html = await page.content()
        base.with_suffix(".html").write_text(html, encoding="utf-8")
    except Exception as e:
        logger.warning("dump html falhou: %s", e)
    try:
        await page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
    except Exception as e:
        logger.warning("dump screenshot falhou: %s", e)
    try:
        cat = await page.eval_on_selector_all(
            "input, button, a[onclick], a[title]",
            "els => els.map(e=>({tag:e.tagName,id:e.id,name:e.name,type:e.type,"
            "title:e.title,txt:(e.innerText||e.value||'').trim().slice(0,40)}))"
            ".filter(x=>x.id||x.name||x.title||x.txt).slice(0,120)",
        )
        import json

        base.with_suffix(".elementos.json").write_text(
            json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("dump catalogo falhou: %s", e)
    logger.info("DOM dump: %s.*", base)
    print(f"  [dump] DOM salvo para calibracao: {base}.html / .png / .elementos.json")
    return base.with_suffix(".html")


async def _tentar_clicar(page, seletores: list[str], descricao: str) -> bool:
    """Tenta uma lista de seletores; clica no primeiro visivel. Retorna sucesso."""
    for sel in seletores:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.click()
                logger.info("clicou (%s) via %s", descricao, sel)
                return True
        except Exception:
            continue
    return False


async def _tentar_preencher(page, seletores: list[str], valor: str) -> bool:
    for sel in seletores:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                await loc.fill(valor)
                return True
        except Exception:
            continue
    return False


# --- Login -------------------------------------------------------------------


async def garantir_login(context, *, timeout_seg: int | None = None) -> None:
    """Abre o login e AGUARDA voce concluir a autenticacao manualmente.

    Detecta sucesso quando a URL volta ao host autenticado fora das telas de
    login/SSO. Se a sessao ja estiver valida, retorna quase imediatamente.
    """
    timeout_seg = timeout_seg or config.PJE_WEB_LOGIN_TIMEOUT_SEG
    page = context.pages[0] if context.pages else await context.new_page()

    print("=" * 64)
    print("  Abrindo a Consulta Processual do PJe/TRF3.")
    print("  - Se aparecer a tela de LOGIN, faca login (senha ou certificado).")
    print("    Sua senha NAO e' lida nem salva.")
    print("  - O TRF3 as vezes demora; se a aba ficar carregando, deixe aberta —")
    print("    eu reabro sozinho. Voce tambem pode navegar ate a Consulta.")
    print(f"  Aguardando o formulario de consulta aparecer (ate {timeout_seg}s)...")
    print("=" * 64)

    # Primeira tentativa de navegacao (tolerante: nao falha se o load demorar).
    await _goto_tolerante(page, config.PJE_WEB_CONSULTA_URL)

    loop = asyncio.get_event_loop()
    inicio = loop.time()
    ultima_navegacao = inicio
    while (loop.time() - inicio) < timeout_seg:
        # Sucesso = o campo do numero do processo esta presente na tela.
        try:
            campo = page.locator(_SEL_NUM_SEQUENCIAL).first
            if await campo.count() and await campo.is_visible():
                print("  [ok] Formulario de consulta disponivel.")
                return
        except Exception:
            pass

        url = (page.url or "").lower()
        em_login = any(x in url for x in ("login", "sso", "openid-connect"))
        # Se nao estamos na tela de login e o form ainda nao apareceu (load lento
        # ou pagina em branco), re-tenta navegar a cada ~25s.
        if not em_login and (loop.time() - ultima_navegacao) > 12:
            await _goto_tolerante(page, config.PJE_WEB_CONSULTA_URL)
            ultima_navegacao = loop.time()

        await asyncio.sleep(3)

    raise TimeoutError(
        "Formulario de consulta nao apareceu no tempo limite. O TRF3 pode estar "
        "fora do ar/lento agora — tente novamente. (Ajuste PJE_WEB_LOGIN_TIMEOUT_SEG "
        "para esperar mais.)"
    )


# --- Automacao: buscar, abrir, baixar ---------------------------------------


def _partes_cnj(numero: str) -> dict[str, str]:
    """Quebra o numero CNJ (20 digitos) nos campos do PJe.

    NNNNNNN-DD.AAAA.J.TR.OOOO -> seq, dv, ano, ramo, tribunal, orgao.
    """
    d = re.sub(r"\D", "", numero or "")
    if len(d) != 20:
        raise ValueError(f"Numero invalido para quebra CNJ: {numero!r}")
    return {
        "seq": d[0:7],
        "dv": d[7:9],
        "ano": d[9:13],
        "ramo": d[13:14],
        "tribunal": d[14:16],
        "orgao": d[16:20],
    }


async def _preencher_numero(page, numero: str) -> bool:
    """Preenche os campos divididos do numero do processo. Retorna sucesso."""
    p = _partes_cnj(numero)
    pares = [
        (_SEL_NUM_SEQUENCIAL, p["seq"]),
        (_SEL_NUM_DV, p["dv"]),
        (_SEL_NUM_ANO, p["ano"]),
        (_SEL_NUM_ORGAO, p["orgao"]),
    ]
    ok = False
    for sel, val in pares:
        try:
            loc = page.locator(sel).first
            if await loc.count():
                await loc.fill(val)
                ok = True
        except Exception as e:
            logger.warning("falha ao preencher %s: %s", sel, e)
    return ok


async def _fechar_modais(page) -> None:
    """Tenta dispensar modais que o PJe abre no load (ex: 'PJe Office indisponivel')."""
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def buscar_e_abrir_processo(context, numero: str):
    """Vai a Consulta Processual, digita o numero (campos divididos) e abre os autos.

    Faz auto-dump do DOM em cada etapa (calibracao). Retorna a page dos autos.
    Levanta RuntimeError se nao conseguir — com o dump salvo para ajuste.
    """
    page = context.pages[0] if context.pages else await context.new_page()

    # garantir_login ja garantiu que o formulario de consulta esta na tela
    # (campo do numero presente). Nao re-navega para evitar a lentidao do TRF3.
    await _wait_pf_ajax(page)
    await _fechar_modais(page)

    if not await _preencher_numero(page, numero):
        await _dump_dom(page, "01b_consulta_sem_campo")
        raise RuntimeError(
            "Campos do numero do processo nao encontrados. "
            "DOM salvo em logs/pje_debug/ para calibracao."
        )

    await _tentar_clicar(page, _SEL_BOTAO_PESQUISAR, "pesquisar")
    await _wait_pf_ajax(page)
    await page.wait_for_timeout(2500)

    # No resultado, o link de abrir o processo e' um <a> dentro de
    # 'fPP:processosTable' cujo title/texto e' o proprio numero (mascarado).
    num_fmt = formatar_numero_cnj(numero)
    seletores_abrir = [
        f'a[title="{num_fmt}"]',
        'a[id*="processosTable"]',
        *_SEL_ABRIR_PROCESSO,
    ]
    alvo = None
    for sel in seletores_abrir:
        try:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                alvo = loc
                break
        except Exception:
            continue
    if alvo is None:
        await _dump_dom(page, "02b_resultado_sem_link")
        raise RuntimeError(
            "Nao foi possivel localizar o link do processo no resultado. "
            "DOM salvo em logs/pje_debug/ para calibracao."
        )

    # Abrir os autos costuma abrir uma NOVA ABA (popup). Capturamos; se nao
    # houver popup, seguimos na mesma page.
    autos = page
    try:
        async with context.expect_page(timeout=12000) as pg_info:
            await alvo.click()
        autos = await pg_info.value
    except Exception:
        await alvo.click()  # garante o clique caso expect_page tenha estourado
        if len(context.pages) > 1:
            autos = context.pages[-1]

    # Aguarda os autos carregarem (tolerante a lentidao).
    try:
        await autos.wait_for_load_state("domcontentloaded", timeout=_NAV_TIMEOUT_MS)
    except Exception:
        pass
    await _wait_pf_ajax(autos)
    await autos.wait_for_timeout(2500)
    await _dump_dom(autos, "03_autos")
    return autos


# Seletores CALIBRADOS da tela de autos (Autos Digitais) do TRF3.
_SEL_ABRIR_DIALOGO_DOWNLOAD = [
    'a[title="Download autos do processo"]',
    '[id="navbar:j_id219"]',
]
_SEL_DOWNLOAD_DT_INICIO = '[id="navbar:dtInicioInputDate"]'
_SEL_DOWNLOAD_DT_FIM = '[id="navbar:dtFimInputDate"]'
_SEL_DOWNLOAD_ID_DE = '[id="navbar:idDe"]'
_SEL_DOWNLOAD_ID_ATE = '[id="navbar:idAte"]'
# O botao AZUL visivel "Download" e' o navbar:j_id219 (type=button); o
# navbar:downloadProcesso (submit) fica oculto (display:none). Tentamos o
# visivel primeiro e por texto, com o oculto como ultimo recurso.
_SEL_DOWNLOAD_CONFIRMAR = [
    '[id="navbar:j_id219"]',
    'input[type="button"][value="Download"]',
    'input[type="submit"][value="Download"]',
    '[id="navbar:downloadProcesso"]',
]


async def _clicar_confirmar_download(page) -> bool:
    """Clica o botao 'Download' do dialogo. Tolerante: tenta varios seletores e
    clique normal -> forcado, sem exigir is_visible (o botao real pode reportar
    estados estranhos durante o AJAX do RichFaces)."""
    for sel in _SEL_DOWNLOAD_CONFIRMAR:
        loc = page.locator(sel).first
        try:
            if not await loc.count():
                continue
        except Exception:
            continue
        for forcar in (False, True):
            try:
                await loc.scroll_into_view_if_needed(timeout=2500)
            except Exception:
                pass
            try:
                await loc.click(timeout=5000, force=forcar)
                logger.info("download confirmado via %s (force=%s)", sel, forcar)
                return True
            except Exception as e:
                logger.warning("clique download %s (force=%s) falhou: %s", sel, forcar, str(e)[:80])
    return False


async def _set_valor(page, seletor: str, valor: str) -> bool:
    """Preenche um input por seletor (tolerante). Dispara blur via Tab."""
    try:
        loc = page.locator(seletor).first
        if await loc.count():
            await loc.fill(valor)
            await loc.press("Tab")
            return True
    except Exception as e:
        logger.warning("falha set %s=%s: %s", seletor, valor, e)
    return False


def _eh_url_pdf(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    return ("pjedocs" in u) or ("pje-downloads" in u) or (u.split("?")[0].endswith(".pdf"))


async def _baixar_pdf_da_aba(context, aba, pasta: Path) -> Path | None:
    """O PJe abre o PDF dos autos numa NOVA ABA (visualizador). Em vez de clicar
    no botao de salvar do visualizador, pegamos a URL e baixamos os bytes direto
    (a APIRequestContext reusa os cookies/sessao). Retorna o arquivo salvo."""
    import contextlib

    url = ""
    for _ in range(40):  # ate ~20s aguardando a URL do PDF aparecer
        url = aba.url or ""
        if _eh_url_pdf(url):
            break
        await aba.wait_for_timeout(500)
    if not _eh_url_pdf(url):
        return None

    nome = url.split("?")[0].rstrip("/").split("/")[-1] or "processo.pdf"
    if not nome.lower().endswith(".pdf"):
        nome += ".pdf"
    try:
        resp = await context.request.get(url)
        body = await resp.body()
        destino = pasta / _nome_unico(pasta, nome)
        destino.write_bytes(body)
        print(f"  [baixado] {destino.name} ({len(body)} bytes)")
        return destino
    except Exception as e:
        logger.warning("falha ao baixar PDF da aba: %s", e)
        return None
    finally:
        with contextlib.suppress(Exception):
            await aba.close()


async def baixar_autos(
    context,
    page,
    pasta: Path,
    *,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    id_de: str | None = None,
    id_ate: str | None = None,
    teto_seg: int = 240,
) -> list[Path]:
    """Baixa pecas dos autos via o dialogo 'Download autos do processo'.

    Duas estrategias (use uma):
      * Por DATA: data_inicio/data_fim no formato 'DD/MM/AAAA'.
      * Por ID: id_de/id_ate (mesmo valor nos dois baixa uma unica peca).

    Captura os downloads, salva em `pasta` e retorna os caminhos.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    salvos: list[Path] = []
    loop = asyncio.get_event_loop()
    ultimo = {"t": loop.time()}

    async def _on_download(download) -> None:
        destino = pasta / _nome_unico(pasta, download.suggested_filename or "peca")
        try:
            await download.save_as(str(destino))
            salvos.append(destino)
            ultimo["t"] = loop.time()
            print(f"  [baixado] {destino.name}")
        except Exception as e:
            logger.warning("falha salvar download: %s", e)

    def _reg(pg):
        pg.on("download", lambda d: asyncio.create_task(_on_download(d)))

    for pg in context.pages:
        _reg(pg)
    context.on("page", _reg)

    # 1) Abre o dialogo de download dos autos.
    if not await _tentar_clicar(page, _SEL_ABRIR_DIALOGO_DOWNLOAD, "abrir download"):
        await _dump_dom(page, "04_autos_sem_botao_download")
        print("  [aviso] icone 'Download autos do processo' nao localizado — DOM salvo.")
    await page.wait_for_timeout(1500)

    # 2) Preenche os criterios.
    if id_de or id_ate:
        await _set_valor(page, _SEL_DOWNLOAD_ID_DE, id_de or id_ate or "")
        await _set_valor(page, _SEL_DOWNLOAD_ID_ATE, id_ate or id_de or "")
        print(f"  [download] por ID: {id_de or id_ate} ate {id_ate or id_de}")
    if data_inicio:
        await _set_valor(page, _SEL_DOWNLOAD_DT_INICIO, data_inicio)
    if data_fim:
        await _set_valor(page, _SEL_DOWNLOAD_DT_FIM, data_fim)
    if data_inicio or data_fim:
        print(f"  [download] por data: {data_inicio or '...'} ate {data_fim or '...'}")

    # 3) Confirma o download. O PJe gera o PDF e abre numa NOVA ABA — capturamos
    #    a aba e baixamos o PDF direto pela URL.
    nova_aba = None
    clicou = False
    try:
        async with context.expect_page(timeout=120000) as pg_info:
            clicou = await _clicar_confirmar_download(page)
        nova_aba = await pg_info.value
    except Exception:
        pass

    if nova_aba is not None:
        arq = await _baixar_pdf_da_aba(context, nova_aba, pasta)
        if arq:
            salvos.append(arq)
    elif not clicou:
        await _dump_dom(page, "04b_dialogo_download")
        print("  [aviso] botao de confirmar download nao localizado — DOM salvo.")

    # 4) Aguarda eventuais downloads adicionais (caso o navegador dispare o
    #    evento de download em vez de abrir aba).
    inicio = loop.time()
    while (loop.time() - inicio) < 15:
        await asyncio.sleep(1)
        if salvos and (loop.time() - ultimo["t"]) >= 6:
            break
    return salvos


# --- Modo assistido (fallback garantido) ------------------------------------


async def capturar_pecas(context, pasta: Path, *, espera_inatividade_seg: int = 10,
                         teto_seg: int = 600) -> list[Path]:
    """Captura TODO arquivo que voce baixar manualmente, salvando em `pasta`.

    Usado como fallback enquanto a automacao nao esta calibrada.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    salvos: list[Path] = []
    loop = asyncio.get_event_loop()
    ultimo = {"t": loop.time()}

    async def _on_download(download) -> None:
        destino = pasta / _nome_unico(pasta, download.suggested_filename or "peca")
        try:
            await download.save_as(str(destino))
            salvos.append(destino)
            ultimo["t"] = loop.time()
            print(f"  [baixado] {destino.name}")
        except Exception as e:
            logger.warning("falha salvar download: %s", e)

    def _reg(pg):
        pg.on("download", lambda d: asyncio.create_task(_on_download(d)))

    for pg in context.pages:
        _reg(pg)
    context.on("page", _reg)

    print("-" * 64)
    print("  MODO ASSISTIDO: abra o processo e baixe os autos/pecas. Salvo em:")
    print(f"    {pasta}")
    print(f"  Encerro apos {espera_inatividade_seg}s sem novos downloads.")
    print("-" * 64)

    inicio = loop.time()
    ultimo["t"] = inicio
    while True:
        await asyncio.sleep(1)
        agora = loop.time()
        if salvos and (agora - ultimo["t"]) >= espera_inatividade_seg:
            break
        if (agora - inicio) >= teto_seg:
            break
    return salvos


# --- Numero do processo & utilidades ----------------------------------------


def numero_do_paj(paj_norm: str) -> str | None:
    """Le o numero do processo judicial do metadata.json de um PAJ.

    `paj_norm` ex: 'PAJ-2026-044-00311'. Retorna o numero (com mascara) ou None.
    """
    import json

    meta = config.PAJS_DIR / paj_norm / "metadata.json"
    if not meta.exists():
        return None
    try:
        dados = json.loads(meta.read_text(encoding="utf-8"))
    except Exception:
        return None
    return (dados.get("processo_judicial") or "").strip() or None


def formatar_numero_cnj(numero: str) -> str:
    """Normaliza para a mascara CNJ 'NNNNNNN-DD.AAAA.J.TR.OOOO' (20 digitos)."""
    d = re.sub(r"\D", "", numero or "")
    if len(d) != 20:
        return numero.strip()
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13:14]}.{d[14:16]}.{d[16:20]}"


def _nome_unico(pasta: Path, nome: str) -> str:
    if not (pasta / nome).exists():
        return nome
    stem, dot, ext = nome.rpartition(".")
    base, suf = (stem, ext) if dot else (nome, "")
    i = 1
    while (pasta / f"{base}_{i}{('.' + suf) if suf else ''}").exists():
        i += 1
    return f"{base}_{i}{('.' + suf) if suf else ''}"


def ocr_e_markdown(arquivos: list[Path], numero: str) -> str:
    """Roda OCR nos PDFs (reusa ingestao.ocr) e monta um digest .md agregado."""
    from ingestao import ocr

    linhas = [f"# Processo {formatar_numero_cnj(numero)} — pecas do PJe (TRF3)", ""]
    for arq in arquivos:
        linhas.append(f"## {arq.name}")
        if arq.suffix.lower() == ".pdf":
            try:
                texto = ocr.extrair_texto(
                    arq, timeout_por_pagina_seg=config.TIMEOUT_OCR_POR_PAGINA_SEG
                )
                if texto and "[OCR indisponivel" not in texto:
                    arq.with_suffix(".txt").write_text(texto, encoding="utf-8")
                    linhas.append(texto.strip())
                else:
                    linhas.append("_(OCR indisponivel)_")
            except Exception as e:
                linhas.append(f"_(erro de OCR: {type(e).__name__}: {e})_")
        else:
            linhas.append(f"_(arquivo nao-PDF: {arq.suffix})_")
        linhas.append("")
    return "\n".join(linhas) + "\n"


# --- Orquestrador ------------------------------------------------------------


def intervalo_por_intimacao(data_intimacao: str, *, dias_antes: int = 5) -> tuple[str, str]:
    """Dada a data da intimacao 'DD/MM/AAAA', devolve (inicio, fim) no formato
    'DD/MM/AAAA': inicio = intimacao - dias_antes (pega a decisao anterior),
    fim = hoje (data em que se esta analisando)."""
    import datetime as dt

    d = dt.datetime.strptime(data_intimacao.strip(), "%d/%m/%Y").date()
    inicio = d - dt.timedelta(days=dias_antes)
    fim = dt.date.today()
    return inicio.strftime("%d/%m/%Y"), fim.strftime("%d/%m/%Y")


async def processar(
    numero: str,
    pasta: Path,
    *,
    data_intimacao: str | None = None,
    dias_antes: int = 5,
    id_peca: str | None = None,
    assistido_fallback: bool = True,
) -> dict:
    """Fluxo completo: login manual -> buscar -> abrir -> baixar -> OCR -> md.

    Estrategia de download:
      * Se `id_peca`: baixa essa peca especifica (busca por ID).
      * Senao se `data_intimacao` ('DD/MM/AAAA'): baixa de (intimacao-`dias_antes`)
        ate hoje — pega a decisao anterior + tudo ate a data atual.
      * Senao: cai no modo assistido (voce baixa, ele captura).

    Retorna {numero, arquivos:[...], digest_md, modo}.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    pw, context = await _abrir_contexto()
    modo = "automatico"
    arquivos: list[Path] = []
    try:
        await garantir_login(context)
        try:
            autos = await buscar_e_abrir_processo(context, numero)
            if id_peca:
                arquivos = await baixar_autos(context, autos, pasta, id_de=id_peca, id_ate=id_peca)
            elif data_intimacao:
                ini, fim = intervalo_por_intimacao(data_intimacao, dias_antes=dias_antes)
                arquivos = await baixar_autos(context, autos, pasta, data_inicio=ini, data_fim=fim)
            else:
                raise RuntimeError("sem criterio de download (data_intimacao ou id_peca)")
        except Exception as e:
            logger.warning("automacao falhou: %s", e)
            print(f"  [aviso] automacao incompleta: {e}")
            if assistido_fallback:
                modo = "assistido"
                arquivos = await capturar_pecas(context, pasta)
            else:
                raise
        digest = ocr_e_markdown(arquivos, numero) if arquivos else ""
        if digest:
            (pasta / "_digest.md").write_text(digest, encoding="utf-8")
        return {
            "numero": formatar_numero_cnj(numero),
            "arquivos": [str(a) for a in arquivos],
            "digest_md": str(pasta / "_digest.md") if digest else None,
            "modo": modo,
        }
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            await context.close()
        with contextlib.suppress(Exception):
            await pw.stop()


# --- Sessao reutilizavel (autentica uma vez, consulta varios) ---------------


async def abrir_sessao():
    """Abre o navegador e garante login UMA vez. Idempotente: se a sessao ja
    estiver aberta, reusa. Retorna o contexto Playwright (mantido aberto)."""
    global _sessao_pw, _sessao_ctx
    if _sessao_ctx is not None:
        return _sessao_ctx
    _sessao_pw, _sessao_ctx = await _abrir_contexto()
    await garantir_login(_sessao_ctx)
    return _sessao_ctx


async def fechar_sessao() -> None:
    """Fecha o navegador/sessao. Chame so quando terminar TODAS as consultas."""
    global _sessao_pw, _sessao_ctx
    import contextlib

    if _sessao_ctx is not None:
        with contextlib.suppress(Exception):
            await _sessao_ctx.close()
    if _sessao_pw is not None:
        with contextlib.suppress(Exception):
            await _sessao_pw.stop()
    _sessao_ctx = None
    _sessao_pw = None


async def consultar(
    numero: str,
    pasta: Path,
    *,
    data_intimacao: str | None = None,
    dias_antes: int = 5,
    id_peca: str | None = None,
) -> dict:
    """Consulta UM processo reusando a sessao aberta (NAO fecha o navegador).

    Use `abrir_sessao()` antes (uma vez) e `fechar_sessao()` ao final de tudo.
    Fecha apenas a aba dos autos aberta nesta consulta, preservando a sessao
    autenticada para as proximas — evita reassinar a cada processo.
    """
    import contextlib

    context = await abrir_sessao()
    pasta.mkdir(parents=True, exist_ok=True)

    autos = await buscar_e_abrir_processo(context, numero)
    principal = context.pages[0] if context.pages else None
    arquivos: list[Path] = []
    try:
        if id_peca:
            arquivos = await baixar_autos(context, autos, pasta, id_de=id_peca, id_ate=id_peca)
        elif data_intimacao:
            ini, fim = intervalo_por_intimacao(data_intimacao, dias_antes=dias_antes)
            arquivos = await baixar_autos(context, autos, pasta, data_inicio=ini, data_fim=fim)
        else:
            raise RuntimeError("sem criterio de download (data_intimacao ou id_peca)")
    finally:
        # Fecha so a aba dos autos; mantem a sessao/consulta aberta.
        if autos is not None and autos is not principal:
            with contextlib.suppress(Exception):
                await autos.close()

    digest = ocr_e_markdown(arquivos, numero) if arquivos else ""
    if digest:
        (pasta / "_digest.md").write_text(digest, encoding="utf-8")
    return {
        "numero": formatar_numero_cnj(numero),
        "arquivos": [str(a) for a in arquivos],
        "digest_md": str(pasta / "_digest.md") if digest else None,
    }
