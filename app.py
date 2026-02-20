import os
import random
import string
import threading
import logging
import re
import secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import yfinance as yf

# Importations de nos modules core
from core.database import init_db, get_db_connection
from core.analysis import analyze_stock, analyze_sentiment, create_stock_chart
from core.market import MARKET_STATE, market_lock, fetch_market_data_job, get_global_context
from core.legal import get_company_legal_info
from core.news import get_combined_news
from core.auth import hash_password, check_password, generate_code, generate_token, register_device, is_device_recognized
from core.mailer import send_auth_email
from core.ai_engine import ai_brain

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

ANALYST_MAP = {
    'Strong Buy': 'Achat Fort',
    'Buy': 'Achat',
    'Hold': 'Conserver',
    'Sell': 'Vendre',
    'Strong Sell': 'Vente Forte',
    'Underperform': 'Sous-performer',
    'Outperform': 'Sur-performer',
    'Neutral': 'Neutre',
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradingApp")

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
# On s'assure d'avoir une clé secrète pour les sessions
# Utilisation de la variable d'environnement ou d'une clé aléatoire sécurisée
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(24)
VERSION = "4.0.0 (Modular Edition)"

# Initialisation de la DB au démarrage
init_db()

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
# On ajoute le job avec next_run_time=datetime.now() pour qu'il démarre immédiatement
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=20), id='mkt_job', next_run_time=datetime.now())
scheduler.start()

# --- ROUTES ---

@app.route('/')
def ultra_home():
    # TEMPORAIRE : Accès libre sans authentification
    return redirect(url_for('ultra_analyze'))
    # if session.get('user_id') and session.get('device_verified'):
    #    return redirect(url_for('ultra_analyze'))
    # return render_template('welcome.html')

@app.route('/register', methods=['GET', 'POST'])
def ultra_register():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        if not email or not password:
            flash("Champs obligatoires manquants", "error")
            return redirect(url_for('ultra_register'))
            
        hashed = hash_password(password)
        token = generate_token()
        
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)", 
                             (email, hashed, datetime.now().isoformat()))
                cursor.execute("INSERT OR REPLACE INTO activation_codes (email, code, type, expires_at) VALUES (?, ?, ?, ?)",
                             (email, token, 'activation', (datetime.now() + timedelta(hours=24)).isoformat()))
                conn.commit()
            
            # On utilise le nom de domaine pour les liens externes
            base_url = "https://aibourse.freeboxos.fr" # ou http si vous n'avez pas encore de SSL
            activation_link = f"{base_url}/activate/{token}"
            subject = "Activation de votre compte Trading Analyzer"
            body = f"Cliquez ici pour activer votre compte : <a href='{activation_link}'>{activation_link}</a>"
            
            if send_auth_email(email, subject, body):
                flash("Lien d'activation envoyé par email !", "success")
            else:
                logger.warning(f"Email d'activation non envoyé à {email}. Lien : {activation_link}")
                flash("Compte créé, mais l'envoi du mail a échoué. Contactez l'admin.", "error")
                
            return redirect(url_for('ultra_home'))
        except Exception as e:
            flash("Cet email est déjà utilisé", "error")
            return redirect(url_for('ultra_register'))
            
    return render_template('register.html')

@app.route('/activate/<token>')
def ultra_activate(token):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM activation_codes WHERE code = ? AND type = 'activation'", (token,))
            row = cursor.fetchone()
            if row:
                email = row[0]
                cursor.execute("UPDATE users SET is_active = 1 WHERE email = ?", (email,))
                cursor.execute("DELETE FROM activation_codes WHERE email = ?", (email,))
                conn.commit()
                flash("Compte activé ! Vous pouvez vous connecter.", "success")
            else:
                flash("Lien invalide ou expiré", "error")
    except Exception:
        flash("Erreur lors de l'activation", "error")
    return redirect(url_for('ultra_home'))

