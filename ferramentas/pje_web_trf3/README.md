# Ferramenta de consulta PJe/TRF3 via navegador (SOMENTE LEITURA) — ARQUIVADA

Snapshot da solução que construímos do zero para consultar processos no PJe do
TRF3 (1º grau, Vara Federal e JEF de Osasco) automatizando o **navegador real**.
Funcionou de ponta a ponta em 01/06/2026 (proc. 5001690-86.2026.4.03.6130).

**Status:** arquivada. A partir de 01/06/2026 o projeto passou a usar o MCP do
colega portado para o TRF3 (ver `../../mcp_pje_trf3/`). Estes arquivos ficam aqui
para você poder VOLTAR a esta abordagem se quiser.

## Arquivos
- `pje_web.py` — núcleo: abre Chrome real, login manual, busca, abre autos,
  baixa por data/ID, OCR, Markdown. API de sessão reutilizável.
- `pje_web_test.py` — execução one-shot: `python -m ingestao.pje_web_test PAJ-... --data DD/MM/AAAA`
- `pje_web_console.py` — console: autentica 1× e consulta vários sem reassinar.

> Obs.: estes módulos importam `config` e `ingestao.ocr` do SIS. Para rodar,
> use as cópias originais em `C:\DPU\sis-dpu\ingestao\` (com a venv do SIS).
> Esta pasta é um arquivo/documentação, não um pacote standalone.

## O que aprendemos (conhecimento que destravou o TRF3)
1. **TRF3 fica atrás do Akamai (anti-bot).** Cliente headless / Chromium de
   automação → tela em branco ou timeout. Solução: dirigir o **Chrome REAL**
   (`channel="chrome"`) com janela VISÍVEL + `ignore_default_args=["--enable-automation"]`
   + `--disable-blink-features=AutomationControlled` + mascarar `navigator.webdriver`.
2. **HTTP/2 quebra na automação** → `ERR_HTTP2_PROTOCOL_ERROR`. Forçar
   `--disable-http2` (HTTP/1.1).
3. **Login manual + sessão persistente** (`user_data_dir`): autentica 1×; a
   senha nunca passa pelo código.
4. **Consulta Processual (form fPP):** número é dividido em campos
   (`fPP:numeroProcesso:numeroSequencial|numeroDigitoVerificador|Ano|NumeroOrgaoJustica`);
   botão `fPP:searchProcessos`; o resultado é `a[title="<numero mascarado>"]` e
   abre os autos em NOVA ABA.
5. **Autos:** ícone `a[title="Download autos do processo"]` abre diálogo com
   `navbar:dtInicioInputDate`/`navbar:dtFimInputDate` (datas) e `navbar:idDe`/`navbar:idAte`
   (IDs); botão azul visível = `navbar:j_id219`. O Download abre o PDF combinado
   em nova aba (`pje-downloads.trf3.jus.br/...processo.pdf?X-Amz-...`) → baixar via
   `context.request.get(url)` (reusa a sessão), NÃO pelo botão do visualizador.
6. **Estratégias de download:** por DATA (intimação −5 dias → hoje) ou por ID da peça.

## Como reativar (se um dia precisar)
Os módulos seguem em `C:\DPU\sis-dpu\ingestao\`. Rode, com a venv do SIS:
```
python -m ingestao.pje_web_console
```
e use o login manual + sessão persistente. Tudo SOMENTE LEITURA.
