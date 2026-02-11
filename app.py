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

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYDEVD_DISABLE_FILE_VALIDATION'] = '1'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingEngine")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "".join(random.choices(string.ascii_letters + string.digits, k=32)))
VERSION = "3.5.0 (Recovery Edition)"
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

def analyze_stock(df, sector_avg_change=0):
    try:
        if df is None or len(df) < 10:
            return "Neutre", "Données insuffisantes", 50, 0, 0, None, 0, 0, 0
            
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        if len(df) >= 200:
            df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        
        last = df.iloc[-1]
        close = last['close']
        rsi = last.get('RSI_14', 50)
        mm200 = last.get('SMA_200')
        
        daily_change = ((close - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0
        
        reco, reason = "Conserver", "Analyse technique neutre"
        
        if mm200 and not pd.isna(mm200):
            if close > mm200:
                if rsi < 45: reco, reason = "Achat", "Tendance haussière & zone d'achat"
                else: reco, reason = "Conserver", "Tendance haussière confirmée"
            else:
                if rsi > 65: reco, reason = "Vente", "Tendance baissière & surachat"
                else: reco, reason = "Prudence", "Sous la moyenne mobile 200"
        
        return reco, reason, float(rsi), float(last.get('SMA_20', 0)), float(last.get('SMA_50', 0)), None, float(mm200 or 0), float(close*0.98), float(close*1.05)
    except Exception as e:
        logger.error(f"Analysis Error: {e}")
        return "Erreur", "Problème technique", 50, 0, 0, None, 0, 0, 0

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
    temp_tickers, temp_dfs = {}, {}
    
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            # Utilisation de 1y pour avoir assez de données pour SMA 200
            df = ticker.history(period="1y", timeout=20)
            if df is None or df.empty:
                # On met quand même une entrée vide pour la carte thermique
                temp_tickers[symbol] = {'price': 0, 'change_pct': 0, 'sector': symbols_info.get(symbol, 'Autre'), 'vol_spike': 1.0}
                continue
            
            df.columns = [col.lower() for col in df.columns]
            close_now = df['close'].iloc[-1]
            close_prev = df['close'].iloc[-2] if len(df) > 1 else close_now
            change_pct = ((close_now - close_prev) / close_prev * 100) if close_prev != 0 else 0
            
            reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
            
            temp_dfs[symbol] = df
            temp_tickers[symbol] = {
                'price': float(close_now),
                'change_pct': float(change_pct),
                'sector': symbols_info.get(symbol, 'Autre'),
                'recommendation': reco,
                'reason': reason,
                'rsi': rsi,
                'mm20': mm20,
                'mm50': mm50,
                'mm200': mm200,
                'targets': {'entry': entry, 'exit': exit},
                'vol_spike': 1.0
            }
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Failed {symbol}: {e}")
            temp_tickers[symbol] = {'price': 0, 'change_pct': 0, 'sector': symbols_info.get(symbol, 'Autre'), 'vol_spike': 1.0}
            
    with market_lock:
        MARKET_STATE['tickers'].update(temp_tickers)
        MARKET_STATE['dataframes'].update(temp_dfs)
        MARKET_STATE['last_update'] = datetime.now().isoformat()
    logger.info(f"✅ ENGINE: Cycle complete. {len(MARKET_STATE['tickers'])} assets.")

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
    
    heatmap_data = []
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers")
            all_db_symbols = [row[0] for row in cursor.fetchall()]
            
            if not all_db_symbols and live_tickers:
                all_db_symbols = list(live_tickers.keys())

            for s in all_db_symbols:
                info = live_tickers.get(s, {})
                change = info.get('change_pct', 0)
                intensity = min(abs(change) * 10, 100)
                
                heatmap_data.append({
                    'symbol': s.replace('.PA', ''),
                    'change': change,
                    'full_symbol': s,
                    'intensity': intensity
                })
    except Exception: pass
    return [], sorted(heatmap_data, key=lambda x: x['symbol'])

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=20), id='mkt_job')
scheduler.start()

