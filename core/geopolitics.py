import feedparser
import urllib.parse
import logging
import socket
from datetime import datetime

# Sécurité : Timeout de 10 secondes pour éviter les blocages réseau
socket.setdefaulttimeout(10)

logger = logging.getLogger("TradingEngine.Geopolitics")

# Thématiques et entités à surveiller
GEOPOLITICAL_ENTITIES = [
    "BCE", "FED", "OPEP", "OTAN", "UE", "G7", "FMI"
]

GEOPOLITICAL_THEMES = [
    "Inflation", "Taux d'intérêt", "Prix de l'énergie", "Guerre", 
    "Sanctions économiques", "Crise énergétique", "Tensions commerciales"
]

# Lexique de risque géopolitique et systémique (Pondération de -1.0 à +1.0)
GEOPOL_LEXICON = {
    # Risques Extrêmes (-1.0 à -0.8)
    "krach": -1.0, "effondrement": -0.9, "récession": -0.9, "invasion": -0.9,
    "nucléaire": -0.9, "pandémie": -0.8, "faillite": -0.8, "conflit": -0.8,
    "embargo": -0.8, "panique": -0.8, "risque systémique": -0.8,
    
    # Risques Modérés à Forts (-0.7 à -0.4)
    "sanction": -0.7, "pénurie": -0.7, "stagflation": -0.7, "défaut": -0.7,
    "escalade": -0.7, "confinement": -0.6, "menace": -0.6, "instabilité": -0.6,
    "hausse des taux": -0.6, "inflation": -0.4, "tension": -0.5, "blocage": -0.5,
    "protectionnisme": -0.4, "cyberguerre": -0.5,
    
    # Signaux Positifs (0.4 à 1.0)
    "accord": 0.7, "apaisement": 0.8, "stabilité": 0.6, "coopération": 0.7,
    "reprise": 0.6, "relance": 0.7, "baisse des prix": 0.5, "croissance mondiale": 0.6,
    "assouplissement": 0.5, "pivot": 0.5
}

def fetch_geopolitical_news():
    """Récupère les actualités macro et géopolitiques globales."""
    query = "géopolitique économie marchés krach guerre récession"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=fr&gl=FR&ceid=FR:fr"
    
    news_items = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:15]: # On prend un peu plus d'articles pour une meilleure couverture
            news_items.append({
                'title': entry.title,
                'link': entry.link,
                'published': entry.published if hasattr(entry, 'published') else 'N/A'
            })
    except Exception as e:
        logger.error(f"Error fetching geopolitical news: {e}")
    return news_items

def analyze_global_risk():
    """Analyse les news globales et retourne un score de risque (0-100) et un résumé."""
    news = fetch_geopolitical_news()
    if not news:
        return 50, "Données géopolitiques indisponibles", []

    impacts = []
    top_events = []

    for item in news:
        title = item['title'].lower()
        item_score = 0
        found_keywords = []

        # 1. Analyse par lexique spécifique
        for word, weight in GEOPOL_LEXICON.items():
            if word in title:
                item_score += weight
                found_keywords.append(word)
        
        # 2. Bonus de détection d'entités/thèmes
        for theme in GEOPOLITICAL_THEMES:
            if theme.lower() in title:
                found_keywords.append(theme)
                if item_score == 0: item_score = -0.1 

        if found_keywords:
            impacts.append(item_score)
            top_events.append(item['title'])

    if not impacts:
        return 50, "Aucun signal géopolitique majeur détecté.", []

    # Calcul du score hybride : 50% Moyenne / 50% Pire Scénario
    # Cela permet de rester sensible aux chocs brutaux sans ignorer le contexte global.
    avg_impact = sum(impacts) / len(impacts)
    worst_impact = min(impacts)
    
    final_impact = (avg_impact * 0.5) + (worst_impact * 0.5)
    
    # Normalisation de 0 à 100
    risk_score = 50 + (final_impact * 50)
    risk_score = max(0, min(100, risk_score))

    # Génération du verdict
    if risk_score < 25:
        verdict = "ALERTE ROUGE : Risque systémique ou géopolitique EXTRÊME."
    elif risk_score < 40:
        verdict = "Risque Géopolitique ÉLEVÉ : Forte volatilité à prévoir."
    elif risk_score < 50:
        verdict = "Risque Modéré : Le contexte macroéconomique est fragile."
    elif risk_score > 65:
        verdict = "Contexte Favorable : Signes d'apaisement ou de relance."
    else:
        verdict = "Contexte Stable : Pas de choc géopolitique majeur."

    return int(risk_score), verdict, top_events[:5]
