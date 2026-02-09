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

# Lancer l'application avec gunicorn
CMD gunicorn --bind 0.0.0.0:$PORT app:app
