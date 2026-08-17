@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Plateforme Manager - Demarrage
echo ============================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Docker n'est pas installe ou n'est pas dans le PATH.
    echo Installez Docker Desktop : https://www.docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Docker Desktop ne semble pas demarre.
    echo Lancez Docker Desktop puis reessayez.
    echo.
    pause
    exit /b 1
)

echo Demarrage des conteneurs (construction de l'image si necessaire, cela peut prendre quelques minutes la premiere fois)...
echo.
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo [ERREUR] Le demarrage a echoue. Voir les messages ci-dessus.
    echo.
    pause
    exit /b 1
)

echo.
echo Attente du demarrage de l'application...
timeout /t 5 /nobreak >nul

echo Ouverture du navigateur...
start "" http://localhost:8000/

echo.
echo Plateforme Manager est disponible sur http://localhost:8000/
echo Cette fenetre peut etre fermee.
echo.
pause
