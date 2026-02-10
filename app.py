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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingEngine")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-123")
VERSION = "3.2.6 (Diagnostic Mode)"
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
                ('MT.PA', 'ArcelorMittal', 'Matériaux'), ('CS.PA', 'AXA', 'Finance'), ('BNP.PA', 'BNP Paribas', 'Finance'), ('EN.PA', 'Bouygues', 'Industrie'),
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
    logger.info("📡 ENGINE: Starting stealth refresh...")
    symbols_info = {}
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM tickers")
            for row in cursor.fetchall(): symbols_info[row[0]] = row[1]
    except Exception: return

    symbols = list(symbols_info.keys())
    temp_tickers = {}
    temp_dfs = {}
    sector_stats = {}

    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2y")
            if df is None or df.empty: continue
            
            df.columns = [col.lower() for col in df.columns]
            # Sécurité division par zéro sur prix
            if len(df) < 2 or df['close'].iloc[-2] == 0: continue
            
            change_pct = ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100)
            sector = symbols_info.get(symbol, 'Autre')
            
            if sector not in sector_stats: sector_stats[sector] = []
            sector_stats[sector].append(change_pct)

            temp_dfs[symbol] = df
            vol_avg = df['volume'].tail(20).mean()
            temp_tickers[symbol] = {
                'price': float(df['close'].iloc[-1]), 'change_pct': float(change_pct), 'sector': sector,
                'vol_spike': float(df['volume'].iloc[-1] / vol_avg) if vol_avg > 0 else 1.0
            }
            time.sleep(0.3) # Anti-ban delay
        except Exception as e: 
            logger.error(f"Error {symbol}: {e}")
            MARKET_STATE['last_error'] = str(e)

    # Mise à jour atomique
    with market_lock:
        MARKET_STATE['tickers'].update(temp_tickers)
        MARKET_STATE['dataframes'].update(temp_dfs)
        for sec, changes in sector_stats.items():
            if changes: # Sécurité division par zéro
                MARKET_STATE['sectors'][sec] = sum(changes) / len(changes)
        
        # Analyse finale
        for symbol, info in MARKET_STATE['tickers'].items():
            df = MARKET_STATE['dataframes'].get(symbol)
            if df is None: continue
            sec_avg = MARKET_STATE['sectors'].get(info['sector'], 0)
            reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df, sec_avg)
            info.update({
                'recommendation': reco, 'reason': reason, 'rsi': rsi,
                'mm20': mm20, 'mm50': mm50, 'mm200': mm200,
                'targets': {'entry': entry, 'exit': exit}, 'sector_avg': sec_avg,
                'relative_strength': info['change_pct'] - sec_avg
            })
        MARKET_STATE['last_update'] = datetime.now().isoformat()
    logger.info(f"✅ ENGINE: Refreshed.")

def analyze_stock(df, sector_avg_change=0):
    try:
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        last = df.iloc[-1]
        mm200, rsi, close = last.get('SMA_200'), last.get('RSI_14', 50), last['close']
        daily_change = ((close - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0
        rs = daily_change - sector_avg_change
        reco, reason = "Conserver", "Neutre"
        if mm200 and close > mm200:
            if rsi < 40 or rs > 1.5: reco, reason = "Achat", "Tendance haussière"
        elif mm200 and close < mm200:
            if rsi > 70 or rs < -1.5: reco, reason = "Vente", "Faiblesse relative"
        return reco, reason, float(rsi), float(last.get('SMA_20', 0)), float(last.get('SMA_50', 0)), None, float(mm200 or 0), float(close*0.98), float(close*1.05)
    except Exception: return "N/A", "Erreur", 50, 0, 0, None, 0, 0, 0

def create_stock_chart(df, symbol):
    try:
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'])])
        fig.update_layout(title=f'{symbol}', height=400, template='plotly_white', margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False)
        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception: return ""

# --- HELPERS ---
def get_global_context():
    with market_lock:
        sectors = dict(MARKET_STATE['sectors'])
        tickers = dict(MARKET_STATE['tickers'])
    sorted_sectors = sorted(sectors.items(), key=lambda x: x[1], reverse=True)
    top_sectors = [{'name': name, 'change': change} for name, change in sorted_sectors[:5]]
    heatmap_data = []
    for s, t_info in tickers.items():
        if '.PA' in s: heatmap_data.append({'symbol': s.replace('.PA', ''), 'change': t_info['change_pct'], 'full_symbol': s})
    return top_sectors, sorted(heatmap_data, key=lambda x: x['symbol'])

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=20), id='mkt_job')
scheduler.start()

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
        if not MARKET_STATE['tickers']: threading.Thread(target=fetch_market_data_job).start()
        return redirect(url_for('analyze_page'))
    except Exception: return redirect(url_for('index'))

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.form.get('query', '').strip() if request.method == 'POST' else request.args.get('query', '').strip()
    if not query: return redirect(url_for('analyze_page'))
    return redirect(url_for('analyze_page', symbol=query))

