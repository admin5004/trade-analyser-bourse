import os
import random
import string
import threading
import logging
import re
from datetime import datetime
from dotenv import load_dotenv

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import yfinance as yf

# Importations de nos modules core
from core.database import init_db, get_db_connection
from core.analysis import analyze_stock, analyze_sentiment, create_stock_chart
from core.market import MARKET_STATE, market_lock, fetch_market_data_job, get_global_context
from core.legal import get_company_legal_info
from core.news import get_combined_news

# --- CONFIGURATION ---
load_dotenv()
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

CURRENCY_MAP = {
    'USD': '$',
    'EUR': '€',
    'GBP': '£',
    'JPY': '¥',
    'CHF': 'CHF',
    'CAD': 'CA$',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingApp")

app = Flask(__name__)
# On s'assure d'avoir une clé secrète pour les sessions
app.secret_key = os.environ.get("SECRET_KEY", "trading-analyzer-super-secret-key-12345")
VERSION = "4.0.0 (Modular Edition)"

# Initialisation de la DB au démarrage
init_db()

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=20), id='mkt_job')
scheduler.start()

# Lancer un premier scan immédiatement en arrière-plan sans bloquer le démarrage
threading.Thread(target=fetch_market_data_job, daemon=True).start()

# --- ROUTES ---

@app.route('/')
def ultra_home():
    if session.get('verified'): return redirect(url_for('ultra_analyze'))
    return render_template('welcome.html')

@app.route('/login', methods=['POST'])
def ultra_login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()
    
    # Mot de passe de sécurité défini dans l'environnement ou valeur par défaut
    admin_password = os.environ.get("ADMIN_PASSWORD", "Corentin2026!")
    
    if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        flash("Email invalide", "error")
        return redirect(url_for('ultra_home'))
    
    if password != admin_password:
        flash("Accès refusé : Mot de passe incorrect", "error")
        return redirect(url_for('ultra_home'))
        
    session['verified'] = True
    return redirect(url_for('ultra_analyze'))

@app.route('/api/search_tickers')
def api_search_tickers():
    query = request.args.get('query', '').upper()
    if not query: return jsonify([])
    results = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, name FROM tickers WHERE symbol LIKE ? OR name LIKE ? LIMIT 10", (f'%{query}%', f'%{query}%'))
            results = [{'symbol': row[0], 'name': row[1]} for row in cursor.fetchall()]
        
        # Si aucun résultat local, on suggère le ticker direct s'il ressemble à un ticker US
        if not results and len(query) >= 2:
            # On pourrait utiliser yf.Search ici, mais pour la rapidité on propose le ticker tel quel
            results.append({'symbol': query, 'name': 'Recherche globale...'})
    except Exception: pass
    return jsonify(results)

@app.route('/ultra_search_handler', methods=['POST'])
def ultra_search():
    query = request.form.get('query', '').strip()
    if not query: return redirect(url_for('ultra_analyze'))
    
    # Détection si c'est un ISIN (ex: FR0000120271)
    is_isin = re.match(r'^[A-Z]{2}[A-Z0-9]{9}[0-9]$', query.upper())
    
    try:
        # Recherche via yfinance
        from yfinance import Search
        s = Search(query, max_results=10)
        quotes = s.quotes
        
        if not quotes:
            # Si Yahoo ne trouve rien, on tente quand même l'analyse directe si c'est un ticker
            if not is_isin:
                return redirect(url_for('ultra_analyze', symbol=query.upper()))
            flash(f"Aucune valeur trouvée pour l'ISIN {query}", "error")
            return redirect(url_for('ultra_home'))

        # Si un seul résultat exact et c'est un ticker direct connu
        if len(quotes) == 1:
            return redirect(url_for('ultra_analyze', symbol=quotes[0]['symbol']))

        # Si plusieurs résultats, on les propose à l'utilisateur
        results = []
        for q in quotes:
            results.append({
                'symbol': q['symbol'],
                'name': q.get('shortname') or q.get('longname') or 'N/A',
                'exchange': q.get('exchange', 'N/A'),
                'type': q.get('quoteType', 'N/A')
            })
        
        return render_template('search_results.html', query=query, results=results)
            
    except Exception as e:
        logger.error(f"Global search error for {query}: {e}")
        # En cas d'erreur de l'API Search, on tente l'accès direct
        return redirect(url_for('ultra_analyze', symbol=query.upper()))

