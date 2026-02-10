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
VERSION = "3.1.0 (Sector & ESG Aware)"
DB_NAME = "users.db"

cache = Cache(app, config={'CACHE_TYPE': 'SimpleCache', 'CACHE_DEFAULT_TIMEOUT': 300})

# --- GLOBAL MARKET STATE ---
MARKET_STATE = {
    'last_update': None,
    'tickers': {},  
    'dataframes': {},
    'sectors': {}, # { 'Luxe': {'avg_change': 1.2, 'count': 3}, ... }
    'esg_data': {}  # { 'MC.PA': {'total': 70, 'badge': 'A'} }
}

def init_db():
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS tickers") # On recrée pour ajouter la colonne sector
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickers (symbol TEXT PRIMARY KEY, name TEXT, sector TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS legal_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, ip_address TEXT, consent_date TEXT, user_agent TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS leads (email TEXT PRIMARY KEY, signup_date TEXT, marketing_consent INTEGER DEFAULT 0, ip_address TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, symbol TEXT, found INTEGER, timestamp TEXT)''')
            
            # CAC 40 avec Secteurs (Optimisation inspirée par Euronext Index Services)
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
        logger.error(f"Database initialization failed: {e}")

init_db()

# --- MARKET DATA ENGINE ---

def fetch_esg_data():
    """Tâche quotidienne pour récupérer les scores ESG (Lent, donc séparé)"""
    logger.info("🌿 ESG ENGINE: Updating sustainability scores...")
    symbols = list(MARKET_STATE['tickers'].keys())
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            sus = ticker.sustainability
            if sus is not None:
                score = sus.loc['totalEsg', 'Value'] if 'totalEsg' in sus.index else 0
                badge = 'A' if score < 20 else 'B' if score < 30 else 'C'
                MARKET_STATE['esg_data'][symbol] = {'score': score, 'badge': badge}
        except Exception: pass
    logger.info("✅ ESG ENGINE: Update complete.")

def fetch_market_data_job():
    logger.info("📡 ENGINE: Starting market data refresh cycle...")
    
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
        data = yf.download(symbols, period="2y", group_by='ticker', progress=False, threads=True)
        
        # Reset Sectors
        sector_stats = {} 

        for symbol in symbols:
            try:
                df = data[symbol] if len(symbols) > 1 else data
                if df.empty or len(df) < 50: continue
                
                df = df.dropna(subset=['Close'])
                df.columns = [col.lower() for col in df.columns]
                
                # Calcul Performance Individuelle
                change_pct = ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0
                
                # Agrégation Sectorielle
                sector = symbols_info.get(symbol, 'Autre')
                if sector not in sector_stats: sector_stats[sector] = []
                sector_stats[sector].append(change_pct)

                MARKET_STATE['dataframes'][symbol] = df
                MARKET_STATE['tickers'][symbol] = {
                    'price': df['close'].iloc[-1],
                    'change_pct': change_pct,
                    'sector': sector,
                    'last_updated': datetime.now().strftime('%H:%M:%S')
                }
            except Exception: continue

        # Finalisation des moyennes sectorielles
        for sec, changes in sector_stats.items():
            MARKET_STATE['sectors'][sec] = sum(changes) / len(changes) if changes else 0

        # Seconde passe : Analyse avec Force Relative
        for symbol in list(MARKET_STATE['tickers'].keys()):
            df = MARKET_STATE['dataframes'][symbol]
            info = MARKET_STATE['tickers'][symbol]
            sec_avg = MARKET_STATE['sectors'].get(info['sector'], 0)
            
            reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df, sec_avg)
            info.update({
                'recommendation': reco, 'reason': reason, 'rsi': rsi,
                'targets': {'entry': entry, 'exit': exit},
                'sector_avg': sec_avg,
                'relative_strength': info['change_pct'] - sec_avg
            })
                
        MARKET_STATE['last_update'] = datetime.now().isoformat()
        logger.info(f"✅ ENGINE: Refreshed {len(MARKET_STATE['tickers'])} instruments and {len(MARKET_STATE['sectors'])} sectors.")
        
    except Exception as e:
        logger.error(f"❌ ENGINE CRITICAL: {e}")

def analyze_stock(df, sector_avg_change=0):
    """Algorithme optimisé avec Force Relative Sectorielle"""
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
        
        # Force Relative : L'action monte-t-elle plus que son secteur ?
        relative_strength = daily_change - sector_avg_change
        
        reco = "Conserver"
        reason = "Neutre"
        
        if mm200 and close > mm200:
            if rsi < 40 or relative_strength > 1.5:
                reco = "Achat"
                reason = "Tendance haussière + Forte résistance sectorielle" if relative_strength > 1.5 else "Tendance haussière + Survente"
        elif mm200 and close < mm200:
            if rsi > 70 or relative_strength < -1.5:
                reco = "Vente"
                reason = "Faiblesse sous MM200 + Sous-performance sectorielle"
            
        return reco, reason, rsi, last.get('SMA_20'), last.get('SMA_50'), None, mm200, close*0.98, close*1.05
    except Exception:
        return "N/A", "Erreur", 50, None, None, None, None, None, None

def create_stock_chart(df, symbol):
    try:
        fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Cours')])
        if 'SMA_200' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], name='MM200 Long Terme', line=dict(width=2, color='red')))
        fig.update_layout(title=f'{symbol}', height=400, template='plotly_white', margin=dict(l=10, r=10, t=30, b=10), xaxis_rangeslider_visible=False)
        return fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception: return ""

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=15), id='mkt_job')
scheduler.add_job(func=fetch_esg_data, trigger=IntervalTrigger(hours=24), id='esg_job')
scheduler.start()

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
def analyze_page():
    if not session.get('verified'): return redirect(url_for('index'))
    symbol = request.args.get('symbol', 'MC.PA').upper().strip()
    
    # 1. Résolution
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol FROM tickers WHERE name LIKE ? OR symbol = ?", (f'%{symbol}%', symbol))
            row = cursor.fetchone()
            if row: symbol = row[0]
    except Exception: pass

    info = MARKET_STATE['tickers'].get(symbol)
    df = MARKET_STATE['dataframes'].get(symbol)
    esg = MARKET_STATE['esg_data'].get(symbol, {'score': 'N/A', 'badge': '-'})

    # TOP 5 SECTEURS (Calculé dynamiquement depuis la mémoire)
    sorted_sectors = sorted(MARKET_STATE['sectors'].items(), key=lambda x: x[1], reverse=True)
    top_sectors = [{'name': name, 'change': change} for name, change in sorted_sectors[:5]]

    # HEATMAP DATA (Nouveau)
    heatmap_data = []
    for s, t_info in MARKET_STATE['tickers'].items():
        if '.PA' in s: # On se concentre sur Euronext Paris pour la heatmap
            heatmap_data.append({
                'symbol': s.replace('.PA', ''),
                'change': t_info['change_pct'],
                'full_symbol': s
            })
    heatmap_data = sorted(heatmap_data, key=lambda x: x['symbol'])

    if df is not None:
        context = {
            'symbol': symbol,
            'last_close_price': info['price'],
            'daily_change': df['close'].iloc[-1] - df['close'].iloc[-2],
            'daily_change_percent': info['change_pct'],
            'recommendation': info['recommendation'],
            'reason': info['reason'],
            'rsi_value': info['rsi'],
            'short_term_entry_price': f"{info['targets']['entry']:.2f}",
            'short_term_exit_price': f"{info['targets']['exit']:.2f}",
            'sector': info['sector'],
            'sector_avg': info['sector_avg'],
            'relative_strength': info['relative_strength'],
            'esg_score': esg['score'],
            'esg_badge': esg['badge'],
            'mm200': info.get('mm200'),
            'currency_symbol': '€' if '.PA' in symbol else '$',
            'stock_chart_div': create_stock_chart(df, symbol),
            'engine_status': 'ONLINE',
            'last_update': MARKET_STATE['last_update'],
            'top_sectors': top_sectors,
            'heatmap_data': heatmap_data # Ajout à la Heatmap
        }
        return render_template('index.html', **context)
    
    flash(f"Instrument {symbol} non trouvé ou en cours de chargement.", "error")
    return render_template('index.html', symbol=symbol, recommendation=None)

@app.route('/status')
def engine_status():
    return jsonify({
        'version': VERSION,
        'cached_instruments': len(MARKET_STATE['tickers']),
        'sectors_tracked': len(MARKET_STATE['sectors']),
        'last_update': MARKET_STATE['last_update']
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)
