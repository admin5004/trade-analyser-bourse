import os
import sqlite3
import random
import string
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import pandas as pd
import pandas_ta as ta
import yfinance as yf
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
import plotly.graph_objects as go
from textblob import TextBlob

# Initialisation de l'application Flask
app = Flask(__name__)
app.secret_key = os.urandom(24)  # Clé secrète pour les sessions sécurisées

# --- CONFIGURATION BASE DE DONNÉES ---
DB_NAME = "users.db"

def init_db():
    """Initialise la base de données pour les utilisateurs et l'audit."""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # Table pour stocker les codes de vérification temporaires
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS verification_codes (
                email TEXT PRIMARY KEY,
                code TEXT,
                timestamp REAL
            )
        ''')
        # Table pour l'audit légal (Consentements enregistrés)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS legal_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                ip_address TEXT,
                consent_date TEXT,
                user_agent TEXT
            )
        ''')
        conn.commit()

init_db()

# --- FONCTIONS UTILITAIRES (Email & Sécurité) ---

def generate_code(length=6):
    return ''.join(random.choices(string.digits, k=length))

def send_verification_email(email, code):
    """
    Envoie un email réel via Gmail en utilisant des variables d'environnement.
    """
    sender_email = os.environ.get("SENDER_EMAIL")
    password = os.environ.get("SENDER_PASSWORD")
    
    if not sender_email or not password:
        print(f"\n[MODE TEST] Code pour {email} : {code}\n")
        return True

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = email
        msg['Subject'] = "Votre code d'accès - Trading Analyzer Pro"
        
        body = f"Bonjour,\n\nVotre code de vérification est : {code}\n\nEn entrant ce code, vous confirmez avoir lu et accepté l'avertissement légal : ce programme est expérimental et ne constitue pas un conseil en investissement.\n\nL'équipe Trading Analyzer."
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Erreur d'envoi email: {e}")
        return False

# --- FONCTIONS MÉTIER (Analyse Bourse) ---

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
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="max")
        if df.empty: return None
        df.columns = [col.lower() for col in df.columns]
        df = df[['open', 'high', 'low', 'close', 'volume']]
        return df.sort_index()
    except Exception:
        return None

def analyze_stock(df, sentiment_score=0):
    # (Code d'analyse identique à précédemment, conservé pour la fiabilité)
    short_term_forecast = "Neutre"
    medium_term_forecast = "Neutre"
    long_term_forecast = "Neutre"
    short_term_target = "N/A"
    medium_term_target = "N/A"
    long_term_target = "N/A"

    if len(df) < 200:
        return "Conserver", "Données insuffisantes", None, "Neutre", "Neutre", "Neutre", "N/A", "N/A", "N/A", None, None

    df.ta.sma(length=60, append=True)
    df.ta.sma(length=100, append=True)
    df.ta.sma(length=200, append=True)
    df.ta.rsi(length=14, append=True)

    if len(df) < 2: return "Conserver", "Données insuffisantes", None, "Neutre", "Neutre", "Neutre", "N/A", "N/A", "N/A", None, None

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    mm60 = last_row['SMA_60']
    mm100 = last_row['SMA_100']
    mm200 = last_row['SMA_200']
    rsi = last_row['RSI_14']
    last_close_price = last_row['close']
    prev_mm60 = prev_row['SMA_60']
    prev_mm200 = prev_row['SMA_200']

    adjustment_factor = 1 + (sentiment_score * 0.05) 
    recommendation = "Conserver"
    reason = "Aucun signal fort détecté."

    if last_close_price > mm60:
        medium_term_forecast = "Haussière"
        medium_term_target = f"{mm60 * 1.05 * adjustment_factor:.2f}"
    elif last_close_price < mm60:
        medium_term_forecast = "Baissière"
        medium_term_target = f"{mm60 * 0.95 * adjustment_factor:.2f}"

    if mm60 > mm200 and prev_mm60 <= prev_mm200:
        long_term_forecast = "Haussière (Croisement Doré)"
        long_term_target = f"{mm200 * 1.1 * adjustment_factor:.2f}"
    elif mm60 < mm200 and prev_mm60 >= prev_mm200:
        long_term_forecast = "Baissière (Croisement de la Mort)"
        long_term_target = f"{mm200 * 0.9 * adjustment_factor:.2f}"
    elif last_close_price > mm200:
        long_term_forecast = "Haussière"
        long_term_target = f"{mm200 * 1.05 * adjustment_factor:.2f}"
    elif last_close_price < mm200:
        long_term_forecast = "Baissière"
        long_term_target = f"{mm200 * 0.95 * adjustment_factor:.2f}"

    if mm60 > mm200 and rsi < 30:
        recommendation = "Achat"
        reason = f"Signal technique fort : Croisement haussier et RSI en survente. Sentiment : {'Positif' if sentiment_score > 0.1 else 'Négatif' if sentiment_score < -0.1 else 'Neutre'}."
    elif mm60 < mm200 and rsi > 70:
        recommendation = "Vente"
        reason = f"Signal de vente : Croisement baissier et RSI en surachat. Sentiment : {'Positif' if sentiment_score > 0.1 else 'Négatif' if sentiment_score < -0.1 else 'Neutre'}."
    
    suggested_entry_price = last_close_price * (1 - (sentiment_score * 0.02)) if rsi < 40 else mm60 * (1 - (sentiment_score * 0.01))
    suggested_exit_price = last_close_price * 1.02 * adjustment_factor if rsi > 60 else mm60 * 1.10 * adjustment_factor

    return recommendation, reason, rsi, short_term_forecast, medium_term_forecast, long_term_forecast, short_term_target, medium_term_target, long_term_target, suggested_entry_price, suggested_exit_price

