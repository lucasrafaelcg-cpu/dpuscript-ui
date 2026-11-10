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

## Trabalhar em duas máquinas (casa e DPU), por pen drive

Os PAJs **não vão para nuvem nenhuma**, nem para o OneDrive institucional: ali
trafegam dados pessoais e de saúde dos assistidos. O transporte é físico.

**Em casa, depois de sincronizar o SISDPU:**

```bash
python ferramentas/exportar_pajs.py --saida E:\
```

Gera `PAJs-AAAAMMDD-HHMM.zip` com os PAJs tocados **desde a última
exportação** — a data fica guardada, então não é preciso lembrar. Sem marca
anterior, usa as últimas 24 horas. Outros cortes: `--desde 2026-11-01` ou
`--tudo`. Para um pacote bem menor, sem os PDFs: `--sem-anexos`.

**Na DPU:**

```bash
python ferramentas/importar_pajs.py E:\PAJs-20261110-1930.zip
```

Depois, reinicie o painel para ele reler a pasta.

### O que o importador garante

**Nunca apaga, nunca sobrescreve coisa mais nova.** A comparação é por data de
modificação, arquivo a arquivo. Se você mexeu no mesmo PAJ dos dois lados, o
arquivo local mais novo fica e o caso é listado no fim, para você decidir — o
pacote continua no pen drive se quiser comparar.

**Confere a integridade.** Cada arquivo carrega o SHA-256 no manifesto, e nada
é gravado sem bater. Pen drive é onde arquivo corrompe calado.

**É idempotente.** Importar o mesmo pacote duas vezes não mexe em nada na
segunda — testado: 1.773 arquivos, zero alterações.

**Preserva as datas.** O `zipfile` do Python não restaura data de modificação
na extração, e sem isso tudo chegaria parecendo recém-criado — inclusive o
`SITUACAO.md`, cuja data o painel usa para medir se a análise está atrasada.
O importador devolve a data gravada no próprio zip.

**Leva o estado do painel.** `.concluidos.json`, `.diligencias.json` e
`.situacao_falhas.json` viajam e são **mesclados**, não trocados: entram os
registros que faltam, e item já marcado como anexado não volta a pendente.

**Não leva credencial.** `.env`, `.credentials.json`, chaves e certificados
ficam de fora por lista explícita, conferida nome a nome antes de fechar o zip.

### Tamanho

Com os anexos, um dia de trabalho dá algo entre algumas dezenas e ~300 MB (no
teste, 46 PAJs deram 279 MB). Com `--sem-anexos`, cai para poucos megabytes —
viajam metadata, análises, despachos, peças e o texto extraído dos anexos, mas
não os PDFs originais.

## O que não está aqui, de propósito

- `.env` e `.credentials.json` — são de cada máquina.
- `PAJs/`, `logs/` e `_versoes/` — dados de trabalho e descartes.
- `config-global/memory/honorarios-dpu-fundo-aparelhamento.md` — traz a conta
  institucional do Fundo de Aparelhamento. Fica só na máquina; para versionar,
  tire a linha correspondente do `.gitignore` e faça o commit.
