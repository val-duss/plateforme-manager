@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Plateforme Manager - Demarrage (via WSL)
echo ============================================
echo.

where wsl >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] WSL n'est pas installe ou n'est pas dans le PATH.
    echo Voir : https://learn.microsoft.com/windows/wsl/install
    echo.
    pause
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

set "WSL_PATH="
for /f "usebackq delims=" %%p in (`wsl wslpath -a "%SCRIPT_DIR%"`) do set "WSL_PATH=%%p"

if "%WSL_PATH%"=="" (
    echo [ERREUR] Impossible de determiner le chemin WSL de ce dossier.
    echo Verifiez que WSL est bien configure ^(commande : wsl --status^).
    echo.
    pause
    exit /b 1
)

wsl bash -lc "cd '%WSL_PATH%' && ./demarrer-application.sh"
if errorlevel 1 (
    echo.
    echo [ERREUR] Le demarrage a echoue. Voir les messages ci-dessus.
    echo Vous pouvez aussi lancer le script directement depuis un terminal WSL :
    echo   ./demarrer-application.sh
    echo.
    pause
    exit /b 1
)

echo.
pause
