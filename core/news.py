import feedparser
import urllib.parse
import logging
from datetime import datetime

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
        for entry in feed.entries[:8]:  # On prend les 8 premières news
            news_items.append({
                'title': entry.title,
                'link': entry.link,
                'publisher': entry.source.get('title', 'Google News'),
                'published': entry.published if hasattr(entry, 'published') else 'N/A'
            })
    except Exception as e:
        logger.error(f"Error fetching Google News for {symbol}: {e}")
        
    return news_items

def get_combined_news(ticker_obj, symbol, name=None):
    """Combine les news de yfinance et de Google News."""
    combined = []
    
    # 1. News yfinance (souvent en anglais)
    try:
        yf_news = ticker_obj.news
        for n in yf_news[:5]:
            combined.append({
                'title': n.get('title'),
                'link': n.get('link'),
                'publisher': n.get('publisher', 'Yahoo Finance'),
                'published': datetime.fromtimestamp(n.get('providerPublishTime')).strftime('%d/%m/%Y %H:%M') if n.get('providerPublishTime') else 'N/A'
            })
    except: pass
    
    # 2. News Google (en français)
    google_news = fetch_google_finance_news(symbol, name)
    combined.extend(google_news)
    
    return combined
