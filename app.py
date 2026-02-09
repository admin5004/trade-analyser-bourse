import os
import sqlite3
import random
import string
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from dotenv import load_dotenv
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, Response
import plotly.graph_objects as go
from textblob import TextBlob

# Charger les variables du fichier .env
load_dotenv()

# Initialisation de l'application Flask
app = Flask(__name__)
app.secret_key = "dev-secret-key-123"
VERSION = "2.0.2"

# --- CONFIGURATION BASE DE DONNÉES ---
DB_NAME = "users.db"

def init_db():
    """Initialise la base de données pour les utilisateurs, l'audit et les tickers."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS legal_audit (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, ip_address TEXT, consent_date TEXT, user_agent TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS leads (email TEXT PRIMARY KEY, signup_date TEXT, marketing_consent INTEGER DEFAULT 0, ip_address TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS tickers (symbol TEXT PRIMARY KEY, name TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, symbol TEXT, found INTEGER, timestamp TEXT)''')
        
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

init_db()

# --- FONCTIONS MÉTIER ---

def analyze_news_sentiment(news_list):
    if not news_list: return 0
    total_sentiment = 0
    for article in news_list:
        title = article.get('title', '')
        analysis = TextBlob(title)
        total_sentiment += analysis.sentiment.polarity
    return total_sentiment / len(news_list)

def get_stock_data(symbol):
    try:
        symbol = symbol.strip().upper()
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="2y")
        if df is None or df.empty: return None
        df.columns = [col.lower() for col in df.columns]
        if 'open' not in df.columns: return None
        df = df[['open', 'high', 'low', 'close', 'volume']]
        return df.sort_index()
    except Exception: return None

def analyze_stock(df, sentiment_score=0, info=None):
    fundamental_score = 0
    if info:
        try:
            rev_growth = info.get('revenueGrowth', 0) or 0
            earning_growth = info.get('earningsGrowth', 0) or 0
            if rev_growth > 0.05: fundamental_score += 1
            if earning_growth > 0.05: fundamental_score += 1
        except Exception: pass

    if len(df) < 200:
        return "Conserver", "Données insuffisantes", None, "N/A", "N/A", "N/A", "N/A", "N/A", "N/A", None, None

    df.ta.sma(length=60, append=True)
    df.ta.sma(length=200, append=True)
    df.ta.rsi(length=14, append=True)

    last_row = df.iloc[-1]
    mm200 = last_row['SMA_200']
    rsi = last_row['RSI_14']
    last_close_price = last_row['close']

    adjustment_factor = 1 + (sentiment_score * 0.05) + (fundamental_score * 0.02)
    recommendation = "Conserver"
    reason = "Analyse trimestrielle neutre."

    if last_close_price > mm200 and rsi < 40:
        recommendation = "Achat"
        reason = "Tendance trimestrielle haussière et zone de prix attractive."
    elif last_close_price < mm200 and rsi > 70:
        recommendation = "Vente"
        reason = "Signal de surachat dans une tendance trimestrielle baissière."
    
    entry = last_close_price * 0.98
    exit = last_close_price * 1.05 * adjustment_factor
    return recommendation, reason, rsi, "Neutre", "Neutre", "Neutre", "N/A", "N/A", "N/A", entry, exit

def create_stock_chart(df, symbol):
    fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Cours')])
    if 'SMA_60' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], mode='lines', name='MM60', line=dict(color='blue', width=1)))
    if 'SMA_200' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], mode='lines', name='MM200', line=dict(color='red', width=1)))
    fig.update_layout(title=f'Historique {symbol}', height=600, template='plotly_white')
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

# --- ROUTES ---

@app.route('/')
def index():
    if session.get('verified'): return redirect(url_for('analyze_page'))
    return render_template('welcome.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET': return redirect(url_for('index'))
    email = request.form.get('email')
    accept_marketing = request.form.get('accept_marketing') == 'on'
    if not email:
        flash("Email requis.", "error")
        return redirect(url_for('index'))
    try:
        print(f"--- NOUVEAU LEAD COLLECTÉ : {email} ---")
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute('INSERT OR REPLACE INTO leads (email, signup_date, marketing_consent, ip_address) VALUES (?, ?, ?, ?)', (email, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1 if accept_marketing else 0, request.remote_addr))
            conn.execute('INSERT INTO legal_audit (email, ip_address, consent_date, user_agent) VALUES (?, ?, ?, ?)', (email, request.remote_addr, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), request.user_agent.string))
        session['verified'] = True
        session['pending_email'] = email
        return redirect(url_for('analyze_page'))
    except Exception: return redirect(url_for('index'))

@app.route('/admin')
def admin_dashboard():
    admin_user = os.environ.get("ADMIN_USER", "admin")
    admin_pass = os.environ.get("ADMIN_PASS", "password123")
    auth = request.authorization
    if not auth or not (auth.username == admin_user and auth.password == admin_pass):
        return Response('Accès refusé.', 401, {'WWW-Authenticate': 'Basic realm="Login Required"'})
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email, signup_date, marketing_consent FROM leads ORDER BY signup_date DESC")
        leads = cursor.fetchall()
        cursor.execute("SELECT symbol, COUNT(*) FROM search_history GROUP BY symbol ORDER BY 2 DESC LIMIT 10")
        stats = cursor.fetchall()
    return render_template('admin.html', leads=leads, search_stats=stats, audit_logs=[])

@app.route('/analyze', methods=['GET'])
def analyze_page():
    if not session.get('verified'): return redirect(url_for('index'))
    symbol = request.args.get('symbol', '').upper().strip()
    context = {'recommendation': None, 'symbol': symbol, 'stock_news': [], 'sentiment_score': 0, 'insiders': []}
    if symbol:
        try:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT symbol FROM tickers WHERE name LIKE ? OR symbol = ?", (f'%{symbol}%', symbol))
                row = cursor.fetchone()
                if row: symbol = row[0]
        except Exception: pass
        df = get_stock_data(symbol)
        if df is None:
            try:
                search_results = yf.Search(symbol, max_results=1).tickers
                if search_results:
                    symbol = search_results[0]['symbol']
                    df = get_stock_data(symbol)
            except Exception: pass
        try:
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute('INSERT INTO search_history (email, symbol, found, timestamp) VALUES (?, ?, ?, ?)', (session.get('pending_email', 'inconnu'), symbol, 1 if df is not None else 0, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        except Exception: pass
        if df is not None:
            ticker_yf = yf.Ticker(symbol)
            info = ticker_yf.info
            try:
                with sqlite3.connect(DB_NAME) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT symbol FROM tickers WHERE symbol = ?", (symbol,))
                    if not cursor.fetchone():
                        name = info.get('longName') or info.get('shortName') or symbol
                        cursor.execute("INSERT INTO tickers (symbol, name) VALUES (?, ?)", (symbol, name))
            except Exception: pass
            insiders = []
            try:
                it = ticker_yf.insider_transactions
                if it is not None and not it.empty:
                    for _, row in it.head(5).iterrows():
                        insiders.append({'name': row.get('Insider', 'N/A'), 'position': row.get('Position', 'Dirigeant'), 'type': row.get('Transaction', 'Action'), 'date': str(row.get('Start Date', ''))})
            except Exception: pass
            raw_news = ticker_yf.news
            stock_news = []
            for article in raw_news[:15]:
                content = article.get('content', {})
                stock_news.append({'title': content.get('title'), 'link': content.get('link') or content.get('canonicalUrl', {}).get('url'), 'publisher': content.get('provider', {}).get('displayName'), 'date': pd.to_datetime(content.get('pubDate')).strftime('%Y-%m-%d %H:%M') if content.get('pubDate') else None})
            sentiment_score = analyze_news_sentiment(stock_news)
            reco, reason, rsi, st_f, mt_f, lt_f, st_t, mt_t, lt_t, entry, exit = analyze_stock(df, sentiment_score, info)
            analyst_reco_chart_div = None
            try:
                recos = ticker_yf.recommendations
                if recos is not None and not recos.empty:
                    latest = recos.iloc[-1]
                    labels = ['Vente Forte', 'Vente', 'Conserver', 'Achat', 'Achat Fort']
                    values = [latest.get('strongSell',0), latest.get('sell',0), latest.get('hold',0), latest.get('buy',0), latest.get('strongBuy',0)]
                    if sum(values) > 0:
                        fig_reco = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.3, marker_colors=['#212121', '#FF4500', '#A9A9A9', '#90EE90', '#228B22'])])
                        fig_reco.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=200, showlegend=True)
                        analyst_reco_chart_div = fig_reco.to_html(full_html=False, include_plotlyjs='cdn')
            except Exception: pass
            context.update({'last_close_price': df['close'].iloc[-1], 'daily_change': df['close'].iloc[-1] - df['close'].iloc[-2] if len(df)>1 else 0, 'daily_change_percent': ((df['close'].iloc[-1] - df['close'].iloc[-2])/df['close'].iloc[-2]*100) if len(df)>1 else 0, 'recommendation': reco, 'reason': reason, 'rsi_value': rsi, 'short_term_entry_price': f"{entry:.2f}" if entry else "N/A", 'short_term_exit_price': f"{exit:.2f}" if exit else "N/A", 'sma_200': df['SMA_200'].iloc[-1] if 'SMA_200' in df.columns else None, 'currency_symbol': info.get('currency', ''), 'stock_chart_div': create_stock_chart(df, symbol), 'analyst_reco_chart_div': analyst_reco_chart_div, 'stock_news': stock_news, 'sentiment_score': sentiment_score, 'insiders': insiders})
    return render_template('index.html', **context)

@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'GET': return redirect(url_for('analyze_page'))
    query = request.form.get('query', '').strip()
    if not query: return redirect(url_for('analyze_page'))
    symbol = query.upper()
    if len(query) > 2 and "." not in query:
        try:
            search_results = yf.Search(query, max_results=1).tickers
            if search_results: symbol = search_results[0]['symbol']
        except Exception: pass
    return redirect(url_for('analyze_page', symbol=symbol))

@app.route('/api/search_tickers', methods=['GET'])
def search_tickers():
    query = request.args.get('query', '').upper()
    if not query: return jsonify([])
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, name FROM tickers WHERE symbol LIKE ? OR name LIKE ? LIMIT 10", (f'%{query}%', f'%{query}%'))
        results = [{'symbol': row[0], 'name': row[1]} for row in cursor.fetchall()]
    return jsonify(results)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)