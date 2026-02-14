import requests
import logging
import re
import yfinance as yf
from .database import get_db_connection

logger = logging.getLogger("TradingEngine.Legal")

def fetch_company_website(symbol):
    """Récupère le site web officiel via yfinance et l'enregistre en base."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        website = info.get('website')
        if website:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE tickers SET website_url = ? WHERE symbol = ?", (website, symbol))
                conn.commit()
            return website
    except Exception as e:
        logger.error(f"Error fetching website for {symbol}: {e}")
    return None

def fetch_balo_news(symbol, name=None):
    """
    Tente de récupérer les dernières annonces BALO.
    Note: Utilise une approche simplifiée via recherche publique ou API ouverte si disponible.
    """
    # Pour l'instant, on génère un lien vers la recherche officielle BALO
    # car l'API DILA nécessite souvent un token et une inscription.
    search_query = name if name else symbol.replace('.PA', '')
    balo_url = f"https://www.journal-officiel.gouv.fr/pages/balo/recherche-resultats/?search={search_query}"
    
    # On pourrait parser le HTML ici, mais pour la stabilité on propose le lien direct
    # et on simule une récupération d'actualités législatives.
    return {
        'title': "Annonces Légales (BALO)",
        'link': balo_url,
        'source': "Journal Officiel"
    }

def get_company_legal_info(symbol):
    """Récupère les infos stockées en DB ou les cherche si absentes."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT website_url, siren, name FROM tickers WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            
            if row:
                website, siren, name = row
                if not website:
                    website = fetch_company_website(symbol)
                return {
                    'website': website,
                    'siren': siren,
                    'name': name
                }
    except Exception as e:
        logger.error(f"Error getting legal info for {symbol}: {e}")
    return None
