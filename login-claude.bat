@echo off
setlocal enabledelayedexpansion
title Login do Claude CLI - painel DPU

rem ============================================================
rem  Autentica o Claude CLI que o PAINEL usa.
rem
rem  NAO execute como Administrador: o painel roda sem elevacao.
rem
rem  Uso:
rem    login-claude.bat           -> LOGIN (grava a credencial)  <== normal
rem    login-claude.bat status    -> so mostra o estado
rem    login-claude.bat token     -> gera TOKEN de longa duracao
rem
rem  Diferenca importante:
rem    "auth login"   grava a credencial em disco. E' o que resolve.
rem    "setup-token"  NAO grava nada: ele IMPRIME um token que precisa ser
rem                   salvo no .env do painel (CLAUDE_CODE_OAUTH_TOKEN=...).
rem ============================================================

set "CLAUDE_BIN="

rem --- 1) Claude Desktop (MSIX): e' a instalacao mais atualizada -----------
for /d %%P in ("%LOCALAPPDATA%\Packages\Claude_*") do (
    if exist "%%~P\LocalCache\Roaming\Claude\claude-code" (
        for /f "delims=" %%V in ('dir /b /ad /o-n "%%~P\LocalCache\Roaming\Claude\claude-code" 2^>nul') do (
            if not defined CLAUDE_BIN if exist "%%~P\LocalCache\Roaming\Claude\claude-code\%%V\claude.exe" (
                set "CLAUDE_BIN=%%~P\LocalCache\Roaming\Claude\claude-code\%%V\claude.exe"
            )
        )
    )
)

rem --- 2) instalador npm ---------------------------------------------------
for %%C in (
    "%APPDATA%\npm\claude.CMD"
    "%USERPROFILE%\AppData\Roaming\npm\claude.CMD"
) do (
    if not defined CLAUDE_BIN if exist "%%~C" set "CLAUDE_BIN=%%~C"
)

rem --- 3) instalador nativo ------------------------------------------------
if not defined CLAUDE_BIN (
    if exist "%USERPROFILE%\.local\bin\claude.exe" set "CLAUDE_BIN=%USERPROFILE%\.local\bin\claude.exe"
)

rem --- 4) ultimo recurso: PATH --------------------------------------------
if not defined CLAUDE_BIN (
    for /f "delims=" %%I in ('where claude 2^>nul') do (
        if not defined CLAUDE_BIN set "CLAUDE_BIN=%%I"
    )
)

if not defined CLAUDE_BIN (
    echo [ERRO] Nao encontrei o executavel do Claude CLI. Procurei em:
    echo    %LOCALAPPDATA%\Packages\Claude_*\...\claude-code\^<versao^>\claude.exe
    echo    %APPDATA%\npm\claude.CMD
    echo    %USERPROFILE%\.local\bin\claude.exe
    echo    e no PATH desta janela.
    echo.
    echo Se a janela abriu como ADMINISTRADOR, feche e abra SEM elevacao.
    echo.
    pause
    exit /b 1
)

echo Executavel: %CLAUDE_BIN%
echo.
echo === Estado atual ===
call "%CLAUDE_BIN%" auth status
echo.

if /i "%~1"=="status" (
    echo modo status - nada foi alterado
    pause
    exit /b 0
)

if /i "%~1"=="token" goto :fazer_token

rem ---------------- LOGIN (grava credencial) ------------------------------
echo === LOGIN ===
echo Vai abrir o navegador. Conclua e volte para esta janela.
echo.
call "%CLAUDE_BIN%" auth login
echo.
echo === Resultado ===
call "%CLAUDE_BIN%" auth status
echo.
echo Se aparecer "loggedIn": true, FECHE E REABRA o painel pelo atalho
echo "Versao Tadeu".
echo.
echo Se continuar "false", rode:  login-claude.bat token
echo.
pause
exit /b 0

rem ---------------- TOKEN de longa duracao --------------------------------
:fazer_token
echo === TOKEN DE LONGA DURACAO ===
echo ATENCAO: este comando NAO grava a credencial. Ele IMPRIME um token
echo abaixo (comeca com sk-ant-oat...). COPIE esse token e cole no arquivo
echo .env do painel, numa linha assim:
echo.
echo     CLAUDE_CODE_OAUTH_TOKEN=cole-o-token-aqui
echo.
echo O arquivo .env fica em: %~dp0.env
echo Depois feche e reabra o painel.
echo.
pause
call "%CLAUDE_BIN%" setup-token
echo.
echo Copie o token acima e salve no .env conforme instruido.
echo.
pause
exit /b 0
