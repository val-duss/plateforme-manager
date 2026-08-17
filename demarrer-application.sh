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

# Ouvre l'application dans sa propre fenetre (mode "app" : sans barre d'adresse,
# ni onglets, ni autres elements de navigateur), plutot que dans un onglet classique.
# Essaye Edge puis Chrome en mode application, avec repli sur le navigateur par defaut.
open_app_window() {
    local url="$1"

    if command -v cmd.exe >/dev/null 2>&1; then
        if cmd.exe /c start msedge --app="$url" >/dev/null 2>&1; then return 0; fi
        if cmd.exe /c start chrome --app="$url" >/dev/null 2>&1; then return 0; fi
        if cmd.exe /c start "" "$url" >/dev/null 2>&1; then return 0; fi
    fi

    for browser in google-chrome chromium chromium-browser microsoft-edge; do
        if command -v "$browser" >/dev/null 2>&1; then
            "$browser" --app="$url" >/dev/null 2>&1 &
            disown
            return 0
        fi
    done

    if command -v wslview >/dev/null 2>&1 && wslview "$url" >/dev/null 2>&1; then return 0; fi
    if command -v xdg-open >/dev/null 2>&1 && xdg-open "$url" >/dev/null 2>&1; then return 0; fi
    if command -v open >/dev/null 2>&1 && open "$url" >/dev/null 2>&1; then return 0; fi

    return 1
}

echo "Ouverture de l'application dans sa propre fenetre ($URL)..."
if open_app_window "$URL"; then
    echo "Fenetre ouverte."
else
    echo "Impossible d'ouvrir automatiquement une fenetre. Ouvrez manuellement : $URL"
fi

echo
echo "Plateforme Manager est disponible sur $URL"