@app.route('/login', methods=['POST'])
def ultra_login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, password_hash, is_active FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        
    if not user or not check_password(password, user[1]):
        flash("Identifiants incorrects", "error")
        return redirect(url_for('ultra_home'))
        
    if not user[2]:
        flash("Veuillez activer votre compte via le lien reçu par email", "error")
        return redirect(url_for('ultra_home'))

    # Génération du code 2FA
    code = generate_code()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO activation_codes (email, code, type, expires_at) VALUES (?, ?, ?, ?)",
                     (email, code, 'login', (datetime.now() + timedelta(minutes=10)).isoformat()))
        conn.commit()
        
    subject = f"Votre code de connexion : {code}"
    body = f"Saisissez ce code pour valider votre connexion : <strong>{code}</strong> (Valable 10 min)"
    
    send_auth_email(email, subject, body)
    logger.info(f"CODE LOGIN POUR {email} : {code}") # Pour dépannage
    
    session['pending_email'] = email
    session['pending_user_id'] = user[0]
    return redirect(url_for('ultra_verify_page'))

@app.route('/forgot-password', methods=['GET', 'POST'])
def ultra_forgot_password():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()
            
        if user:
            token = generate_token()
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO activation_codes (email, code, type, expires_at) VALUES (?, ?, ?, ?)",
                             (email, token, 'reset', (datetime.now() + timedelta(hours=1)).isoformat()))
                conn.commit()
            
            reset_url = url_for('ultra_reset_password', token=token, _external=True)
            subject = "Réinitialisation de votre mot de passe"
            body = f"Cliquez sur le lien suivant pour réinitialiser votre mot de passe : <a href='{reset_url}'>{reset_url}</a> (Lien valable 1 heure)"
            send_auth_email(email, subject, body)
            
        flash("Si cet email existe, un lien de réinitialisation a été envoyé.", "success")
        return redirect(url_for('ultra_forgot_password'))
        
    return render_template('forgot_password.html')

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def ultra_reset_password(token):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM activation_codes WHERE code = ? AND type = 'reset' AND expires_at > ?", 
                     (token, datetime.now().isoformat()))
        row = cursor.fetchone()
        
    if not row:
        flash("Lien invalide ou expiré", "error")
        return redirect(url_for('ultra_home'))
        
    email = row[0]
    
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm = request.form.get('confirm_password', '').strip()
        
        if not password or password != confirm:
            flash("Les mots de passe ne correspondent pas", "error")
            return render_template('reset_password.html')
            
        hashed = hash_password(password)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET password_hash = ? WHERE email = ?", (hashed, email))
            cursor.execute("DELETE FROM activation_codes WHERE email = ? AND type = 'reset'", (email,))
            conn.commit()
            
        flash("Votre mot de passe a été réinitialisé avec succès.", "success")
        return redirect(url_for('ultra_home'))
        
    return render_template('reset_password.html')

