#!/bin/bash
# start_local.sh - Script de lancement optimisé pour Trading Analyser
cd "$(dirname "$0")"

# Chargement du venv
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Erreur : Environnement virtuel (venv) non trouvé."
    exit 1
fi

# Arrêt de l'instance précédente si elle existe
PID=$(pgrep -f "gunicorn.*app:app")
if [ ! -z "$PID" ]; then
    echo "Arrêt de l'instance précédente (PID: $PID)..."
    kill $PID
    sleep 2
fi

# Lancement avec Gunicorn (4 workers pour la stabilité et la performance)
echo "Lancement de Trading Analyser avec Gunicorn..."
nohup gunicorn --workers 4 --bind 0.0.0.0:5000 app:app --access-logfile server_access.log --error-logfile server_local.log > /dev/null 2>&1 &

echo "✅ Application démarrée sur le port 5000."
echo "Logs disponibles dans server_local.log"
