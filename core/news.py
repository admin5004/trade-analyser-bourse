import feedparser
import urllib.parse
import logging
from datetime import datetime

# Import de notre nouveau module
from core.social_intelligence import fetch_official_social_news, load_social_config # Import de load_social_config

logger = logging.getLogger("TradingEngine.News")

def fetch_google_finance_news(symbol, name=None):
    """
    Récupère les actualités via le flux RSS de Google News.
    C'est gratuit, sans clé API et supporte bien les entreprises françaises.
    """
    query = name if name else symbol
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}+bourse&hl=fr&gl=FR&ceid=FR:fr"
    
    news_items = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:8]:
            title = getattr(entry, 'title', None)
            link = getattr(entry, 'link', None)
            if not title or not link or title.lower() == 'none':
                continue
                
            news_items.append({
                'title': title,
                'link': link,
                'publisher': entry.source.get('title', 'Google News'),
                'published': entry.published if hasattr(entry, 'published') else 'N/A'
            })
    except Exception as e:
        logger.error(f"Error fetching Google News for {symbol}: {e}")
        
    return news_items

def get_combined_news(ticker_obj, symbol, name=None):
    """Combine les news de yfinance, Google News et les réseaux sociaux officiels."""
    combined = []
    
    # 1. News yfinance
    try:
        yf_news = ticker_obj.news
        for n in yf_news[:5]:
            title = n.get('title')
            link = n.get('link')
            if not title or not link or title.lower() == 'none':
                continue
                
            combined.append({
                'title': title,
                'link': link,
                'publisher': n.get('publisher', 'Yahoo Finance'),
                'published': datetime.fromtimestamp(n.get('providerPublishTime')).strftime('%d/%m/%Y %H:%M') if n.get('providerPublishTime') else 'N/A'
            })
    except: pass
    
    # 2. News Google (en français)
    google_news = fetch_google_finance_news(symbol, name)
    combined.extend(google_news)
    
    # 3. News des réseaux sociaux officiels (dynamique via social_config.json)
    social_config = load_social_config()
    company_data = social_config.get(symbol)
    
    if company_data:
        official_social_news, _ = fetch_official_social_news(symbol)
        combined.extend(official_social_news)
    else:
        logger.warning(f"Aucune configuration sociale trouvée pour le symbole {symbol}. Les actualités sociales officielles ne seront pas incluses.")
    
    return combined
