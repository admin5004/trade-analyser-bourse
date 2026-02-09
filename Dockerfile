# Utiliser une image Python légère
FROM python:3.12-slim

# Définir le répertoire de travail
WORKDIR /app

# Copier les fichiers de dépendances
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir -r requirements.txt

# Installer les données nécessaires à TextBlob
RUN python -m textblob.download_corpora

# Copier tout le code du projet
COPY . .

# Exposer le port que Cloud Run utilise (8080 par défaut)
ENV PORT 8080

# Lancer l'application avec gunicorn (serveur de production)
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app
