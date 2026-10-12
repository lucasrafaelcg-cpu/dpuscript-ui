# Instalar e manter atualizado

Este repositório é privado e guarda o painel, as skills e os arquivos globais
do Claude. **Nenhum dado de assistido entra aqui**: os PAJs vivem na pasta de
trabalho (`Ofício Geral`), que está no `.gitignore`, assim como `.env`,
`logs/` e `.venv/`.

## Primeira vez numa máquina nova

Pré-requisitos: Python 3.12+, Git, e o pacote de instalação completo já
aplicado uma vez (é ele que cria o `.venv` e a pasta de trabalho).

```powershell
git clone https://github.com/lucasrafaelcg-cpu/dpuscript-ui.git
cd dpuscript-ui
Copy-Item .env.example .env     # e preencha OFICIO_GERAL e as credenciais
```

O `.env` é de cada máquina e nunca sobe para o repositório.

## Depois disso, toda atualização

Duplo clique em **`atualizar.bat`**, ou:

```powershell
.\atualizar.ps1
```

Ele faz, nesta ordem:

1. **Para se houver mudança local pendente.** Puxar por cima de arquivo
   editado nesta máquina perderia a edição, então ele mostra o que está
   modificado e não escreve nada.
2. Puxa do GitHub e lista os commits que chegaram.
3. Reinstala dependências **só se** o `requirements.txt` tiver mudado.
4. Espelha `skills/` na pasta de trabalho (`<Ofício Geral>\.claude\skills\`).
   As duas cópias precisam ficar idênticas: se divergirem, a peça sai
   formatada de um jeito pelo painel e de outro pelo chat.
5. Repõe os arquivos globais do Claude (`config-global/` → `~/.claude/`):
   `CLAUDE.md`, manual de redação e memórias. **Pergunta antes** e guarda a
   versão anterior em `~/.claude/_backup-<data>/`, porque esses arquivos podem
   ter ajuste local.
6. Reinicia o painel e confere que ele respondeu em `http://127.0.0.1:8001`.

Opções: `-Tudo` aplica os globais sem perguntar; `-Simular` mostra o que faria
sem escrever nada.

## Quando esta máquina é a que mudou

```powershell
git add -A
git commit -m "feat: descreva a mudança"
git push
```

A outra máquina pega na próxima vez que rodar `atualizar.bat`.

## O que não está aqui, de propósito

- `.env` e `.credentials.json` — são de cada máquina.
- `PAJs/`, `logs/` e `_versoes/` — dados de trabalho e descartes.
- `config-global/memory/honorarios-dpu-fundo-aparelhamento.md` — traz a conta
  institucional do Fundo de Aparelhamento. Fica só na máquina; para versionar,
  tire a linha correspondente do `.gitignore` e faça o commit.