# --- ROUTES ---

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
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, name FROM tickers WHERE symbol LIKE ? OR name LIKE ? LIMIT 10", (f'%{query}%', f'%{query}%'))
            results = [{'symbol': row[0], 'name': row[1]} for row in cursor.fetchall()]
    except Exception: pass
    return jsonify(results)

@app.route('/')
def ultra_home():
    if session.get('verified'): return redirect(url_for('ultra_analyze'))
    return render_template('welcome.html')

@app.route('/login', methods=['POST'])
def ultra_login():
    email = request.form.get('email', '').strip().lower()
    if not email or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        flash("Email invalide", "error")
        return redirect(url_for('ultra_home'))
    session['verified'] = True
    return redirect(url_for('ultra_analyze'))

@app.route('/analyze')
def ultra_analyze():
    if not session.get('verified'): return redirect(url_for('ultra_home'))
    symbol = request.args.get('symbol', '').upper().strip()
    
    top_sectors, heatmap_data = get_global_context()
    
    if not symbol:
        return render_template('index.html', symbol="", last_close_price=None, top_sectors=[], heatmap_data=heatmap_data)

    # Récupération DATA
    with market_lock:
        info = MARKET_STATE['tickers'].get(symbol)
        df = MARKET_STATE['dataframes'].get(symbol)

    news_list = []
    analyst_info = "N/A"
    
    # Force sync fetch if not in cache or if cache is empty skeleton
    if df is None or (info and info.get('price') == 0):
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y")
            news_list = ticker.news[:5] if ticker.news else []
            analyst_info = ticker.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
            
            if df is not None and not df.empty:
                df.columns = [col.lower() for col in df.columns]
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                info = {
                    'price': float(df['close'].iloc[-1]),
                    'change_pct': ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0,
                    'recommendation': reco, 'reason': reason, 'rsi': rsi, 'mm20': mm20, 'mm50': mm50, 'mm200': mm200,
                    'targets': {'entry': entry, 'exit': exit}, 'sector': 'Autre'
                }
        except: pass

    sentiment_score, sentiment_label = analyze_sentiment(news_list)

    context = {
        'symbol': symbol, 'last_close_price': info.get('price') if info else 0.001,
        'daily_change_percent': info.get('change_pct', 0) if info else 0,
        'recommendation': info.get('recommendation', 'Analyse...') if info else 'Indisponible',
        'reason': info.get('reason', 'Récupération des données en cours') if info else 'Erreur de connexion API',
        'rsi_value': info.get('rsi', 50) if info else 50,
        'mm20': info.get('mm20', 0) if info else 0,
        'mm50': info.get('mm50', 0) if info else 0,
        'mm200': info.get('mm200', 0) if info else 0,
        'short_term_entry_price': f"{info['targets']['entry']:.2f}" if info and 'targets' in info else "N/A",
        'short_term_exit_price': f"{info['targets']['exit']:.2f}" if info and 'targets' in info else "N/A",
        'sector': info.get('sector', 'N/A') if info else 'N/A',
        'pe_ratio': "N/A", 'div_yield': "0", 'currency_symbol': "€", 
        'stock_chart_div': create_stock_chart(df, symbol) if df is not None else "",
        'top_sectors': [], 'heatmap_data': heatmap_data, 'engine_status': 'ONLINE',
        'last_update': MARKET_STATE['last_update'], 'news': news_list, 'analyst_recommendation': analyst_info,
        'sentiment_score': sentiment_score, 'sentiment_label': sentiment_label
    }
    
    return render_template('index.html', **context)

@app.route('/status')
def ultra_status():
    with market_lock:
        return jsonify({'engine_running': scheduler.running, 'last_update': MARKET_STATE['last_update'], 'cached_instruments': len(MARKET_STATE['tickers']), 'version': VERSION})

if __name__ == '__main__':
    threading.Thread(target=fetch_market_data_job).start()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)), use_reloader=False)