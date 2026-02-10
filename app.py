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
VERSION = "3.2.3 (Routes Restored)"
DB_NAME = "users.db"

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})

# --- STATE ---
MARKET_STATE = {
    'last_update': None,
    'tickers': {},  
    'dataframes': {},
    'sectors': {},
    'esg_data': {},
    'fundamentals': {} 
}

def init_db():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS tickers")
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickers (symbol TEXT PRIMARY KEY, name TEXT, sector TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS legal_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, ip_address TEXT, consent_date TEXT, user_agent TEXT)''')
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
    except Exception as e:
        logger.error(f"DB Error: {e}")

init_db()

# --- ENGINE ---

def fetch_esg_and_fundamentals():
    symbols = list(MARKET_STATE['tickers'].keys()) or ['MC.PA', 'AI.PA', 'SAN.PA', 'AAPL']
    for symbol in symbols:
        try:
            t = yf.Ticker(symbol)
            info = t.info
            MARKET_STATE['fundamentals'][symbol] = {
                'pe': info.get('trailingPE', 'N/A'),
                'yield': info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0
            }
            sus = t.sustainability
            if sus is not None:
                score = sus.loc['totalEsg', 'Value'] if 'totalEsg' in sus.index else 0
                badge = 'A' if score < 20 else 'B' if score < 30 else 'C'
                MARKET_STATE['esg_data'][symbol] = {'score': score, 'badge': badge}
        except Exception: continue

def fetch_market_data_job():
    logger.info("📡 ENGINE: Refreshing market data...")
    symbols_info = {}
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM tickers")
            for row in cursor.fetchall(): symbols_info[row[0]] = row[1]
    except Exception: return

    symbols = list(symbols_info.keys())
    if not symbols: return

    try:
        data = yf.download(symbols, period="2y", group_by='ticker', progress=False, threads=False)
        sector_stats = {} 

        for symbol in symbols:
            try:
                df = data[symbol] if len(symbols) > 1 else data
                if df is None or df.empty or len(df) < 50: continue
                df = df.dropna(subset=['Close'])
                df.columns = [col.lower() for col in df.columns]
                
                change_pct = ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0
                sector = symbols_info.get(symbol, 'Autre')
                if sector not in sector_stats: sector_stats[sector] = []
                sector_stats[sector].append(change_pct)

                MARKET_STATE['dataframes'][symbol] = df
                MARKET_STATE['tickers'][symbol] = {
                    'price': df['close'].iloc[-1],
                    'change_pct': change_pct,
                    'sector': sector,
                    'vol_spike': (df['volume'].iloc[-1] / df['volume'].tail(20).mean()) if df['volume'].tail(20).mean() > 0 else 1
                }
            except Exception: continue

        for sec, changes in sector_stats.items():
            MARKET_STATE['sectors'][sec] = sum(changes) / len(changes) if changes else 0

        for symbol in list(MARKET_STATE['tickers'].keys()):
            df = MARKET_STATE['dataframes'][symbol]
            info = MARKET_STATE['tickers'][symbol]
            sec_avg = MARKET_STATE['sectors'].get(info['sector'], 0)
            reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df, sec_avg)
            
            info.update({
                'recommendation': reco, 'reason': reason, 'rsi': rsi,
                'mm20': mm20, 'mm50': mm50, 'mm200': mm200,
                'targets': {'entry': entry, 'exit': exit},
                'sector_avg': sec_avg,
                'relative_strength': info['change_pct'] - sec_avg
            })
                
        MARKET_STATE['last_update'] = datetime.now().isoformat()
        logger.info(f"✅ ENGINE: Refreshed {len(MARKET_STATE['tickers'])} symbols.")
    except Exception as e: logger.error(f"❌ ENGINE CRITICAL: {e}")

def analyze_stock(df, sector_avg_change=0):
    try:
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        last = df.iloc[-1]
        mm200 = last.get('SMA_200')
        rsi = last.get('RSI_14', 50)
        close = last['close']
        daily_change = ((close - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0
        rs = daily_change - sector_avg_change
        reco, reason = "Conserver", "Neutre"
        if mm200 and close > mm200:
            if rsi < 40 or rs > 1.5: reco, reason = "Achat", "Tendance haussière"
        elif mm200 and close < mm200:
            if rsi > 70 or rs < -1.5: reco, reason = "Vente", "Faiblesse relative"
        return reco, reason, rsi, last.get('SMA_20'), last.get('SMA_50'), None, mm200, close*0.98, close*1.05
    except Exception: return "N/A", "Erreur", 50, None, None, None, None, None, None

def create_stock_chart(df, symbol):
    try:
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'])])
        fig.update_layout(title=f'{symbol}', height=400, template='plotly_white', margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False)
        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception: return ""

# --- HELPERS ---
def get_global_context():
    sorted_sectors = sorted(MARKET_STATE['sectors'].items(), key=lambda x: x[1], reverse=True)
    top_sectors = [{'name': name, 'change': change} for name, change in sorted_sectors[:5]]
    heatmap_data = []
    for s, t_info in MARKET_STATE['tickers'].items():
        if '.PA' in s: heatmap_data.append({'symbol': s.replace('.PA', ''), 'change': t_info['change_pct'], 'full_symbol': s})
    return top_sectors, sorted(heatmap_data, key=lambda x: x['symbol'])

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=15), id='mkt_job')
scheduler.add_job(func=fetch_esg_and_fundamentals, trigger=IntervalTrigger(hours=24), id='fnd_job')
scheduler.start()
threading.Timer(1.0, fetch_market_data_job).start()

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
            conn.execute('INSERT OR REPLACE INTO leads (email, signup_date, marketing_consent, ip_address) VALUES (?, ?, ?, ?)', (email, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1 if request.form.get('accept_marketing')=='on' else 0, request.remote_addr))
        session['verified'] = True
        session['pending_email'] = email
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
    
    logger.info(f"🔍 SEARCH: API query for '{query}'")
    results = []
    
    # 1. Tentative Mémoire
    if MARKET_STATE['tickers']:
        results = [{'symbol': s, 'name': ''} for s in MARKET_STATE['tickers'].keys() if query in s][:5]
    
    # 2. Force Fallback DB (Si mémoire vide ou peu de résultats)
    if len(results) < 3:
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                # Recherche intelligente sur symbole OU nom
                cursor.execute("SELECT symbol, name FROM tickers WHERE symbol LIKE ? OR name LIKE ? LIMIT 10", (f'%{query}%', f'%{query}%'))
                db_results = [{'symbol': row[0], 'name': row[1]} for row in cursor.fetchall()]
                # Fusion sans doublons
                seen = {r['symbol'] for r in results}
                for r in db_results:
                    if r['symbol'] not in seen:
                        results.append(r)
                        seen.add(r['symbol'])
        except Exception as e:
            logger.error(f"DB Search Error: {e}")
            
    return jsonify(results[:10])

@app.route('/analyze')
def analyze_page():
    if not session.get('verified'): return redirect(url_for('index'))
    symbol = request.args.get('symbol', 'MC.PA').upper().strip()
    
    try:
        # Résolution
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers WHERE name LIKE ? OR symbol = ?", (f'%{symbol}%', symbol))
            row = cursor.fetchone()
            if row: symbol = row[0]
    except Exception: pass
    
    # Données globales (Safe)
    top_sectors, heatmap_data = [], []
    try:
        top_sectors, heatmap_data = get_global_context()
    except Exception as e:
        logger.error(f"Global Context Error: {e}")

    # Récupération Info (Safe)
    info = MARKET_STATE['tickers'].get(symbol)
    df = MARKET_STATE['dataframes'].get(symbol)
    
    # Fallback
    if df is None:
        try:
            df = yf.Ticker(symbol).history(period="2y")
            if not df.empty:
                df.columns = [col.lower() for col in df.columns]
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                info = {
                    'price': df['close'].iloc[-1], 'change_pct': 0, 'recommendation': reco, 'reason': reason, 
                    'rsi': rsi, 'mm20': mm20, 'mm50': mm50, 'mm200': mm200, 'targets': {'entry': entry, 'exit': exit}, 
                    'vol_spike': 1, 'sector': 'Inconnu', 'sector_avg': 0, 'relative_strength': 0
                }
        except Exception as e:
            logger.error(f"Fallback Error for {symbol}: {e}")

    # Construction Contexte (Blindée)
    try:
        esg = MARKET_STATE['esg_data'].get(symbol, {'score': 'N/A', 'badge': '-'})
        fund = MARKET_STATE['fundamentals'].get(symbol, {'pe': 'N/A', 'yield': 'N/A'})

        if df is not None and info is not None:
            context = {
                'symbol': symbol,
                'last_close_price': info.get('price', 0),
                'daily_change': 0, 
                'daily_change_percent': info.get('change_pct', 0),
                'recommendation': info.get('recommendation', 'N/A'),
                'reason': info.get('reason', 'N/A'),
                'rsi_value': info.get('rsi', 50),
                'mm20': info.get('mm20'), 'mm50': info.get('mm50'), 'mm200': info.get('mm200'),
                'short_term_entry_price': f"{info.get('targets', {}).get('entry', 0):.2f}",
                'short_term_exit_price': f"{info.get('targets', {}).get('exit', 0):.2f}",
                'sector': info.get('sector', 'N/A'),
                'sector_avg': info.get('sector_avg', 0),
                'relative_strength': info.get('relative_strength', 0),
                'vol_spike': info.get('vol_spike', 1),
                'esg_score': esg.get('score', 'N/A'),
                'esg_badge': esg.get('badge', '-'),
                'pe_ratio': fund.get('pe', 'N/A'),
                'div_yield': fund.get('yield', 'N/A'),
                'currency_symbol': '€' if '.PA' in symbol else '$',
                'stock_chart_div': create_stock_chart(df, symbol),
                'stock_news': [],
                'engine_status': 'ONLINE',
                'last_update': MARKET_STATE['last_update'] or 'N/A',
                'top_sectors': top_sectors,
                'heatmap_data': heatmap_data
            }
            return render_template('index.html', **context)
            
    except Exception as e:
        logger.error(f"Rendering Error for {symbol}: {e}\n{traceback.format_exc()}")
        flash(f"Erreur d'affichage pour {symbol}. Contactez le support.", "error")
        return render_template('index.html', symbol=symbol, recommendation=None, top_sectors=top_sectors, heatmap_data=heatmap_data)
    
    flash(f"Données non disponibles pour {symbol}.", "error")
    return render_template('index.html', symbol=symbol, recommendation=None, top_sectors=top_sectors, heatmap_data=heatmap_data)

@app.route('/status')
def engine_status():
    return jsonify({'version': VERSION, 'cached_instruments': len(MARKET_STATE['tickers']), 'sectors_tracked': len(MARKET_STATE['sectors']), 'last_update': MARKET_STATE['last_update']})

@app.route('/admin/export_leads')
def export_leads():
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

@app.route('/debug')
def debug_logs():
    return f"<pre>{traceback.format_exc()}</pre>"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)
