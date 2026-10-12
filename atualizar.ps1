# Atualiza esta instalacao do dpuscript-ui a partir do GitHub.
#
# Puxa o repositorio, espelha as skills na pasta de trabalho, repoe os
# arquivos globais do Claude e reinicia o painel. Substitui o pacote zip:
# roda quantas vezes quiser, so' aplica o que mudou.
#
# Uso:  .\atualizar.ps1            (pergunta antes de tocar em ~/.claude)
#       .\atualizar.ps1 -Tudo      (aplica tambem os globais, sem perguntar)
#       .\atualizar.ps1 -Simular   (mostra o que faria, sem escrever nada)

param(
    [switch]$Tudo,
    [switch]$Simular
)

$ErrorActionPreference = 'Stop'
$raiz = $PSScriptRoot
Set-Location $raiz

function Passo($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Ok($t)    { Write-Host "   $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   $t" -ForegroundColor Yellow }

# --- 1. Mudanca local pendente? -------------------------------------------
# Puxar por cima de arquivo editado aqui perderia a edicao. Melhor parar e
# deixar a decisao com quem editou.
Passo 'Conferindo mudancas locais'
$sujo = git status --porcelain
if ($sujo) {
    Aviso 'Ha arquivos modificados nesta maquina:'
    $sujo -split "`n" | Select-Object -First 15 | ForEach-Object { Write-Host "     $_" }
    Aviso 'Guarde (git stash) ou descarte antes de atualizar. Nada foi feito.'
    exit 1
}
Ok 'arvore limpa'

# --- 2. Puxar ---------------------------------------------------------------
Passo 'Puxando do GitHub'
$antes = git rev-parse HEAD
if ($Simular) {
    git fetch --quiet
    $novos = git log --oneline HEAD..'@{u}'
    if ($novos) { Write-Host $novos } else { Ok 'ja esta atualizado' }
    Aviso 'Simulacao: nada foi escrito.'
    exit 0
}
git pull --ff-only
$depois = git rev-parse HEAD
if ($antes -eq $depois) {
    Ok 'ja estava atualizado'
} else {
    Ok "atualizado: $($antes.Substring(0,7)) -> $($depois.Substring(0,7))"
    git log --oneline "$antes..$depois" | ForEach-Object { Write-Host "     $_" }
}

# --- 3. Dependencias --------------------------------------------------------
# So' reinstala quando o requirements.txt mudou de verdade.
if ($antes -ne $depois) {
    $mudou = git diff --name-only $antes $depois | Select-String 'requirements.txt'
    if ($mudou) {
        Passo 'requirements.txt mudou — instalando'
        & "$raiz\.venv\Scripts\python.exe" -m pip install -q -r requirements.txt
        Ok 'dependencias atualizadas'
    }
}

# --- 4. Espelhar as skills na pasta de trabalho -----------------------------
# A skill vive em dois lugares: aqui e no cwd do Claude CLI. Se divergirem, a
# peca sai formatada de um jeito pelo painel e de outro pelo chat.
Passo 'Espelhando as skills na pasta de trabalho'
$oficio = $null
$envFile = Join-Path $raiz '.env'
if (Test-Path $envFile) {
    $linha = Select-String -Path $envFile -Pattern '^\s*OFICIO_GERAL\s*=\s*(.+)$' |
             Select-Object -First 1
    if ($linha) { $oficio = $linha.Matches[0].Groups[1].Value.Trim().Trim('"') }
}
if (-not $oficio) { $oficio = Join-Path $env:USERPROFILE 'Desktop\Ofício Geral' }

if (Test-Path $oficio) {
    $destSkills = Join-Path $oficio '.claude\skills'
    New-Item -ItemType Directory -Force $destSkills | Out-Null
    foreach ($s in Get-ChildItem "$raiz\skills" -Directory) {
        if ($s.Name -eq '__pycache__') { continue }
        Copy-Item $s.FullName $destSkills -Recurse -Force
        Ok "skill $($s.Name) -> $destSkills"
    }
} else {
    Aviso "pasta de trabalho nao encontrada: $oficio"
    Aviso 'ajuste OFICIO_GERAL no .env e rode de novo'
}

# --- 5. Arquivos globais do Claude -----------------------------------------
# CLAUDE.md, manual de redacao e memorias. Sao de maquina, nao de projeto:
# so' sao tocados com confirmacao, porque podem ter ajuste local.
Passo 'Arquivos globais do Claude (~/.claude)'
$globalDir = Join-Path $env:USERPROFILE '.claude'
$pendentes = @()
foreach ($f in Get-ChildItem "$raiz\config-global" -Recurse -File) {
    $rel = $f.FullName.Substring("$raiz\config-global".Length).TrimStart('\')
    if ($rel -like 'memory\*') {
        $proj = Get-ChildItem (Join-Path $globalDir 'projects') -Directory -ErrorAction SilentlyContinue |
                Where-Object { Test-Path (Join-Path $_.FullName 'memory') } |
                Select-Object -First 1
        if (-not $proj) { continue }
        $alvo = Join-Path $proj.FullName ('memory\' + (Split-Path $rel -Leaf))
    } else {
        $alvo = Join-Path $globalDir $rel
    }
    $difere = $true
    if (Test-Path $alvo) {
        $difere = (Get-FileHash $f.FullName).Hash -ne (Get-FileHash $alvo).Hash
    }
    if ($difere) { $pendentes += [pscustomobject]@{ De = $f.FullName; Para = $alvo; Rel = $rel } }
}

if (-not $pendentes) {
    Ok 'nada a mudar'
} else {
    Write-Host "   $($pendentes.Count) arquivo(s) diferente(s):"
    $pendentes | ForEach-Object { Write-Host "     $($_.Rel)" }
    $aplicar = $Tudo
    if (-not $aplicar) {
        $r = Read-Host '   Sobrescrever esses arquivos globais? (s/N)'
        $aplicar = ($r -eq 's' -or $r -eq 'S')
    }
    if ($aplicar) {
        $bkp = Join-Path $globalDir ('_backup-' + (Get-Date -Format 'yyyy-MM-dd-HHmm'))
        foreach ($p in $pendentes) {
            if (Test-Path $p.Para) {
                $dBkp = Join-Path $bkp $p.Rel
                New-Item -ItemType Directory -Force (Split-Path $dBkp) | Out-Null
                Copy-Item $p.Para $dBkp -Force
            }
            New-Item -ItemType Directory -Force (Split-Path $p.Para) | Out-Null
            Copy-Item $p.De $p.Para -Force
        }
        Ok "aplicados; versao anterior em $bkp"
    } else {
        Aviso 'mantidos como estao'
    }
}

# --- 6. Reiniciar o painel --------------------------------------------------
Passo 'Reiniciando o painel'
$pids = (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue).OwningProcess
if ($pids) {
    $pids | Sort-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force }
    Start-Sleep -Seconds 2
    Ok 'painel anterior encerrado'
}
Start-Process -WindowStyle Hidden -FilePath "$raiz\.venv\Scripts\python.exe" `
    -ArgumentList '-m', 'uvicorn', 'app:app', '--port', '8001'
Start-Sleep -Seconds 3
try {
    Invoke-WebRequest 'http://127.0.0.1:8001/' -UseBasicParsing -TimeoutSec 30 | Out-Null
    Ok 'painel no ar em http://127.0.0.1:8001'
} catch {
    Aviso 'o painel nao respondeu a tempo — abra e confira'
}

Write-Host "`nAtualizacao concluida." -ForegroundColor Green
