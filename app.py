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

# --- CONFIGURATION PRO ---
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingEngine")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-123")
VERSION = "3.0.0 (High Performance Engine)"
DB_NAME = "users.db"

# Cache Configuration (Simple Cache for Dev, Redis for Prod)
cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})

# --- GLOBAL MARKET STATE (In-Memory Database) ---
# Ce dictionnaire remplace les appels API lents. Il est mis à jour par le moteur en arrière-plan.
MARKET_STATE = {
    'last_update': None,
    'tickers': {},  # { 'ACA.PA': { 'price': 12.5, 'change': 1.2, 'trend': 'Bullish', ... } }
    'dataframes': {} # { 'ACA.PA': pd.DataFrame(...) }
}

def init_db():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS legal_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, ip_address TEXT, consent_date TEXT, user_agent TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS leads (email TEXT PRIMARY KEY, signup_date TEXT, marketing_consent INTEGER DEFAULT 0, ip_address TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickers (symbol TEXT PRIMARY KEY, name TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, symbol TEXT, found INTEGER, timestamp TEXT)''')
            
            # Initialisation CAC 40
            cac40 = [
                ('AC.PA', 'Accor'), ('AI.PA', 'Air Liquide'), ('AIR.PA', 'Airbus'), ('ALO.PA', 'Alstom'),
                ('MT.PA', 'ArcelorMittal'), ('CS.PA', 'AXA'), ('BNP.PA', 'BNP Paribas'), ('EN.PA', 'Bouygues'),
                ('CAP.PA', 'Capgemini'), ('CA.PA', 'Carrefour'), ('ACA.PA', 'Crédit Agricole'), ('BN.PA', 'Danone'),
                ('DSY.PA', 'Dassault Systèmes'), ('EDEN.PA', 'Edenred'), ('ENGI.PA', 'Engie'), ('EL.PA', 'EssilorLuxottica'),
                ('ERF.PA', 'Eurofins Scientific'), ('RMS.PA', 'Hermès'), ('KER.PA', 'Kering'), ('OR.PA', "L'Oréal"),
                ('LR.PA', 'Legrand'), ('MC.PA', 'LVMH'), ('ML.PA', 'Michelin'), ('ORA.PA', 'Orange'),
                ('RI.PA', 'Pernod Ricard'), ('PUB.PA', 'Publicis'), ('RNO.PA', 'Renault'), ('SAF.PA', 'Safran'),
                ('SGO.PA', 'Saint-Gobain'), ('SAN.PA', 'Sanofi'), ('SU.PA', 'Schneider Electric'), ('GLE.PA', 'Société Générale'),
                ('STLAP.PA', 'Stellantis'), ('STMPA.PA', 'STMicroelectronics'), ('TEP.PA', 'Teleperformance'), ('HO.PA', 'Thales'),
                ('TTE.PA', 'TotalEnergies'), ('URW.PA', 'Unibail-Rodamco-Westfield'), ('VIE.PA', 'Veolia'), ('DG.PA', 'Vinci'),
                ('AYV.PA', 'Ayvens'), ('AAPL', 'Apple'), ('MSFT', 'Microsoft'), ('GOOGL', 'Alphabet (Google)'), ('AMZN', 'Amazon'),
                ('TSLA', 'Tesla'), ('NVDA', 'NVIDIA'), ('BTC-USD', 'Bitcoin'), ('ETH-USD', 'Ethereum')
            ]
            cursor.executemany('INSERT OR IGNORE INTO tickers (symbol, name) VALUES (?, ?)', cac40)
            conn.commit()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

init_db()

# --- MARKET DATA ENGINE (Optiq-inspired) ---

def fetch_market_data_job():
    """
    Tâche de fond 'Bulk Loader'.
    Télécharge tout le marché en une seule fois (très rapide) et met à jour la mémoire.
    """
    logger.info("📡 ENGINE: Starting market data refresh cycle...")
    
    # 1. Récupérer la liste des tickers
    symbols = []
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers")
            symbols = [row[0] for row in cursor.fetchall()]
    except Exception:
        symbols = ['CAC.PA', 'MC.PA', 'AI.PA', 'SAN.PA', 'GLE.PA', 'ACA.PA', 'BNP.PA', 'AAPL', 'MSFT', 'TSLA'] # Fallback
    
    if not symbols: return

    # 2. Bulk Download (Optimisation Majeure)
    try:
        # Téléchargement groupé : 1 requête HTTP au lieu de 50
        data = yf.download(symbols, period="2y", group_by='ticker', progress=False, threads=True)
        
        # 3. Traitement et Analyse
        updated_count = 0
        for symbol in symbols:
            try:
                # Extraction du DataFrame pour ce symbole
                df = data[symbol] if len(symbols) > 1 else data
                
                # Validation des données (Sanity Check)
                if df.empty or len(df) < 50:
                    continue
                
                # Nettoyage
                df = df.dropna(subset=['Close'])
                df.columns = [col.lower() for col in df.columns] # standardisation
                
                # Analyse Technique (Pré-calculée)
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                
                # Mise en cache
                MARKET_STATE['dataframes'][symbol] = df
                MARKET_STATE['tickers'][symbol] = {
                    'price': df['close'].iloc[-1],
                    'change_pct': ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0,
                    'recommendation': reco,
                    'reason': reason,
                    'rsi': rsi,
                    'targets': {'entry': entry, 'exit': exit},
                    'last_updated': datetime.now().strftime('%H:%M:%S')
                }
                updated_count += 1
            except Exception as e:
                logger.warning(f"Failed to process {symbol}: {e}")
                
        MARKET_STATE['last_update'] = datetime.now().isoformat()
        logger.info(f"✅ ENGINE: Refreshed {updated_count} instruments in {(datetime.now() - datetime.fromisoformat(MARKET_STATE['last_update'])).seconds if MARKET_STATE['last_update'] else 0}s")
        
    except Exception as e:
        logger.error(f"❌ ENGINE CRITICAL: Bulk download failed: {e}")

def analyze_stock(df, sentiment_score=0):
    """Analyse technique robuste"""
    if df is None or len(df) < 50:
        return "N/A", "Données insuffisantes", 50, None, None, None, None, None, None

    try:
        # Indicateurs
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=100, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)

        last = df.iloc[-1]
        mm200 = last.get('SMA_200')
        rsi = last.get('RSI_14', 50)
        close = last['close']
        
        reco = "Conserver"
        reason = "Neutre"
        
        if mm200 and close > mm200 and rsi < 40:
            reco = "Achat"
            reason = "Tendance haussière + Survente"
        elif mm200 and close < mm200 and rsi > 70:
            reco = "Vente"
            reason = "Tendance baissière + Surachat"
            
        return reco, reason, rsi, last.get('SMA_20'), last.get('SMA_50'), last.get('SMA_100'), mm200, close*0.98, close*1.05
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return "Erreur", "Echec calcul", 50, None, None, None, None, None, None

def create_stock_chart(df, symbol):
    try:
        # Version légère pour performance
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Cours')])
        if 'SMA_50' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], name='MM50', line=dict(width=1, color='orange')))
        if 'SMA_200' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], name='MM200', line=dict(width=1.5, color='blue')))
        fig.update_layout(title=f'{symbol}', height=450, template='plotly_white', margin=dict(l=20, r=20, t=40, b=20), xaxis_rangeslider_visible=False)
        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception: return "<div>Graphique indisponible</div>"

# --- SCHEDULER SETUP ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=15), id='market_data_job', name='Rafraichissement Market Data', replace_existing=True)
scheduler.start()

# Lancement immédiat au démarrage (dans un thread pour ne pas bloquer Flask)
threading.Thread(target=fetch_market_data_job).start()


# --- ROUTES ---

@app.route('/')
def index():
    if session.get('verified'): return redirect(url_for('analyze_page'))
    return render_template('welcome.html')

@app.route('/login', methods=['POST'])
def login():
    email = request.form.get('email', '').strip()
    if not email: return redirect(url_for('index'))
    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute('INSERT OR REPLACE INTO leads (email, signup_date, marketing_consent, ip_address) VALUES (?, ?, ?, ?)', 
                        (email, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1 if request.form.get('accept_marketing')=='on' else 0, request.remote_addr))
        session['verified'] = True
        session['pending_email'] = email
        return redirect(url_for('analyze_page'))
    except Exception: return redirect(url_for('index'))

@app.route('/analyze')
@cache.cached(timeout=60, query_string=True) # Cache la vue pour 60s
def analyze_page():
    if not session.get('verified'): return redirect(url_for('index'))
    symbol = request.args.get('symbol', 'ACA.PA').upper().strip()
    
    # 1. Résolution Symbole
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers WHERE name LIKE ? OR symbol = ?", (f'%{symbol}%', symbol))
            row = cursor.fetchone()
            if row: symbol = row[0]
    except Exception: pass

    # 2. Récupération depuis le MOTEUR (Mémoire) - Ultra Rapide
    market_info = MARKET_STATE['tickers'].get(symbol)
    df = MARKET_STATE['dataframes'].get(symbol)
    
    # 3. Fallback: Si pas en mémoire, on charge à la demande (Lent mais nécessaire)
    if df is None:
        logger.info(f"Cache miss for {symbol}, fetching live...")
        try:
            df = yf.Ticker(symbol).history(period="2y")
            df.columns = [col.lower() for col in df.columns]
            market_info = {'recommendation': 'Neutre', 'reason': 'Données temps réel', 'rsi': 50}
        except Exception:
            flash(f"Symbole {symbol} introuvable.", "error")
            return render_template('index.html', symbol=symbol, recommendation=None)
    
    # 4. Construction du contexte
    if df is not None and not df.empty:
        reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df) # Recalcul rapide
        
        context = {
            'symbol': symbol,
            'last_close_price': df['close'].iloc[-1],
            'daily_change': df['close'].iloc[-1] - df['close'].iloc[-2] if len(df)>1 else 0,
            'daily_change_percent': ((df['close'].iloc[-1] - df['close'].iloc[-2])/df['close'].iloc[-2]*100) if len(df)>1 else 0,
            'recommendation': reco, 'reason': reason, 'rsi_value': rsi,
            'short_term_entry_price': f"{entry:.2f}" if entry else "N/A",
            'short_term_exit_price': f"{exit:.2f}" if exit else "N/A",
            'mm20': mm20, 'mm50': mm50, 'mm100': mm100, 'mm200': mm200,
            'currency_symbol': '€' if '.PA' in symbol else '$',
            'stock_chart_div': create_stock_chart(df, symbol),
            'stock_news': [], # Désactivé pour performance, à remettre en async JS
            'sentiment_score': 0,
            'insiders': [],
            'engine_status': 'ONLINE',
            'last_update': MARKET_STATE['last_update']
        }
        return render_template('index.html', **context)
    
    return render_template('index.html', symbol=symbol, recommendation=None)

@app.route('/api/search_tickers')
def search_tickers():
    query = request.args.get('query', '').upper()
    if not query: return jsonify([])
    # Recherche en mémoire d'abord (très rapide)
    results = [{'symbol': s, 'name': ''} for s in MARKET_STATE['tickers'].keys() if query in s][:5]
    if not results:
        # Fallback DB
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT symbol, name FROM tickers WHERE symbol LIKE ? OR name LIKE ? LIMIT 5", (f'%{query}%', f'%{query}%'))
                results = [{'symbol': row[0], 'name': row[1]} for row in cursor.fetchall()]
        except Exception: pass
    return jsonify(results)

@app.route('/admin/export_leads')
def export_leads():
    # ... (Code existant conservé pour export) ...
    try:
        si = io.StringIO()
        cw = csv.writer(si)
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email, signup_date, marketing_consent, ip_address FROM leads")
            cw.writerow(['Email', 'Signup Date', 'Marketing Consent', 'IP Address'])
            cw.writerows(cursor.fetchall())
        return Response(si.getvalue(), mimetype="text/csv", headers={"Content-disposition": "attachment; filename=leads.csv"})
    except Exception: return "Erreur"

@app.route('/status')
def engine_status():
    return jsonify({
        'version': VERSION,
        'cached_instruments': len(MARKET_STATE['tickers']),
        'last_update': MARKET_STATE['last_update'],
        'engine_running': scheduler.running
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False) # use_reloader=False important pour Scheduler
