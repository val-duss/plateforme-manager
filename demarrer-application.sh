#!/usr/bin/env bash
# A executer depuis un terminal WSL (ou Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "  Plateforme Manager - Demarrage"
echo "============================================"
echo

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERREUR] Docker n'est pas installe ou pas dans le PATH de cette distribution WSL."
    echo "Voir : https://docs.docker.com/desktop/wsl/ (integration Docker Desktop <-> WSL)"
    echo "ou installez Docker directement dans WSL (docker.io / docker-ce)."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "[ERREUR] Le demon Docker n'est pas accessible."
    echo "Si vous utilisez Docker Desktop : verifiez que l'integration WSL est activee"
    echo "(Settings > Resources > WSL Integration) et que Docker Desktop est lance."
    exit 1
fi

echo "Demarrage des conteneurs (construction de l'image si necessaire, cela peut"
echo "prendre quelques minutes la premiere fois)..."
echo
docker compose up -d --build

echo
echo "Attente du demarrage de l'application..."
sleep 5

URL="http://localhost:8000/"
echo "Ouverture du navigateur ($URL)..."
if command -v wslview >/dev/null 2>&1; then
    wslview "$URL" >/dev/null 2>&1 || true
elif command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "$URL" >/dev/null 2>&1 || true
elif command -v explorer.exe >/dev/null 2>&1; then
    explorer.exe "$URL" >/dev/null 2>&1 || true
else
    echo "Ouvrez manuellement l'URL ci-dessus dans votre navigateur."
fi

echo
echo "Plateforme Manager est disponible sur $URL"