@app.route('/analyze')
def ultra_analyze():
    if not session.get('verified'): return redirect(url_for('ultra_home'))
    symbol = request.args.get('symbol', '').upper().strip()
    
    top_sectors, heatmap_data = get_global_context()
    
    if not symbol:
        return render_template('index.html', symbol="", last_close_price=None, top_sectors=top_sectors, heatmap_data=heatmap_data, version=VERSION)

    # Récupération DATA depuis le cache
    with market_lock:
        info = MARKET_STATE['tickers'].get(symbol)
        df = MARKET_STATE['dataframes'].get(symbol)

    news_list = []
    analyst_info = "N/A"
    
    # Force sync fetch if not in cache or if cache is empty skeleton
    if df is None or (info and info.get('price', 0) == 0):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y")
            news_list = ticker.news[:5] if ticker.news else []
            try:
                analyst_info = ticker.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
            except: pass
            
            if df is not None and not df.empty:
                df.columns = [col.lower() for col in df.columns]
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                info = {
                    'price': float(df['close'].iloc[-1]),
                    'change_pct': ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0,
                    'recommendation': reco, 'reason': reason, 'rsi': rsi, 'mm20': mm20, 'mm50': mm50, 'mm200': mm200,
                    'targets': {'entry': entry, 'exit': exit}, 'sector': 'Autre'
                }
        except Exception as e:
            logger.error(f"Sync fetch error for {symbol}: {e}")
    else:
        # Si on a les données du cache, on s'assure que l'analyse est faite sur le DF pour le graphique
        df.columns = [col.lower() for col in df.columns]
        analyze_stock(df)

    sentiment_score, sentiment_label = analyze_sentiment(news_list)
    top_sectors, _ = get_global_context()
    
    # Infos Légales (Site Web)
    legal_info = get_company_legal_info(symbol)
    
    # Détection Devise
    currency_code = 'EUR'
    try:
        if df is not None and not df.empty:
            ticker_obj = yf.Ticker(symbol)
            currency_code = ticker_obj.info.get('currency', 'EUR')
            # Actualités enrichies (Google News + Yahoo)
            news_list = get_combined_news(ticker_obj, symbol, legal_info['name'] if legal_info else None)
    except: pass
    currency_symbol = CURRENCY_MAP.get(currency_code, currency_code)

    context = {
        'symbol': symbol, 
        'last_close_price': info.get('price') if info else 0.001,
        'daily_change_percent': info.get('change_pct', 0) if info else 0,
        'recommendation': info.get('recommendation', 'Analyse...') if info else 'Indisponible',
        'reason': info.get('reason', 'Récupération des données en cours') if info else 'Échec de connexion API',
        'rsi_value': info.get('rsi', 50) if info else 50,
        'mm20': info.get('mm20', 0) if info else 0,
        'mm50': info.get('mm50', 0) if info else 0,
        'mm200': info.get('mm200', 0) if info else 0,
        'short_term_entry_price': f"{info['targets']['entry']:.2f}" if info and 'targets' in info else "N/A",
        'short_term_exit_price': f"{info['targets']['exit']:.2f}" if info and 'targets' in info else "N/A",
        'sector': info.get('sector', 'N/A') if info else 'N/A',
        'pe_ratio': info.get('pe') if info and info.get('pe') else None,
        'div_yield': info.get('yield') if info and info.get('yield') else None,
        'currency_symbol': currency_symbol, 
        'stock_chart_div': create_stock_chart(df, symbol) if df is not None else "",
        'top_sectors': top_sectors, 
        'heatmap_data': heatmap_data, 
        'engine_status': 'ONLINE', 
        'version': VERSION,
        'last_update': MARKET_STATE['last_update'], 
        'news': news_list, 
        'website_url': legal_info.get('website') if legal_info else None,
        'analyst_recommendation': analyst_info,
        'sentiment_score': sentiment_score, 
        'sentiment_label': sentiment_label
    }
    
    return render_template('index.html', **context)

@app.route('/status')
def ultra_status():
    with market_lock:
        return jsonify({
            'engine_running': scheduler.running, 
            'last_update': MARKET_STATE['last_update'], 
            'cached_instruments': len(MARKET_STATE['tickers']), 
            'version': VERSION
        })

if __name__ == '__main__':
    # Lancement d'un cycle initial en arrière-plan
    threading.Thread(target=fetch_market_data_job).start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False)