@app.route('/api/search_tickers')
def search_tickers():
    query = request.args.get('query', '').upper()
    if not query: return jsonify([])
    with market_lock:
        results = [{'symbol': s, 'name': ''} for s in MARKET_STATE['tickers'].keys() if query in s][:5]
    if not results:
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT symbol, name FROM tickers WHERE symbol LIKE ? OR name LIKE ? LIMIT 10", (f'%{query}%', f'%{query}%'))
                results = [{'symbol': row[0], 'name': row[1]} for row in cursor.fetchall()]
        except Exception: pass
    return jsonify(results)

@app.route('/analyze')
def analyze_page():
    if not session.get('verified'): return redirect(url_for('index'))
    symbol = request.args.get('symbol', 'MC.PA').upper().strip()
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers WHERE name LIKE ? OR symbol = ?", (f'%{symbol}%', symbol))
            row = cursor.fetchone()
            if row: symbol = row[0]
    except Exception: pass
    
    with market_lock:
        info = MARKET_STATE['tickers'].get(symbol)
        df = MARKET_STATE['dataframes'].get(symbol)
    
    if df is None or info is None:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2y")
            if not df.empty:
                df.columns = [col.lower() for col in df.columns]
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                info = {'price': float(df['close'].iloc[-1]), 'change_pct': 0.0, 'recommendation': reco, 'reason': reason, 'rsi': rsi, 'mm20': mm20, 'mm50': mm50, 'mm200': mm200, 'targets': {'entry': entry, 'exit': exit}, 'vol_spike': 1.0}
        except Exception: pass

    top_sectors, heatmap_data = get_global_context()
    esg = MARKET_STATE['esg_data'].get(symbol, {'score': 'N/A', 'badge': '-'})
    fund = MARKET_STATE['fundamentals'].get(symbol, {'pe': 'N/A', 'yield': 'N/A'})

    if df is not None and info is not None:
        context = {
            'symbol': symbol, 'last_close_price': info.get('price', 0), 'daily_change': 0, 'daily_change_percent': info.get('change_pct', 0),
            'recommendation': info.get('recommendation', 'N/A'), 'reason': info.get('reason', 'N/A'), 'rsi_value': info.get('rsi', 50),
            'mm20': info.get('mm20', 0), 'mm50': info.get('mm50', 0), 'mm200': info.get('mm200', 0),
            'short_term_entry_price': f"{info.get('targets', {}).get('entry', 0):.2f}", 
            'short_term_exit_price': f"{info.get('targets', {}).get('exit', 0):.2f}",
            'sector': info.get('sector', 'N/A'), 'sector_avg': info.get('sector_avg', 0), 'relative_strength': info.get('relative_strength', 0), 'vol_spike': info.get('vol_spike', 1),
            'esg_score': esg['score'], 'esg_badge': esg['badge'], 'pe_ratio': fund['pe'], 'div_yield': fund['yield'],
            'currency_symbol': '€' if '.PA' in symbol else '$', 'stock_chart_div': create_stock_chart(df, symbol),
            'engine_status': 'ONLINE', 'last_update': MARKET_STATE['last_update'], 'top_sectors': top_sectors, 'heatmap_data': heatmap_data
        }
        return render_template('index.html', **context)
    
    flash(f"Instrument {symbol} introuvable.", "error")
    return render_template('index.html', symbol=symbol, recommendation=None, top_sectors=top_sectors, heatmap_data=heatmap_data)

@app.errorhandler(500)
def handle_500(e):
    return f"INTERNAL ERROR DETECTED:<br><pre>{traceback.format_exc()}</pre>", 500

@app.route('/status')
def engine_status():
    return jsonify({'version': VERSION, 'cache_size': len(MARKET_STATE['tickers']), 'last_update': MARKET_STATE['last_update']})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)