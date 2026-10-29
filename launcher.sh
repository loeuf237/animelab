#!/usr/bin/env bash
# Démarre le launcher de bureau depuis les sources, quel que soit le dossier courant.
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$PROJECT_DIR"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    cat <<'HELP'
Usage : ./launcher.sh [options du launcher]

Sans option : ouvre la fenêtre de configuration ; cliquer sur Launch pour démarrer.
  --admin                 Rouvrir la configuration
  --launch --browser      Démarrer directement dans le navigateur
  --status                Afficher l'état du serveur de bureau
  --stop                  Arrêter le serveur de bureau
  --launcher-self-test    Vérifier les onglets du launcher, puis fermer

Prérequis : uv 0.13.1. Node.js/npm sont nécessaires si l'interface n'est pas compilée.
Les dépendances Python de bureau sont installées par uv si nécessaire.
HELP
    exit 0
fi

UV_BIN="$(command -v uv || true)"
if [[ -z "$UV_BIN" && -x "${HOME}/.local/bin/uv" ]]; then
    UV_BIN="${HOME}/.local/bin/uv"
fi
if [[ -z "$UV_BIN" ]]; then
    echo "Erreur : uv est introuvable. Installation : https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

if [[ ! -f frontend/dist/index.html ]]; then
    if ! command -v npm >/dev/null 2>&1; then
        echo "Erreur : l'interface doit être compilée. Installer Node.js 22 (22.13+) et npm, puis relancer ce script." >&2
        exit 1
    fi
    echo "Compilation de l'interface…"
    (
        cd frontend
        if [[ ! -d node_modules ]]; then
            npm ci
        fi
        npm run build
    )
fi

exec "$UV_BIN" run --locked --group desktop python desktop.py "$@"
