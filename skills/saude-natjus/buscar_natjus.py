#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Busca e baixa notas tecnicas FAVORAVEIS do e-NATJus (CNJ) para um PAJ.

Adaptado ao layout deste painel:
  - grava em   <OFICIO_GERAL>/PAJs/<PAJ-NORM>/natjus/
  - copia para <OFICIO_GERAL>/PAJs/<PAJ-NORM>/pecas/  (aparece na aba Pecas e
    entra no contexto da analise do PAJ)
  - extrai o texto de cada PDF num .txt ao lado — sem isso a nota fica
    ilegivel para a analise

FORMULARIO DO e-NATJus (verificado no site, 08/2026):
  A pesquisa publica esta em pesquisaPublica.php. Os campos de tecnologia NAO
  aceitam texto livre: "Tecnologia" (#txtTecnologiaE) e' readonly, e a escolha
  se faz por LISTAS CONTROLADAS via Select2 com AJAX:
    #txtDcb          -> Principio Ativo   (ex.: INSULINA GLARGINA)
    #txtDcbComercial -> Nome comercial
    #txtCid          -> CID               (ex.: E11 - Diabetes mellitus...)
    #selConclusao    -> Conclusao Justificada  (F = Favoravel, N = Nao favoravel)
    #btnPesquisar    -> dispara a busca
  Resultados: tabela #tabela-notaTecnica, colunas
    [0] ID | [1] Data | [2] Tecnologia | [3] CID | [4] NatJus | [5] Status
  e, na ultima celula, o link a.btn-download ("Gerar documento").

Uso:
    python buscar_natjus.py --tecnologia "Insulina Glargina" \
        --cid E11 --paj PAJ-2025-056-00701

Saida (stdout): linhas STATUS: | NOTA: | AVISO: | ERRO: | RESULTADO:
"""

import argparse
import asyncio
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

URL_BUSCA = "https://www.pje.jus.br/e-natjus/pesquisaPublica.php"

# O Chromium empacotado do Playwright nao e' assinado e o Smart App Control do
# Windows as vezes o bloqueia (reportando o erro enganoso "Executable doesn't
# exist"). Chrome/Edge instalados sao assinados e sempre passam.
CANAIS = (None, "chrome", "msedge")


def parse_args():
    p = argparse.ArgumentParser(description="Baixa notas tecnicas favoraveis do e-NATJus.")
    p.add_argument("--tecnologia", required=True,
                   help="principio ativo ou nome comercial (ex.: 'Insulina Glargina')")
    p.add_argument("--cid", default="", help="CID, ex.: E11 ou E11.9 (opcional, recomendado)")
    p.add_argument("--principio-ativo", default="", dest="principio_ativo",
                   help="alternativa a --tecnologia, se souber o principio ativo exato")
    p.add_argument("--paj", required=True,
                   help="PAJ-2025-056-00701 | 2025-056-00701 | 2025/056-00701")
    p.add_argument("--max", type=int, default=3, dest="max_notas")
    p.add_argument("--oficio", default="",
                   help="raiz do workspace Oficio Geral (default: env OFICIO_GERAL)")
    return p.parse_args()


def normalizar_paj(bruto: str) -> str:
    t = bruto.strip().upper().replace("/", "-")
    return t if t.startswith("PAJ-") else "PAJ-" + t


def resolver_oficio(arg: str) -> Path:
    if arg:
        return Path(arg)
    env = (os.getenv("OFICIO_GERAL") or "").strip()
    return Path(env) if env else Path.home() / "Desktop" / "Ofício Geral"


def data_br_para_iso(data_br: str) -> str:
    try:
        return datetime.strptime(data_br.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except Exception:
        return data_br.strip().replace("/", "-")


def extrair_texto_pdf(pdf: Path) -> str:
    """Texto nativo do PDF. Vazio se for digitalizado (OCR fica com o painel)."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        doc = fitz.open(pdf)
    except Exception:
        return ""
    try:
        return "\n".join(
            f"=== pagina {i} ===\n{(pag.get_text() or '').strip()}\n"
            for i, pag in enumerate(doc, start=1)
        )
    finally:
        doc.close()


async def _abrir_browser(pw):
    ultimo = None
    for canal in CANAIS:
        try:
            return await pw.chromium.launch(headless=True, channel=canal), (canal or "chromium-empacotado")
        except Exception as e:
            ultimo = e
    raise ultimo


async def _escolher_em_lista(page, campo_id: str, termo: str) -> str | None:
    """Escolhe a 1a opcao de um Select2 com AJAX. Retorna o texto escolhido.

    Abre via jQuery (o clique no container e' interceptado pelo layout) e
    confirma com Enter (clicar na opcao tambem e' interceptado).
    """
    try:
        await page.evaluate(
            """(id) => {
                const el = document.getElementById(id);
                if (el && window.jQuery && jQuery(el).data('select2')) jQuery(el).select2('open');
            }""",
            campo_id,
        )
        await page.wait_for_timeout(600)
        busca = page.locator(".select2-search__field:visible").first
        if await busca.count() == 0:
            return None
        await busca.type(termo, delay=80)
        await page.wait_for_timeout(2500)
        opt = page.locator(".select2-results__option").first
        if await opt.count() == 0:
            await page.keyboard.press("Escape")
            return None
        texto = (await opt.inner_text()).strip()
        if "nenhum resultado" in texto.lower() or not texto:
            await page.keyboard.press("Escape")
            return None
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(500)
        return texto
    except Exception:
        return None


async def executar(args) -> int:
    from playwright.async_api import async_playwright

    paj_norm = normalizar_paj(args.paj)
    pasta_paj = resolver_oficio(args.oficio) / "PAJs" / paj_norm
    if not pasta_paj.is_dir():
        print(f"ERRO: pasta do PAJ nao encontrada: {pasta_paj}")
        print("ERRO: confira o numero do PAJ e a variavel OFICIO_GERAL.")
        return -1

    pasta_natjus = pasta_paj / "natjus"
    pasta_pecas = pasta_paj / "pecas"
    pasta_natjus.mkdir(parents=True, exist_ok=True)
    pasta_pecas.mkdir(parents=True, exist_ok=True)

    termo_tec = (args.principio_ativo or args.tecnologia).strip()
    print(f"STATUS: tecnologia='{termo_tec}' | cid='{args.cid}' | destino={pasta_natjus}")

    async with async_playwright() as pw:
        browser, canal = await _abrir_browser(pw)
        print(f"STATUS: navegador={canal}")
        context = await browser.new_context(
            accept_downloads=True, viewport={"width": 1366, "height": 900}
        )
        page = await context.new_page()
        try:
            print("STATUS: carregando o e-NATJus...")
            await page.goto(URL_BUSCA, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(2500)

            # Tecnologia: tenta Principio Ativo e, se nao houver, Nome comercial.
            escolhido = await _escolher_em_lista(page, "txtDcb", termo_tec)
            if escolhido:
                print(f"STATUS: principio ativo selecionado: {escolhido}")
            else:
                escolhido = await _escolher_em_lista(page, "txtDcbComercial", termo_tec)
                if escolhido:
                    print(f"STATUS: nome comercial selecionado: {escolhido}")
            if not escolhido:
                print(f"ERRO: '{termo_tec}' nao existe nas listas do e-NATJus "
                      "(nem como principio ativo, nem como nome comercial).")
                print("ERRO: confira a grafia ou tente o principio ativo em vez do nome comercial.")
                return -1

            if args.cid:
                cid_sel = await _escolher_em_lista(page, "txtCid", args.cid)
                if cid_sel:
                    print(f"STATUS: CID selecionado: {cid_sel}")
                else:
                    print(f"AVISO: CID '{args.cid}' nao encontrado — pesquisando sem filtro de CID")

            await page.select_option("#selConclusao", "F")
            print("STATUS: conclusao = Favoravel")

            await page.click("#btnPesquisar")
            print("STATUS: pesquisando...")
            await page.wait_for_timeout(6000)

            linhas = page.locator("#tabela-notaTecnica tbody tr")
            total = await linhas.count()
            if total == 0 or await page.locator("#tabela-notaTecnica a.btn-download").count() == 0:
                print("RESULTADO: NENHUMA_NOTA_BAIXADA")
                print("INSTRUCAO: seguir pela Etapa 3-B da skill (argumentacao juridica apenas).")
                return 0

            # Coleta metadados de cada linha (ID/Data/Tecnologia/CID/NatJus).
            registros = []
            for i in range(min(total, 60)):
                cel = linhas.nth(i).locator("td")
                if await cel.count() < 5:
                    continue
                if await linhas.nth(i).locator("a.btn-download").count() == 0:
                    continue
                dados = [(await cel.nth(j).inner_text()).strip() for j in range(5)]
                registros.append({
                    "linha": i,
                    "id": dados[0],
                    "data_br": dados[1],
                    "data_iso": data_br_para_iso(dados[1]),
                    "tecnologia": dados[2],
                    "cid": dados[3],
                    "natjus": dados[4],
                })

            registros.sort(key=lambda r: r["data_iso"], reverse=True)
            selecionadas = registros[: args.max_notas]
            print(f"STATUS: {len(registros)} nota(s) favoravel(is) | baixando {len(selecionadas)} mais recente(s)")

            baixados = 0
            for seq, r in enumerate(selecionadas, start=1):
                nome = f"natjus_{seq:02d}_{r['data_iso']}_id{r['id']}.pdf"
                destino = pasta_natjus / nome
                try:
                    btn = linhas.nth(r["linha"]).locator("a.btn-download").first
                    # expect_download vive na Page (nao no BrowserContext) nas
                    # versoes atuais do Playwright.
                    async with page.expect_download(timeout=90000) as dl:
                        await btn.click()
                    await (await dl.value).save_as(str(destino))
                    kb = destino.stat().st_size // 1024

                    a, m, d = r["data_iso"].split("-")
                    nome_pecas = f"90_{d}_{m}_{a}_NOTA TECNICA NATJUS {seq:02d} id{r['id']}.pdf"
                    shutil.copy2(str(destino), str(pasta_pecas / nome_pecas))

                    texto = extrair_texto_pdf(destino)
                    if texto.strip():
                        destino.with_suffix(".txt").write_text(texto, encoding="utf-8")
                        (pasta_pecas / nome_pecas).with_suffix(".txt").write_text(texto, encoding="utf-8")
                    else:
                        print(f"AVISO: nota {seq} sem texto nativo — rode o OCR do painel para ler o teor")

                    print(f"NOTA: {seq} | id={r['id']} | {r['data_br']} | {r['natjus']} | "
                          f"{r['tecnologia']} | CID {r['cid'][:28]} | {kb} KB | {nome}")
                    baixados += 1
                except Exception as e:
                    print(f"AVISO: falha ao baixar nota {seq} (id={r['id']}): {type(e).__name__}: {e}")

            return baixados
        finally:
            await browser.close()


def main() -> int:
    args = parse_args()
    try:
        baixados = asyncio.run(executar(args))
    except Exception as e:
        print(f"ERRO: {type(e).__name__}: {e}")
        return 1

    if baixados < 0:
        return 1
    if baixados == 0:
        print("RESULTADO: NENHUMA_NOTA_BAIXADA")
        print("INSTRUCAO: seguir pela Etapa 3-B da skill (argumentacao juridica apenas).")
    else:
        print(f"RESULTADO: {baixados}_NOTA(S)_BAIXADA(S)")
        print("INSTRUCAO: ler os .txt em natjus/ e seguir pela Etapa 3-A da skill.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
