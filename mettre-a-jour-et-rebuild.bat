@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   Plateforme Manager - Mise a jour
echo ============================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Git n'est pas installe ou n'est pas dans le PATH.
    echo.
    pause
    exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Docker n'est pas installe ou n'est pas dans le PATH.
    echo Installez Docker Desktop : https://www.docker.com/products/docker-desktop
    echo.
    pause
    exit /b 1
)

echo Recuperation des dernieres modifications de la branche courante...
echo.
git pull
if errorlevel 1 (
    echo.
    echo [ERREUR] La mise a jour Git a echoue. Voir les messages ci-dessus.
    echo ^(en cas de modifications locales en conflit, sauvegardez-les avant de reessayer^)
    echo.
    pause
    exit /b 1
)

echo.
echo Reconstruction de l'image et redemarrage des conteneurs...
echo.
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo [ERREUR] La reconstruction a echoue. Voir les messages ci-dessus.
    echo.
    pause
    exit /b 1
)

echo.
echo Mise a jour terminee. L'application est disponible sur http://localhost:8000/
echo.
pause
