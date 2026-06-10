"""Configuracao central do painel — aponta para o workspace Oficio Geral."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

OFICIO_GERAL = Path(os.getenv(
    "OFICIO_GERAL",
    str(Path.home() / "Desktop" / "Ofício Geral"),
))
PAJS_DIR = OFICIO_GERAL / "PAJs"
PECAS_FEITAS_DIR = OFICIO_GERAL / "Peças Feitas"

# Scripts do workspace usados pelo painel
GERAR_DOCX_SCRIPT = OFICIO_GERAL / "gerar_docx.py"
GERAR_PECA_SCRIPT = OFICIO_GERAL / "gerar_peticao.py"

# Credenciais SISDPU (usadas pela ingestao automatica — carregadas lazy, so
# validadas quando a sincronizacao e' disparada).
SISDPU_USERNAME = os.getenv("SISDPU_USERNAME", "")
SISDPU_PASSWORD = os.getenv("SISDPU_PASSWORD", "")
RATE_LIMIT_SISDPU = int(os.getenv("RATE_LIMIT_SISDPU_SEG", "2"))
TIMEOUT_TOTAL = int(os.getenv("TIMEOUT_TOTAL_SEG", "3600"))
# Limite de anexos baixados do SISDPU por PAJ (protege contra PAJs gigantes).
# Se um PAJ tiver mais que isso, o sync baixa os N mais recentes e avisa no log.
MAX_ANEXOS_POR_PAJ = int(os.getenv("MAX_ANEXOS_POR_PAJ", "30"))

# Timeout por pagina no Tesseract (segundos). PDFs escaneados grandes ou
# corrompidos podem travar o OCR — esse limite garante progresso.
TIMEOUT_OCR_POR_PAGINA_SEG = int(os.getenv("TIMEOUT_OCR_POR_PAGINA_SEG", "30"))

# Pasta onde DOCX/PDF gerados pelo docgen sao salvos.
# Default: <OFICIO_GERAL>/Peças Feitas
DOCGEN_OUT_DIR = Path(os.getenv("DOCGEN_OUT_DIR", str(OFICIO_GERAL / "Peças Feitas")))

# Analise FIRAC automatica: quando a sincronizacao detecta que um PAJ entrou
# na caixa (evento de triagem novo), a analise da situacao roda sozinha em
# fila de fundo (Claude CLI, 1 por vez) — sem precisar do botao. Desligue com
# SITUACAO_AUTO=false no .env se quiser voltar ao modo manual.
SITUACAO_AUTO = os.getenv("SITUACAO_AUTO", "true").strip().lower() != "false"

# ---------------------------------------------------------------------------
# Integracao PJe / MNI (Modelo Nacional de Interoperabilidade) — SOMENTE LEITURA
# ---------------------------------------------------------------------------
# Consulta processual no PJe via webservice MNI (operacao consultarProcesso).
# NAO ha peticionamento/escrita: o cliente so implementa consultarProcesso.
#
# As credenciais (idConsultante/senhaConsultante) sao institucionais da DPU,
# habilitadas pelo tribunal. Ficam SO no .env — nunca no codigo. Carregadas
# lazy: so validadas quando uma consulta e' efetivamente disparada.
#
# Endpoint padrao: TRF3 1o grau (cobre Vara Federal de Osasco e o JEF de Osasco).
# Para 2o grau (TRF3), troque PJE_MNI_WSDL no .env.
PJE_MNI_WSDL = os.getenv(
    "PJE_MNI_WSDL",
    "https://pje1g.trf3.jus.br/pje/intercomunicacao?wsdl",
)
PJE_MNI_ID_CONSULTANTE = os.getenv("PJE_MNI_ID_CONSULTANTE", "")
PJE_MNI_SENHA_CONSULTANTE = os.getenv("PJE_MNI_SENHA_CONSULTANTE", "")
# Verificacao de certificado TLS do servidor. SEMPRE True em producao; so
# coloque "false" no .env para diagnostico pontual contra ambiente de
# homologacao com certificado autoassinado.
PJE_MNI_VERIFY_TLS = os.getenv("PJE_MNI_VERIFY_TLS", "true").strip().lower() != "false"
# Timeout (segundos) das chamadas SOAP ao MNI.
PJE_MNI_TIMEOUT_SEG = int(os.getenv("PJE_MNI_TIMEOUT_SEG", "60"))
# Quantas pecas mais recentes baixar por consulta (protege contra processos
# gigantes). As N mais recentes sao priorizadas.
PJE_MAX_PECAS = int(os.getenv("PJE_MAX_PECAS", "15"))

# ---------------------------------------------------------------------------
# Integracao PJe via navegador (Playwright) — caminho alternativo ao MNI.
# ---------------------------------------------------------------------------
# Usa LOGIN MANUAL + SESSAO PERSISTENTE: o navegador abre, o usuario faz login
# uma vez (senha OU certificado), e a sessao (cookies) fica salva localmente em
# PJE_WEB_USER_DATA_DIR. A SENHA NUNCA e' digitada nem armazenada pelo codigo —
# por isso nao ha variavel de senha aqui. O diretorio de sessao e' ignorado
# pelo git (.gitignore), entao nada sensivel vai para o repositorio.
PJE_WEB_LOGIN_URL = os.getenv(
    "PJE_WEB_LOGIN_URL",
    "https://pje1g.trf3.jus.br/pje/login.seam",
)
# Host autenticado do PJe — usado para detectar que o login terminou (saiu do
# dominio do SSO e voltou para o PJe).
PJE_WEB_HOST = os.getenv("PJE_WEB_HOST", "pje1g.trf3.jus.br")
# Diretorio LOCAL da sessao persistente do navegador (cookies/login). Sensivel —
# fica fora do git. Default: <raiz do projeto>/.pje_session
PJE_WEB_USER_DATA_DIR = Path(
    os.getenv("PJE_WEB_USER_DATA_DIR", str(Path(__file__).parent / ".pje_session"))
)
# Tempo maximo (segundos) que o sistema aguarda voce concluir o login manual.
PJE_WEB_LOGIN_TIMEOUT_SEG = int(os.getenv("PJE_WEB_LOGIN_TIMEOUT_SEG", "300"))
# URL da Consulta Processual autenticada (onde se digita o numero do processo).
# Ajustavel: o caminho exato pode variar por versao do PJe/TRF3.
PJE_WEB_CONSULTA_URL = os.getenv(
    "PJE_WEB_CONSULTA_URL",
    "https://pje1g.trf3.jus.br/pje/Processo/ConsultaProcesso/listView.seam",
)


def validar_paths() -> list[str]:
    """Verifica que OFICIO_GERAL/PAJS_DIR existem. Retorna lista de avisos
    (vazia se tudo ok). Usada no startup pelo app.py — nao crasha a importacao
    para que ferramentas como ruff/pytest possam importar sem precisar do
    workspace montado."""
    erros: list[str] = []
    if not OFICIO_GERAL.exists():
        erros.append(f"OFICIO_GERAL nao encontrado: {OFICIO_GERAL}")
    if not PAJS_DIR.exists():
        erros.append(f"PAJS_DIR nao encontrado: {PAJS_DIR}")
    return erros
