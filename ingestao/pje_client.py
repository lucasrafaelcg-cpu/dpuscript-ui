"""Cliente PJe via MNI (Modelo Nacional de Interoperabilidade) — SOMENTE LEITURA.

Espelha o padrao de `sisdpu_client.py`, mas para o webservice SOAP do PJe
(TRF3 1o grau por padrao — cobre a Vara Federal e o JEF de Osasco).

ESCOPO DELIBERADAMENTE RESTRITO A CONSULTA:
    - A unica operacao MNI implementada e' `consultarProcesso` (leitura).
    - NAO existe `entregarManifestacaoProcessual` (peticionamento/escrita) neste
      modulo, por decisao de projeto. Isto e' uma ferramenta de leitura/analise.

Fluxo tipico:
    1. `consultar_processo(numero)` -> dict com cabecalho, partes, movimentos e
       a lista de documentos (com conteudo em base64 quando solicitado).
    2. `baixar_pecas(processo, pasta)` -> grava os PDFs e roda OCR (reusa
       `ingestao.ocr`), devolvendo o caminho de cada peca + texto extraido.
    3. `processo_para_markdown(processo, pecas)` -> monta um digest .md enxuto
       para a analise por IA.

Dependencias: `zeep` (cliente SOAP/WSDL). Adicionada em requirements.txt.
As credenciais vem de `config` (carregadas do .env) — nunca hardcoded.
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

# Operacao MNI permitida. Mantida como constante explicita para deixar claro,
# em revisao de codigo, que este modulo NAO escreve no PJe.
_OPERACAO_PERMITIDA = "consultarProcesso"


class PJEConfigError(RuntimeError):
    """Configuracao do MNI ausente ou invalida (ex: credenciais faltando)."""


class PJEConsultaError(RuntimeError):
    """Falha na consulta ao MNI (rede, autenticacao, processo inexistente...)."""


def normalizar_numero_processo(numero: str) -> str:
    """Remove mascara do numero CNJ, devolvendo so os 20 digitos.

    Aceita '5001234-56.2024.4.03.6130' ou '50012345620244036130' e devolve
    '50012345620244036130'. Levanta ValueError se nao resultar em 20 digitos.
    """
    so_digitos = re.sub(r"\D", "", numero or "")
    if len(so_digitos) != 20:
        raise ValueError(
            f"Numero de processo invalido: {numero!r} "
            f"(esperado 20 digitos, obtido {len(so_digitos)})"
        )
    return so_digitos


def _criar_cliente(verify_tls: bool, timeout: int):
    """Instancia o cliente zeep apontando para o WSDL configurado.

    Importacao de zeep e' lazy (dentro da funcao) para que o modulo possa ser
    importado em ambientes sem a dependencia instalada (ex: CI/lint) sem quebrar.
    """
    try:
        from zeep import Client, Settings
        from zeep.transports import Transport
    except ImportError as e:  # pragma: no cover - depende do ambiente
        raise PJEConfigError(
            "Pacote 'zeep' nao instalado. Rode: pip install zeep"
        ) from e

    import httpx

    wsdl = config.PJE_MNI_WSDL
    if not wsdl:
        raise PJEConfigError("PJE_MNI_WSDL nao configurado no .env")

    # Transport com verificacao TLS controlada e timeout. zeep usa requests por
    # padrao; passamos uma Session com verify configuravel.
    import requests

    session = requests.Session()
    session.verify = verify_tls
    transport = Transport(session=session, timeout=timeout, operation_timeout=timeout)
    settings = Settings(strict=False, xml_huge_tree=True)
    logger.info("MNI: conectando WSDL %s (verify_tls=%s)", wsdl, verify_tls)
    return Client(wsdl=wsdl, transport=transport, settings=settings)


def consultar_processo(
    numero: str,
    *,
    incluir_documentos: bool = True,
    incluir_movimentos: bool = True,
    ids_documentos: list[str] | None = None,
) -> dict[str, Any]:
    """Consulta um processo no PJe via MNI `consultarProcesso` (somente leitura).

    Args:
        numero: numero do processo (com ou sem mascara CNJ).
        incluir_documentos: pede o conteudo das pecas (base64 inline). Pode ser
            pesado; combine com `ids_documentos` para pecas especificas.
        incluir_movimentos: inclui a lista de movimentacoes.
        ids_documentos: se informado, restringe o conteudo a essas pecas.

    Returns:
        dict serializado da resposta MNI (sucesso, mensagem, processo{...}).

    Raises:
        PJEConfigError: credenciais/endpoint ausentes.
        PJEConsultaError: falha de rede/autenticacao ou processo nao retornado.
    """
    id_consultante = config.PJE_MNI_ID_CONSULTANTE
    senha = config.PJE_MNI_SENHA_CONSULTANTE
    if not id_consultante or not senha:
        raise PJEConfigError(
            "Credenciais MNI ausentes. Configure PJE_MNI_ID_CONSULTANTE e "
            "PJE_MNI_SENHA_CONSULTANTE no .env (credenciais institucionais DPU "
            "habilitadas pelo tribunal)."
        )

    num = normalizar_numero_processo(numero)

    cliente = _criar_cliente(config.PJE_MNI_VERIFY_TLS, config.PJE_MNI_TIMEOUT_SEG)

    # Monta os argumentos da operacao. Nem todo tribunal aceita todos os campos;
    # zeep introspecta o WSDL, entao passamos os parametros padrao do MNI 2.2.2
    # e deixamos campos opcionais de fora quando nao usados.
    kwargs: dict[str, Any] = {
        "idConsultante": id_consultante,
        "senhaConsultante": senha,
        "numeroProcesso": num,
        "movimentos": bool(incluir_movimentos),
        "incluirCabecalho": True,
        "incluirDocumentos": bool(incluir_documentos),
    }
    if ids_documentos:
        kwargs["documento"] = list(ids_documentos)

    try:
        resposta = cliente.service.consultarProcesso(**kwargs)
    except Exception as e:  # zeep levanta varios tipos; normalizamos
        raise PJEConsultaError(
            f"Falha ao consultar processo {num} no MNI: {type(e).__name__}: {e}"
        ) from e

    from zeep.helpers import serialize_object

    dados = serialize_object(resposta) or {}
    # serialize_object devolve OrderedDict aninhado; convertendo para dict puro
    # via round-trip simples mantem o codigo a jusante agnostico de zeep.
    sucesso = dados.get("sucesso")
    if sucesso is False:
        raise PJEConsultaError(
            f"MNI recusou a consulta de {num}: {dados.get('mensagem') or 'sem mensagem'}"
        )
    return dict(dados)


# --- Extracao de pecas + OCR --------------------------------------------------

# Assinaturas de tipo MIME -> extensao, para nomear as pecas baixadas.
_MIME_EXT = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "text/plain": ".txt",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def _ext_por_mime(mimetype: str | None) -> str:
    return _MIME_EXT.get((mimetype or "").lower().strip(), ".bin")


def _extrair_documentos(processo: dict[str, Any]) -> list[dict[str, Any]]:
    """Normaliza a lista de documentos da resposta MNI para uma forma estavel.

    A estrutura exata varia por tribunal; navegamos defensivamente.
    """
    proc = processo.get("processo") or processo
    docs = proc.get("documento") or proc.get("documentos") or []
    if isinstance(docs, dict):
        docs = [docs]
    norm: list[dict[str, Any]] = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        norm.append(
            {
                "id": str(d.get("idDocumento") or d.get("id") or ""),
                "descricao": (d.get("descricao") or d.get("tipoDocumento") or "").strip(),
                "mimetype": d.get("mimetype") or d.get("mimeType") or "",
                "data": d.get("dataHora") or d.get("data") or "",
                "nivel_sigilo": d.get("nivelSigilo"),
                "conteudo_b64": d.get("conteudo"),
            }
        )
    return norm


def baixar_pecas(
    processo: dict[str, Any],
    pasta: Path,
    *,
    limite: int | None = None,
    rodar_ocr: bool = True,
    deve_cancelar: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Grava em `pasta` as pecas com conteudo retornadas pelo MNI e roda OCR.

    Reusa `ingestao.ocr.extrair_texto` para gerar um companion .txt por PDF.
    Prioriza as pecas mais recentes (assume ordem do MNI; faz fallback estavel).

    Returns: lista de dicts {id, descricao, arquivo, texto, ocr_ok}.
    """
    from ingestao import ocr

    pasta.mkdir(parents=True, exist_ok=True)
    docs = _extrair_documentos(processo)
    # Mantem so os que vieram com conteudo inline.
    docs_com_conteudo = [d for d in docs if d.get("conteudo_b64")]
    if limite is not None:
        docs_com_conteudo = docs_com_conteudo[:limite]

    resultado: list[dict[str, Any]] = []
    for idx, d in enumerate(docs_com_conteudo, start=1):
        if deve_cancelar is not None and deve_cancelar():
            logger.info("baixar_pecas: cancelado pelo usuario em %d", idx)
            break
        try:
            conteudo = base64.b64decode(d["conteudo_b64"])
        except Exception as e:
            logger.warning("peca %s: base64 invalido: %s", d.get("id"), e)
            continue
        ext = _ext_por_mime(d.get("mimetype"))
        nome = f"{idx:02d}_{_slug(d.get('descricao') or d.get('id') or 'peca')}{ext}"
        destino = pasta / nome
        destino.write_bytes(conteudo)

        texto = ""
        ocr_ok = False
        if rodar_ocr and ext == ".pdf":
            try:
                texto = ocr.extrair_texto(
                    destino,
                    deve_cancelar=deve_cancelar,
                    timeout_por_pagina_seg=config.TIMEOUT_OCR_POR_PAGINA_SEG,
                )
                ocr_ok = bool(texto) and "[OCR indisponivel" not in texto
                if ocr_ok:
                    destino.with_suffix(".txt").write_text(texto, encoding="utf-8")
            except Exception as e:
                logger.warning("OCR falhou em %s: %s", destino.name, e)

        resultado.append(
            {
                "id": d.get("id"),
                "descricao": d.get("descricao"),
                "arquivo": str(destino),
                "texto": texto,
                "ocr_ok": ocr_ok,
            }
        )
    return resultado