def create_stock_chart(df, symbol):
    fig = go.Figure(data=[go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Cours')])
    if 'SMA_60' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_60'], mode='lines', name='MM60', line=dict(color='blue', width=1)))
    if 'SMA_100' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_100'], mode='lines', name='MM100', line=dict(color='orange', width=1)))
    if 'SMA_200' in df.columns: fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], mode='lines', name='MM200', line=dict(color='red', width=1)))
    fig.update_layout(title=f'Historique {symbol}', yaxis_title='Prix', height=600, margin=dict(l=20, r=20, t=40, b=20), xaxis_rangeslider_visible=False)
    return fig.to_html(full_html=False, include_plotlyjs='cdn')

# --- ROUTES AUTHENTIFICATION ---

@app.route('/')
def index():
    if session.get('verified'):
        return redirect(url_for('analyze_page'))
    return render_template('welcome.html')

@app.route('/send_code', methods=['POST'])
def send_code():
    email = request.form.get('email')
    if not email:
        flash("Email requis.", "error")
        return redirect(url_for('index'))
    
    code = generate_code()
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute('INSERT OR REPLACE INTO verification_codes (email, code, timestamp) VALUES (?, ?, ?)', 
                     (email, code, time.time()))
    
    send_verification_email(email, code)
    session['pending_email'] = email
    flash(f"Code envoyé à {email}. (Regardez la console serveur pour le code en mode test)", "success")
    return render_template('welcome.html', step='verify')

@app.route('/verify_code', methods=['POST'])
def verify_code():
    email = session.get('pending_email')
    code_input = request.form.get('code')
    
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT code FROM verification_codes WHERE email = ?', (email,))
        row = cursor.fetchone()
        
    if row and row[0] == code_input:
        # Enregistrement Audit Légal
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute('INSERT INTO legal_audit (email, ip_address, consent_date, user_agent) VALUES (?, ?, ?, ?)',
                         (email, request.remote_addr, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), request.user_agent.string))
        
        session['verified'] = True
        return redirect(url_for('analyze_page'))
    else:
        flash("Code incorrect.", "error")
        return render_template('welcome.html', step='verify')

# --- ROUTE PRINCIPALE ---

