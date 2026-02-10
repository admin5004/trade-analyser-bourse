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
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2y")
            if df is None or df.empty: continue
            df.columns = [col.lower() for col in df.columns]
            if len(df) < 2 or df['close'].iloc[-2] == 0: continue
            change_pct = ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100)
            sector = symbols_info.get(symbol, 'Autre')
            if sector not in sector_stats: sector_stats[sector] = []
            sector_stats[sector].append(change_pct)
            temp_dfs[symbol] = df
            temp_tickers[symbol] = {'price': float(df['close'].iloc[-1]), 'change_pct': float(change_pct), 'sector': sector, 'vol_spike': float(df['volume'].iloc[-1] / df['volume'].tail(20).mean()) if df['volume'].tail(20).mean() > 0 else 1.0}
            time.sleep(0.5)
        except Exception: continue
    with market_lock:
        MARKET_STATE['tickers'].update(temp_tickers)
        MARKET_STATE['dataframes'].update(temp_dfs)
        for sec, changes in sector_stats.items():
            if changes: MARKET_STATE['sectors'][sec] = sum(changes) / len(changes)
        MARKET_STATE['last_update'] = datetime.now().isoformat()
    logger.info("✅ ENGINE: Cycle complete.")

def analyze_stock(df, sector_avg_change=0):
    try:
        df.ta.sma(length=20, append=True); df.ta.sma(length=50, append=True); df.ta.sma(length=200, append=True); df.ta.rsi(length=14, append=True)
        last = df.iloc[-1]; mm200, rsi, close = last.get('SMA_200'), last.get('RSI_14', 50), last['close']
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

def get_global_context():
    # Récupérer les données live
    with market_lock:
        sectors, tickers = dict(MARKET_STATE['sectors']), dict(MARKET_STATE['tickers'])
    
    # Récupérer TOUS les symboles de la base pour garantir que la heatmap n'est jamais vide
    all_symbols_data = {}
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, name FROM tickers")
            for row in cursor.fetchall():
                symbol_full = row[0]
                all_symbols_data[symbol_full] = {
                    'symbol_short': symbol_full.replace('.PA', ''),
                    'change': 0,
                    'full_symbol': symbol_full
                }
    except Exception as e:
        logger.error(f"Error fetching symbols for heatmap: {e}")

    # Fusionner avec les données live
    for s, t_info in tickers.items():
        if s in all_symbols_data:
            all_symbols_data[s]['change'] = t_info.get('change_pct', 0)
        else:
            all_symbols_data[s] = {
                'symbol_short': s.replace('.PA', ''),
                'change': t_info.get('change_pct', 0),
                'full_symbol': s
            }

    sorted_sectors = sorted(sectors.items(), key=lambda x: x[1], reverse=True)
    top_sectors = [{'name': name, 'change': change} for name, change in sorted_sectors[:5]]
    
    heatmap_data = []
    for s, data in all_symbols_data.items():
        heatmap_data.append({
            'symbol': data['symbol_short'],
            'change': data['change'],
            'full_symbol': data['full_symbol']
        })
    
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
        if not MARKET_STATE['tickers']: threading.Thread(target=fetch_market_data_job).start()
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
    if df is None:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2y")
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
        except Exception as e:
            logger.error(f"Fallback fetch error for {symbol}: {e}")
            pass

    top_sectors, heatmap_data = get_global_context()
    esg, fund = MARKET_STATE['esg_data'].get(symbol, {'score': 'N/A', 'badge': '-'}), MARKET_STATE['fundamentals'].get(symbol, {'pe': 'N/A', 'yield': 'N/A'})

    # --- INITIALISATION SYSTEMATIQUE ---
    context = {
        'symbol': symbol, 'last_close_price': None, 'daily_change_percent': 0, 'recommendation': None, 'reason': 'Analyse en cours...', 
        'rsi_value': 50, 'mm20': 0, 'mm50': 0, 'mm200': 0, 'short_term_entry_price': "N/A", 'short_term_exit_price': "N/A",
        'sector': "N/A", 'sector_avg': 0, 'relative_strength': 0, 'vol_spike': 1, 'esg_score': "N/A", 'esg_badge': "-", 
        'pe_ratio': "N/A", 'div_yield': "0", 'currency_symbol': "€", 'stock_chart_div': "", 'top_sectors': top_sectors, 
        'heatmap_data': heatmap_data, 'engine_status': 'ONLINE', 'last_update': MARKET_STATE['last_update'] or 'Chargement...'
    }

    if df is not None and info is not None:
        price = info.get('price', 0)
        context.update({
            'last_close_price': price if price > 0 else 0.001, # Évite le loop du loader si prix est 0
            'daily_change_percent': info.get('change_pct', 0),
            'recommendation': info.get('recommendation', 'Conserver'), 'reason': info.get('reason', 'N/A'), 'rsi_value': info.get('rsi', 50),
            'mm20': info.get('mm20', 0), 'mm50': info.get('mm50', 0), 'mm200': info.get('mm200', 0),
            'short_term_entry_price': f"{info.get('targets', {}).get('entry', 0):.2f}" if info.get('targets') else "N/A", 
            'short_term_exit_price': f"{info.get('targets', {}).get('exit', 0):.2f}" if info.get('targets') else "N/A",
            'sector': info.get('sector', 'N/A'), 'sector_avg': info.get('sector_avg', 0), 'relative_strength': info.get('relative_strength', 0), 'vol_spike': info.get('vol_spike', 1),
            'esg_score': esg.get('score', 'N/A'), 'esg_badge': esg.get('badge', '-'), 'pe_ratio': fund.get('pe', 'N/A'), 'div_yield': fund.get('yield', '0'),
            'currency_symbol': '€' if '.PA' in symbol else '$', 'stock_chart_div': create_stock_chart(df, symbol)
        })
    
    return render_template('index.html', **context)

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
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host='0.0.0.0', port=port, use_reloader=False)