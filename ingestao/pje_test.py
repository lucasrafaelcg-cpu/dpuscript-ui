"""Teste manual de conexao com o PJe via MNI (SOMENTE LEITURA).

Uso (a partir da raiz do projeto, com a venv ativada):

    python -m ingestao.pje_test 5001234-56.2024.4.03.6130

Le as credenciais do .env (PJE_MNI_ID_CONSULTANTE / PJE_MNI_SENHA_CONSULTANTE)
e o endpoint de PJE_MNI_WSDL. Faz UMA chamada consultarProcesso, salva as pecas
numa pasta temporaria, roda OCR e imprime o digest em Markdown.

Nao escreve nada no PJe. Nao toca em PAJs/ — usa uma pasta _pje_teste/ local.
"""

from __future__ import annotations

import sys
from pathlib import Path

import config
from ingestao import pje_client


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Uso: python -m ingestao.pje_test <numero_do_processo>")
        return 2

    numero = argv[1]
    print(f"[pje-teste] endpoint: {config.PJE_MNI_WSDL}")
    print(f"[pje-teste] verify_tls: {config.PJE_MNI_VERIFY_TLS}")
    print(f"[pje-teste] id_consultante configurado: {bool(config.PJE_MNI_ID_CONSULTANTE)}")

    try:
        numero_norm = pje_client.normalizar_numero_processo(numero)
    except ValueError as e:
        print(f"[ERRO] {e}")
        return 1
    print(f"[pje-teste] consultando processo {numero_norm} ...")

    try:
        processo = pje_client.consultar_processo(
            numero_norm, incluir_documentos=True, incluir_movimentos=True
        )
    except pje_client.PJEConfigError as e:
        print(f"[ERRO de configuracao] {e}")
        return 1
    except pje_client.PJEConsultaError as e:
        print(f"[ERRO de consulta] {e}")
        return 1

    print("[pje-teste] consulta OK — baixando pecas e rodando OCR...")
    out = Path(__file__).resolve().parent.parent / "_pje_teste" / numero_norm
    pecas = pje_client.baixar_pecas(processo, out, limite=config.PJE_MAX_PECAS)
    print(f"[pje-teste] {len(pecas)} peca(s) com conteudo baixada(s) em {out}")

    md = pje_client.processo_para_markdown(processo, pecas)
    md_path = out / "_digest.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[pje-teste] digest gravado: {md_path}")
    print("\n" + "=" * 60)
    print(md[:2000])
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
