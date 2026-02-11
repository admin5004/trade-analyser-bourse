import os
import sqlite3
import random
import string
import smtplib
import time
import csv
import io
import threading
import logging
import traceback
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, Response
from flask_caching import Cache
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import plotly.graph_objects as go
from textblob import TextBlob

# --- CONFIGURATION ---
load_dotenv()

# Désactiver toute tentative d'interface graphique (évite les erreurs Firefox/X11 sur Render)
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYDEVD_DISABLE_FILE_VALIDATION'] = '1'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingEngine")

app = Flask(__name__)
# Génère une clé unique au démarrage si SECRET_KEY n'est pas dans les variables d'environnement
app.secret_key = os.environ.get("SECRET_KEY", "".join(random.choices(string.ascii_letters + string.digits, k=32)))
VERSION = "3.4.0 (Stable Edition)"
DB_NAME = "users.db"

market_lock = threading.Lock()
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})

MARKET_STATE = {
    'last_update': None,
    'tickers': {},  
    'dataframes': {},
    'sectors': {},
    'esg_data': {},
    'fundamentals': {},
    'last_error': None
}

def init_db():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS tickers")
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickers (symbol TEXT PRIMARY KEY, name TEXT, sector TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS leads (email TEXT PRIMARY KEY, signup_date TEXT, marketing_consent INTEGER DEFAULT 0, ip_address TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, symbol TEXT, found INTEGER, timestamp TEXT)''')
            cac40 = [
                ('AC.PA', 'Accor', 'Consommation'), ('AI.PA', 'Air Liquide', 'Industrie'), ('AIR.PA', 'Airbus', 'Aéronautique'), ('ALO.PA', 'Alstom', 'Industrie'),
                ('MT.AS', 'ArcelorMittal', 'Matériaux'), ('CS.PA', 'AXA', 'Finance'), ('BNP.PA', 'BNP Paribas', 'Finance'), ('EN.PA', 'Bouygues', 'Industrie'),
                ('CAP.PA', 'Capgemini', 'Technologie'), ('CA.PA', 'Carrefour', 'Consommation'), ('ACA.PA', 'Crédit Agricole', 'Finance'), ('BN.PA', 'Danone', 'Consommation'),
                ('DSY.PA', 'Dassault Systèmes', 'Technologie'), ('EDEN.PA', 'Edenred', 'Finance'), ('ENGI.PA', 'Engie', 'Services Publics'), ('EL.PA', 'EssilorLuxottica', 'Santé'),
                ('ERF.PA', 'Eurofins Scientific', 'Santé'), ('RMS.PA', 'Hermès', 'Luxe'), ('KER.PA', 'Kering', 'Luxe'), ('OR.PA', "L'Oréal", 'Consommation'),
                ('LR.PA', 'Legrand', 'Industrie'), ('MC.PA', 'LVMH', 'Luxe'), ('ML.PA', 'Michelin', 'Industrie'), ('ORA.PA', 'Orange', 'Télécoms'),
                ('RI.PA', 'Pernod Ricard', 'Consommation'), ('PUB.PA', 'Publicis', 'Média'), ('RNO.PA', 'Renault', 'Industrie'), ('SAF.PA', 'Safran', 'Aéronautique'),
                ('SGO.PA', 'Saint-Gobain', 'Industrie'), ('SAN.PA', 'Sanofi', 'Santé'), ('SU.PA', 'Schneider Electric', 'Industrie'), ('GLE.PA', 'Société Générale', 'Finance'),
                ('STLAP.PA', 'Stellantis', 'Industrie'), ('STMPA.PA', 'STMicroelectronics', 'Technologie'), ('TEP.PA', 'Teleperformance', 'Industrie'), ('HO.PA', 'Thales', 'Aéronautique'),
                ('TTE.PA', 'TotalEnergies', 'Énergie'), ('URW.PA', 'Unibail-Rodamco', 'Immobilier'), ('VIE.PA', 'Veolia', 'Services Publics'), ('DG.PA', 'Vinci', 'Industrie'),
                ('AAPL', 'Apple', 'Technologie'), ('MSFT', 'Microsoft', 'Technologie'), ('GOOGL', 'Google', 'Technologie'), ('TSLA', 'Tesla', 'Automobile')
            ]
            cursor.executemany('INSERT OR IGNORE INTO tickers (symbol, name, sector) VALUES (?, ?, ?)', cac40)
            conn.commit()
    except Exception as e: logger.error(f"DB Error: {e}")

init_db()

# --- ENGINE ---

def fetch_market_data_job():
    logger.info("📡 ENGINE: Cycle started...")
    symbols_info = {}
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM tickers")
            for row in cursor.fetchall(): symbols_info[row[0]] = row[1]
    except Exception: return
    
    symbols = list(symbols_info.keys())
    temp_tickers, temp_dfs, sector_stats = {}, {}, {}
    
    # Pré-remplir avec des données par défaut pour éviter le 0
    for symbol in symbols:
        temp_tickers[symbol] = {'price': 0, 'change_pct': 0, 'sector': symbols_info.get(symbol, 'Autre'), 'vol_spike': 1.0}

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            # Utilisation de 1mo au lieu de 2y pour être plus léger au démarrage
            df = ticker.history(period="1mo", timeout=15)
            if df is None or df.empty: continue
            
            df.columns = [col.lower() for col in df.columns]
            if len(df) < 2: continue
            
            close_now = df['close'].iloc[-1]
            close_prev = df['close'].iloc[-2]
            change_pct = ((close_now - close_prev) / close_prev * 100) if close_prev != 0 else 0
            
            sector = symbols_info.get(symbol, 'Autre')
            if sector not in sector_stats: sector_stats[sector] = []
            sector_stats[sector].append(change_pct)
            
            temp_dfs[symbol] = df
            temp_tickers[symbol].update({
                'price': float(close_now),
                'change_pct': float(change_pct),
                'vol_spike': float(df['volume'].iloc[-1] / df['volume'].tail(10).mean()) if df['volume'].tail(10).mean() > 0 else 1.0
            })
            time.sleep(0.2) # Petit délai pour éviter le ban IP
        except Exception as e: 
            logger.warning(f"Error fetching {symbol}: {e}")
            continue
            
    with market_lock:
        MARKET_STATE['tickers'].update(temp_tickers)
        MARKET_STATE['dataframes'].update(temp_dfs)
        for sec, changes in sector_stats.items():
            if changes: MARKET_STATE['sectors'][sec] = sum(changes) / len(changes)
        MARKET_STATE['last_update'] = datetime.now().isoformat()
    logger.info(f"✅ ENGINE: Cycle complete. Cached: {len(MARKET_STATE['tickers'])}")

def analyze_stock(df, sector_avg_change=0):
    try:
        df.ta.sma(length=20, append=True); df.ta.sma(length=50, append=True); df.ta.sma(length=200, append=True); df.ta.rsi(length=14, append=True)
        last = df.iloc[-1]; mm200, rsi, close = last.get('SMA_200'), last.get('RSI_14', 50), last['close']
        
        # Calcul de la dynamique de volume
        vol_today = df['volume'].iloc[-1]
        vol_yesterday = df['volume'].iloc[-2] if len(df) > 1 else vol_today
        vol_ratio = vol_today / vol_yesterday if vol_yesterday > 0 else 1.0
        
        daily_change = ((close - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0
        rs = daily_change - sector_avg_change
        reco, reason = "Conserver", "Neutre"
        
        if mm200 and close > mm200:
            if rsi < 40 or rs > 1.5: reco, reason = "Achat", "Tendance haussière"
        elif mm200 and close < mm200:
            if rsi > 70 or rs < -1.5: reco, reason = "Vente", "Faiblesse relative"
            
        # Ajustement dynamique des prix en fonction du volume
        entry_coeff = 0.98
        exit_coeff = 1.05
        
        if vol_ratio > 1.2: # Volume en hausse de 20%+ : Forte conviction
            entry_coeff = 0.99 # On peut entrer un peu plus haut
            exit_coeff = 1.07 # On vise plus haut
        elif vol_ratio < 0.8: # Volume faible : Manque de conviction
            entry_coeff = 0.97 # On attend un repli plus marqué
            exit_coeff = 1.04 # Objectif plus prudent
            
        return reco, reason, float(rsi), float(last.get('SMA_20', 0)), float(last.get('SMA_50', 0)), None, float(mm200 or 0), float(close*entry_coeff), float(close*exit_coeff)
    except Exception: return "N/A", "Erreur", 50, 0, 0, None, 0, 0, 0

def create_stock_chart(df, symbol):
    try:
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'])])
        fig.update_layout(title=f'{symbol}', height=400, template='plotly_white', margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False)
        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception: return ""

def analyze_sentiment(news_list):
    if not news_list: return 0, "Neutre"
    sentiments = []
    for n in news_list:
        text = n.get('title', '')
        blob = TextBlob(text)
        sentiments.append(blob.sentiment.polarity)
    avg = sum(sentiments) / len(sentiments) if sentiments else 0
    label = "Positif" if avg > 0.1 else "Négatif" if avg < -0.1 else "Neutre"
    return avg, label

def get_global_context():
    with market_lock:
        live_tickers = dict(MARKET_STATE['tickers'])
        live_sectors = dict(MARKET_STATE['sectors'])
    
    heatmap_data = []
    # D'abord, récupérer tout de la DB
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers")
            all_db_symbols = [row[0] for row in cursor.fetchall()]
            
            # Si la DB est vide mais qu'on a des données live, on utilise le live
            if not all_db_symbols and live_tickers:
                all_db_symbols = list(live_tickers.keys())

            for s in all_db_symbols:
                # Si on a de la donnée live, on l'utilise
                if s in live_tickers:
                    change = live_tickers[s].get('change_pct', 0)
                else:
                    change = 0
                
                # Intensité basée sur 0-10% (10% = 100% de couleur)
                intensity = min(abs(change) * 10, 100)
                
                heatmap_data.append({
                    'symbol': s.replace('.PA', ''),
                    'change': change,
                    'full_symbol': s,
                    'intensity': intensity
                })
    except Exception as e:
        logger.error(f"Heatmap error: {e}")
        # Fallback sur les données live si erreur DB
        for s, info in live_tickers.items():
            heatmap_data.append({
                'symbol': s.replace('.PA', ''),
                'change': info.get('change_pct', 0),
                'full_symbol': s
            })

    sorted_sectors = sorted(live_sectors.items(), key=lambda x: x[1], reverse=True)
    top_sectors = [{'name': name, 'change': change} for name, change in sorted_sectors[:5]]
    
    return top_sectors, sorted(heatmap_data, key=lambda x: x['symbol'])

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=20), id='mkt_job')
scheduler.start()

# --- ROUTES (ULTRA UNIQUE NAMES) ---

@app.route('/ultra_search_handler', methods=['POST'])
def ultra_search():
    query = request.form.get('query', '').strip()
    if not query: return redirect(url_for('ultra_analyze'))
    return redirect(url_for('ultra_analyze', symbol=query.upper()))

@app.route('/api/search_tickers')
def api_search_tickers():
    query = request.args.get('query', '').upper()
    if not query: return jsonify([])
    
    results = []
    # Priorité à la DB pour avoir des noms complets
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, name FROM tickers WHERE symbol LIKE ? OR name LIKE ? LIMIT 10", (f'%{query}%', f'%{query}%'))
            results = [{'symbol': row[0], 'name': row[1]} for row in cursor.fetchall()]
    except Exception: pass
    
    # Si pas de DB ou vide, on check le live
    if not results:
        with market_lock:
            results = [{'symbol': s, 'name': ''} for s in MARKET_STATE['tickers'].keys() if query in s][:5]
            
    return jsonify(results)

@app.route('/')
def ultra_home():
    if session.get('verified'): return redirect(url_for('ultra_analyze'))
    return render_template('welcome.html')

@app.route('/login', methods=['POST'])
def ultra_login():
    email = request.form.get('email', '').strip().lower()
    if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        flash("Veuillez entrer une adresse email valide.", "error")
        return redirect(url_for('ultra_home'))
    try:
        with sqlite3.connect(DB_NAME) as conn:
            # Utilisation de requêtes paramétrées (sécurisé contre injection SQL)
            conn.execute('INSERT OR REPLACE INTO leads (email, signup_date, marketing_consent, ip_address) VALUES (?, ?, ?, ?)', 
                         (email, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1 if request.form.get('accept_marketing')=='on' else 0, request.remote_addr))
        session['verified'] = True
        session['pending_email'] = email
        
        # S'assurer que le moteur démarre immédiatement si vide
        with market_lock:
            needs_update = not MARKET_STATE['tickers']
        if needs_update:
            threading.Thread(target=fetch_market_data_job).start()
            
        return redirect(url_for('ultra_analyze'))
    except Exception as e: 
        logger.error(f"Login Error: {e}")
        return redirect(url_for('ultra_home'))

@app.route('/analyze')
def ultra_analyze():
    if not session.get('verified'): return redirect(url_for('ultra_home'))
    
    # Symbole vide par défaut pour que la barre soit propre
    symbol = request.args.get('symbol', '').upper().strip()
    
    # Si aucun symbole n'est demandé, on n'affiche pas de données vides
    if not symbol:
        top_sectors, heatmap_data = get_global_context()
        return render_template('index.html', 
            symbol="", last_close_price=None, recommendation=None, 
            reason="Veuillez entrer un symbole boursier pour commencer l'analyse.",
            top_sectors=top_sectors, heatmap_data=heatmap_data,
            engine_status='READY', last_update=MARKET_STATE['last_update'])

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers WHERE name LIKE ? OR symbol = ?", (f'%{symbol}%', symbol))
            row = cursor.fetchone()
            if row: symbol = row[0]
    except Exception: pass
    
    with market_lock:
        info, df = MARKET_STATE['tickers'].get(symbol), MARKET_STATE['dataframes'].get(symbol)
    
    # FALLBACK SYNC
    news_list = []
    analyst_info = "N/A"
    if df is None:
        logger.info(f"🔍 Falling back to sync fetch for {symbol}")
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2y")
            logger.info(f"📊 Data fetched for {symbol}: {len(df) if df is not None else 0} rows")
            
            # Fetch news and analyst info
            news_list = ticker.news[:5] if ticker.news else []
            try:
                analyst_info = ticker.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
            except Exception as e:
                logger.warning(f"Could not fetch info for {symbol}: {e}")

            if df is not None and not df.empty:
                df.columns = [col.lower() for col in df.columns]
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                info = {
                    'price': float(df['close'].iloc[-1]),
                    'change_pct': ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0,
                    'recommendation': reco,
                    'reason': reason,
                    'rsi': rsi,
                    'mm20': mm20,
                    'mm50': mm50,
                    'mm200': mm200,
                    'targets': {'entry': entry, 'exit': exit},
                    'vol_spike': 1.0,
                    'sector': 'Autre',
                    'sector_avg': 0,
                    'relative_strength': 0
                }
                logger.info(f"✅ Analysis complete for {symbol}: {reco}")
            else:
                logger.warning(f"⚠️ No data returned for {symbol}")
        except Exception as e:
            logger.error(f"❌ Fallback fetch error for {symbol}: {e}")
            pass
    else:
        # If df was already in MARKET_STATE, we still need news for the specific symbol
        try:
            ticker = yf.Ticker(symbol)
            news_list = ticker.news[:5] if ticker.news else []
            analyst_info = ticker.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
        except: pass

    top_sectors, heatmap_data = get_global_context()
    esg, fund = MARKET_STATE['esg_data'].get(symbol, {'score': 'N/A', 'badge': '-'}), MARKET_STATE['fundamentals'].get(symbol, {'pe': 'N/A', 'yield': 'N/A'})
    sentiment_score, sentiment_label = analyze_sentiment(news_list)

    # --- INITIALISATION SYSTEMATIQUE ---
    context = {
        'symbol': symbol, 'last_close_price': None, 'daily_change_percent': 0, 'recommendation': None, 'reason': 'Analyse en cours...', 
        'rsi_value': 50, 'mm20': 0, 'mm50': 0, 'mm200': 0, 'short_term_entry_price': "N/A", 'short_term_exit_price': "N/A",
        'sector': "N/A", 'sector_avg': 0, 'relative_strength': 0, 'vol_spike': 1, 'esg_score': "N/A", 'esg_badge': "-", 
        'pe_ratio': "N/A", 'div_yield': "0", 'currency_symbol': "€", 'stock_chart_div': "", 'top_sectors': top_sectors, 
        'heatmap_data': heatmap_data, 'engine_status': 'ONLINE', 'last_update': MARKET_STATE['last_update'] or 'Chargement...',
        'news': news_list, 'analyst_recommendation': analyst_info,
        'sentiment_score': sentiment_score, 'sentiment_label': sentiment_label
    }

    if df is not None and info is not None:
        price = info.get('price', 0)
        targets = info.get('targets', {})
        context.update({
            'last_close_price': price if price > 0 else 0.001,
            'daily_change_percent': info.get('change_pct', 0),
            'recommendation': info.get('recommendation', 'Conserver'), 
            'reason': info.get('reason', 'N/A'), 
            'rsi_value': info.get('rsi', 50),
            'mm20': info.get('mm20', 0), 
            'mm50': info.get('mm50', 0), 
            'mm200': info.get('mm200', 0),
            'short_term_entry_price': f"{targets.get('entry', 0):.2f}" if targets.get('entry') else "N/A", 
            'short_term_exit_price': f"{targets.get('exit', 0):.2f}" if targets.get('exit') else "N/A",
            'sector': info.get('sector', 'N/A'),
            'vol_spike': info.get('vol_spike', 1),
            'stock_chart_div': create_stock_chart(df, symbol)
        })
    
    return render_template('index.html', **context)

@app.route('/status')
def ultra_status():
    with market_lock:
        running = scheduler.running
        last_upd = MARKET_STATE['last_update']
        count = len(MARKET_STATE['tickers'])
    return jsonify({
        'engine_running': running,
        'last_update': last_upd,
        'cached_instruments': count,
        'version': VERSION
    })

@app.route('/export_leads_secret_v3')
def export_leads():
    # Note: Dans une version réelle, vous devriez ajouter une vérification de mot de passe ici
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email, signup_date, marketing_consent, ip_address FROM leads ORDER BY signup_date DESC")
            rows = cursor.fetchall()
        
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Email', 'Date Inscription', 'Consentement Marketing', 'IP'])
        writer.writerows(rows)
        
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=leads_export_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    except Exception as e:
        return f"Erreur lors de l'export : {e}", 500

@app.errorhandler(500)
def handle_500(e):
    return f"V3 CRITICAL ERROR DETECTED:<br><pre>{traceback.format_exc()}</pre>", 500

if __name__ == '__main__':

    # Lancement d'un cycle initial en arrière-plan

    threading.Thread(target=fetch_market_data_job).start()

    

    port = int(os.environ.get("PORT", 5000))

    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)
