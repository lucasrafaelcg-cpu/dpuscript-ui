# Changelog — Integração SIS DPU

Esta é uma versão derivada (fork) do **DPU-script-SIS**, com um conjunto de
features novas voltadas à integração com o **PJe/TRF3**, à análise **FIRAC**
e ao fluxo de trabalho de triagem do 1º Ofício.

Todas as features abaixo são commits limpos sobre o projeto original, então
o upstream (ou qualquer fork irmão) pode **puxar tudo** (merge deste branch) ou
**puxar só uma feature** com `git cherry-pick <hash>`.

> Para cherry-pick, primeiro adicione este fork como remote:
> `git remote add integracao https://github.com/tadeuceia/dpuscript-ui.git`
> `git fetch integracao`

## Features (mais recente → mais antiga)

| Feature | Commit | O que entrega |
|---|---|---|
| Skill FIRAC versionada | `77ec1e5` | Skill de análise integrada + guia de instalação em `skills/firac/`. |
| Coluna/filtro "Última movimentação" | `ec3f2e0` | Dashboard classifica o evento recente entre os 4 fluxos da caixa. |
| Fase 4 — fechamento do ciclo | `4f7745c` | Elaboração concluída sai da Caixa de triagem (idempotente). |
| Sync preserva estado + guard intimação | `1958e75` | Sync não apaga estado do fluxo nem roda FIRAC cega de intimação. |
| Parser: processo judicial das movimentações | `fe5c4f2` | Extrai o nº do processo de PAJs abertos por intimação (+ backfill). |
| Fase 3c — intimação em 1 clique | `26ef68a` | Baixa peças do PJe + OCR + FIRAC encadeados num clique. |
| FIRAC automática ao entrar na caixa | `45bb185` | Análise FIRAC enfileirada quando o PAJ entra na caixa. |
| Aba Situação do PAJ (FIRAC executada) | `d29a063` | Mostra a análise FIRAC já realizada. |
| Fase 2 — gancho de triagem + Caixa | `b54e721` | Detecção de triagem no sync + Caixa de triagem no dashboard. |
| PROMPT_MAX guiado pela skill FIRAC | `258d8e6` | Prompt de situação estruturado pela FIRAC. |
| **Integração PJe/TRF3** | `d7ecb8e` (+ `c4d9172`) | Situação processual, puxar peças, gatilho de intimação (só leitura, sem peticionamento). |
| Planejar — plano estruturado | `9db7cca`, `efa2ca4`, `43ae177` | Serviço/rotas + encaixe na elaboração + UI (botão + modal). |
| Leitura robusta de encoding | `491c5a5` | UTF-8 / CP1252 / Latin-1. |

Os hashes valem para esta publicação; após um rebase eles mudam — confira com
`git log --oneline` no branch `feature/pje-integracao`.

## Segurança

Nenhuma credencial é versionada. `.env`, sessão do PJe (`.pje_session/`),
configurações locais e dados de assistidos ficam fora do Git (ver `.gitignore`).
Copie `.env.example` para `.env` e preencha com os seus acessos.