_SLUG_RE = re.compile(r"[^A-Za-z0-9._\- ]+")


def _slug(s: str) -> str:
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", s or "")
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return (_SLUG_RE.sub("_", sem_acento).strip(" ._") or "peca")[:50]


# --- Digest em Markdown -------------------------------------------------------


def processo_para_markdown(
    processo: dict[str, Any],
    pecas: list[dict[str, Any]] | None = None,
    *,
    max_movimentos: int = 20,
) -> str:
    """Monta um resumo em Markdown do processo + pecas, leve para analise por IA.

    Inclui: cabecalho (classe, assunto, orgao, valor), polos/partes, ultimas
    movimentacoes e o texto OCR das pecas baixadas.
    """
    proc = processo.get("processo") or processo
    basicos = proc.get("dadosBasicos") or proc.get("dados_basicos") or {}

    linhas: list[str] = ["# Processo PJe — consulta MNI", ""]

    def add(rotulo: str, valor: Any) -> None:
        if valor:
            linhas.append(f"- **{rotulo}:** {valor}")

    add("Numero", basicos.get("numero") or proc.get("numero"))
    add("Classe", basicos.get("classeProcessual"))
    add("Orgao julgador", _nome_orgao(basicos.get("orgaoJulgador")))
    add("Valor da causa", basicos.get("valorCausa"))
    add("Nivel de sigilo", basicos.get("nivelSigilo"))

    # Assuntos
    assuntos = basicos.get("assunto") or []
    if isinstance(assuntos, dict):
        assuntos = [assuntos]
    nomes_assunto = [a.get("codigoNacional") or a.get("descricao") for a in assuntos if isinstance(a, dict)]
    if nomes_assunto:
        add("Assuntos", ", ".join(str(x) for x in nomes_assunto if x))

    # Partes (polos)
    polos = basicos.get("polo") or []
    if isinstance(polos, dict):
        polos = [polos]
    if polos:
        linhas += ["", "## Partes"]
        for polo in polos:
            if not isinstance(polo, dict):
                continue
            tipo = polo.get("polo") or polo.get("tipoPolo") or "?"
            partes = polo.get("parte") or []
            if isinstance(partes, dict):
                partes = [partes]
            for parte in partes:
                if not isinstance(parte, dict):
                    continue
                pessoa = parte.get("pessoa") or {}
                nome = pessoa.get("nome") if isinstance(pessoa, dict) else None
                linhas.append(f"- **{tipo}:** {nome or '—'}")

    # Movimentos (mais recentes)
    movs = proc.get("movimento") or []
    if isinstance(movs, dict):
        movs = [movs]
    if movs:
        linhas += ["", f"## Ultimas movimentacoes (ate {max_movimentos})"]
        for m in movs[:max_movimentos]:
            if not isinstance(m, dict):
                continue
            data = m.get("dataHora") or m.get("data") or ""
            desc = _texto_movimento(m)
            linhas.append(f"- [{data}] {desc}")

    # Pecas / OCR
    if pecas:
        linhas += ["", "## Pecas baixadas (texto extraido)"]
        for p in pecas:
            linhas.append(f"\n### {p.get('descricao') or p.get('id')}")
            txt = (p.get("texto") or "").strip()
            if txt:
                linhas.append(txt)
            else:
                linhas.append("_(sem texto extraido / OCR indisponivel)_")

    return "\n".join(linhas) + "\n"


def _nome_orgao(orgao: Any) -> str | None:
    if isinstance(orgao, dict):
        return orgao.get("nomeOrgao") or orgao.get("nome")
    return orgao


def _texto_movimento(m: dict[str, Any]) -> str:
    nac = m.get("movimentoNacional") or {}
    if isinstance(nac, dict) and nac.get("complemento"):
        return str(nac.get("complemento"))
    loc = m.get("movimentoLocal") or {}
    if isinstance(loc, dict) and loc.get("complemento"):
        return str(loc.get("complemento"))
    return str(m.get("complemento") or m.get("descricao") or "movimento")
