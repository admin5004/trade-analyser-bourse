#!/bin/bash
# Script de déploiement automatique pour Render
DEPLOY_HOOK_URL=$1

if [ -z "$DEPLOY_HOOK_URL" ]; then
    echo "Erreur : URL de Deploy Hook manquante."
    exit 1
fi

echo "🚀 Lancement du déploiement sur Render..."
curl -X POST "$DEPLOY_HOOK_URL"
echo -e "
✅ Requête de déploiement envoyée !"
