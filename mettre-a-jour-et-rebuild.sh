#!/usr/bin/env bash
# A executer depuis un terminal WSL (ou Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")"

echo "============================================"
echo "  Plateforme Manager - Mise a jour"
echo "============================================"
echo

if ! command -v git >/dev/null 2>&1; then
    echo "[ERREUR] Git n'est pas installe dans cette distribution WSL."
    echo "Installez-le avec : sudo apt update && sudo apt install -y git"
    exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
    echo "[ERREUR] Docker n'est pas installe ou pas dans le PATH de cette distribution WSL."
    echo "Voir : https://docs.docker.com/desktop/wsl/"
    exit 1
fi

echo "Recuperation des dernieres modifications de la branche courante..."
echo
git pull

echo
echo "Reconstruction de l'image et redemarrage des conteneurs..."
echo
docker compose up -d --build

echo
echo "Mise a jour terminee. L'application est disponible sur http://localhost:8000/"