@app.route('/analyze', methods=['GET'])
def analyze_page():
    if not session.get('verified'):
        return redirect(url_for('index'))

    symbol = request.args.get('symbol', None)
    
    # Variables par défaut
    context = {
        'recommendation': None, 'symbol': symbol, 'stock_news': [], 'sentiment_score': 0
    }

    SECTOR_PE_AVG = {'USA': {'Technology': 28.2}, 'Europe': {'Technology': 25.5}} # Simplifié
    
    if symbol:
        symbol = symbol.upper()
        df = get_stock_data(symbol)
        
        if df is not None:
            ticker_yf = yf.Ticker(symbol)
            info = ticker_yf.info
            
            # News & Sentiment
            raw_news = ticker_yf.news
            stock_news = []
            for article in raw_news[:5]:
                content = article.get('content', {})
                stock_news.append({
                    'title': content.get('title'),
                    'link': content.get('link') or content.get('canonicalUrl', {}).get('url'),
                    'publisher': content.get('provider', {}).get('displayName'),
                    'date': pd.to_datetime(content.get('pubDate')).strftime('%Y-%m-%d %H:%M') if content.get('pubDate') else None
                })
            sentiment_score = analyze_news_sentiment(stock_news)
            
            # Analyse
            reco, reason, rsi, st_f, mt_f, lt_f, st_t, mt_t, lt_t, entry, exit = analyze_stock(df, sentiment_score)
            
            # Reco Analystes (Chart)
            analyst_reco_chart_div = None
            analyst_reco_date = None
            try:
                recos = ticker_yf.recommendations
                if recos is not None and not recos.empty:
                    latest = recos.iloc[-1]
                    analyst_reco_date = recos.index[-1].strftime('%d/%m/%Y') if hasattr(recos.index[-1], 'strftime') else None
                    labels = ['Vente Forte', 'Vente', 'Conserver', 'Achat', 'Achat Fort']
                    values = [latest.get('strongSell',0), latest.get('sell',0), latest.get('hold',0), latest.get('buy',0), latest.get('strongBuy',0)]
                    
                    # COULEURS ET LAYOUT MODIFIÉ (Légende à droite)
                    colors = ['#212121', '#FF4500', '#A9A9A9', '#90EE90', '#228B22']
                    if sum(values) > 0:
                        fig_reco = go.Figure(data=[go.Pie(labels=labels, values=values, hole=.3, marker_colors=colors)])
                        fig_reco.update_layout(
                            margin=dict(t=0, b=0, l=0, r=0),
                            height=200,
                            showlegend=True,
                            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.1) # Légende à droite
                        )
                        analyst_reco_chart_div = fig_reco.to_html(full_html=False, include_plotlyjs='cdn')
            except Exception: pass

            # Update Context
            context.update({
                'last_close_price': df['close'].iloc[-1],
                'daily_change': df['close'].iloc[-1] - df['close'].iloc[-2] if len(df)>1 else 0,
                'daily_change_percent': ((df['close'].iloc[-1] - df['close'].iloc[-2])/df['close'].iloc[-2]*100) if len(df)>1 else 0,
                'recommendation': reco, 'reason': reason, 'rsi_value': rsi,
                'short_term_entry_price': f"{entry:.2f}" if entry else "N/A",
                'short_term_exit_price': f"{exit:.2f}" if exit else "N/A",
                'sma_60': df['SMA_60'].iloc[-1] if 'SMA_60' in df.columns else None,
                'sma_100': df['SMA_100'].iloc[-1] if 'SMA_100' in df.columns else None,
                'sma_200': df['SMA_200'].iloc[-1] if 'SMA_200' in df.columns else None,
                'pe_ratio': info.get('trailingPE'), 'currency_symbol': info.get('currency', ''),
                'stock_chart_div': create_stock_chart(df, symbol),
                'analyst_reco_chart_div': analyst_reco_chart_div,
                'analyst_reco_date': analyst_reco_date,
                'stock_news': stock_news, 'sentiment_score': sentiment_score
            })

    return render_template('index.html', **context)

@app.route('/search', methods=['POST'])
def search():
    return redirect(url_for('analyze_page', symbol=request.form.get('query', '').strip().upper()))

@app.route('/api/search_tickers', methods=['GET'])
def search_tickers():
    query = request.args.get('query', '').upper()
    stocks = [{'symbol': 'CAP.PA', 'name': 'Capgemini'}, {'symbol': 'MC.PA', 'name': 'LVMH'}, {'symbol': 'AAPL', 'name': 'Apple'}] # Liste réduite pour l'exemple
    return jsonify([s for s in stocks if query in s['symbol'] or query in s['name'].upper()])

@app.route('/search_redirect/<symbol>')
def search_redirect(symbol):
    return redirect(url_for('analyze_page', symbol=symbol))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)