@app.route('/verify-code', methods=['GET', 'POST'])
def ultra_verify_page():
    email = session.get('pending_email')
    if not email: return redirect(url_for('ultra_home'))
    
    if request.method == 'POST':
        code = request.form.get('code', '').strip()
        device_name = request.form.get('device_name', 'Terminal inconnu')
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT email FROM activation_codes WHERE email = ? AND code = ? AND type = 'login'", (email, code))
            if cursor.fetchone():
                user_id = session.get('pending_user_id')
                # Enregistrement du terminal (simple ID basé sur le nom pour l'instant)
                device_id = "".join(secrets.choice(string.ascii_letters) for _ in range(16))
                register_device(user_id, device_id, device_name)
                
                session['user_id'] = user_id
                session['device_verified'] = True
                session['verified'] = True # Pour compatibilité ancienne
                
                # On place un cookie de terminal
                resp = redirect(url_for('ultra_analyze'))
                resp.set_cookie('device_id', device_id, max_age=30*24*3600) # 30 jours
                return resp
            else:
                flash("Code incorrect", "error")
                
    return render_template('verify.html', email=email)

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
    # TEMPORAIRE : Désactivation de la vérification de session
    # if not session.get('verified'): return redirect(url_for('ultra_home'))
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
            ticker_obj = yf.Ticker(symbol)
            df = ticker_obj.history(period="1y")
            news_list = ticker_obj.news[:5] if ticker_obj.news else []
            try:
                raw_reco = ticker_obj.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
                analyst_info = ANALYST_MAP.get(raw_reco, raw_reco)
            except: pass
            
            if df is not None and not df.empty:
                df.columns = [col.lower() for col in df.columns]
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                info = {
                    'price': float(df['close'].iloc[-1]),
                    'change_pct': ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0,
                    'recommendation': reco, 'reason': reason, 'rsi': rsi, 'mm20': mm20, 'mm50': mm50, 'mm200': mm200,
                    'targets': {'entry': entry, 'exit': exit}, 'sector': 'Autre', 'analyst_reco': analyst_info
                }
        except Exception as e:
            logger.error(f"Sync fetch error for {symbol}: {e}")
    else:
        # Si on a les données du cache, on tente de récupérer la reco analyste
        try:
            analyst_info = info.get('analyst_reco', 'N/A')
            if analyst_info == 'N/A':
                ticker_obj = yf.Ticker(symbol)
                raw_reco = ticker_obj.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
                analyst_info = ANALYST_MAP.get(raw_reco, raw_reco)
        except: pass
        df.columns = [col.lower() for col in df.columns]
        analyze_stock(df)

    sentiment_score, sentiment_label = analyze_sentiment(news_list)
    top_sectors, _ = get_global_context()
    
    # Infos Légales (Site Web)
    legal_info = get_company_legal_info(symbol)
    if info: # S'assurer que 'info' existe avant d'y ajouter des clés
        info['legal_info'] = legal_info
        info['sentiment_score'] = sentiment_score
        info['sentiment_label'] = sentiment_label
    current_sector = info.get('sector', 'N/A') if info else 'N/A'
    
    # Récupération des valeurs du même secteur
    sector_peers = []
    if current_sector != 'N/A':
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT symbol, name FROM tickers WHERE sector = ? AND symbol != ?", (current_sector, symbol))
                peers = cursor.fetchall()
                
                with market_lock:
                    for p_sym, p_name in peers:
                        p_info = MARKET_STATE['tickers'].get(p_sym)
                        if p_info and p_info.get('price', 0) > 0:
                            sector_peers.append({
                                'symbol': p_sym,
                                'name': p_name,
                                'price': p_info.get('price'),
                                'reco': p_info.get('recommendation', 'N/A'),
                                'entry': p_info.get('targets', {}).get('entry', 'N/A'),
                                'exit': p_info.get('targets', {}).get('exit', 'N/A'),
                                'change': p_info.get('change_pct', 0)
                            })
        except Exception as e:
            logger.error(f"Error fetching sector peers: {e}")

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

    # --- Prédiction de l'IA ---
    ai_prediction = None
    confidence = 0
    ai_reco_next_session = "N/A"
    ai_reco_confidence = 0
    ai_analysis_data = None

    if info and df is not None and not df.empty:
        # Passer le prix actuel, le volume du dernier point et le symbole à l'IA
        ai_prediction, confidence = ai_brain.get_prediction(info.get('price', 0), df['volume'].iloc[-1], symbol)
        ai_reco_next_session, ai_reco_confidence = ai_brain.get_next_session_recommendation(symbol)
        
        # Récupérer les détails de l'analyse pour le template
        recent_events = [e for e in ai_brain.memory if e.get('symbol') == symbol and 'analysis' in e]
        if recent_events:
            ai_analysis_data = recent_events[-1]['analysis']
    
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
        'sector_peers': sector_peers,
        'heatmap_data': heatmap_data, 
        'engine_status': 'ONLINE', 
        'version': VERSION,
        'last_update': MARKET_STATE['last_update'], 
        'news': news_list, 
        'website_url': legal_info.get('website') if legal_info else None,
        'analyst_recommendation': analyst_info,
        'sentiment_score': sentiment_score, 
        'sentiment_label': sentiment_label,
        'ai_prediction': ai_prediction,
        'ai_confidence': confidence,
        'ai_reco_next_session': ai_reco_next_session,
        'ai_reco_confidence': ai_reco_confidence,
        'ai_analysis': ai_analysis_data
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
    # Le cycle initial est maintenant géré uniquement par APScheduler (next_run_time=now)
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port, use_reloader=False, threaded=True)
