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

# Importation du nouveau processeur IA
from core.ml_processor import MLPredictor 

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
# Sécurité des sessions
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True, # Puisque vous utilisez le HTTPS Freebox
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7)
)
VERSION = "4.0.0 (Modular Edition)"

# Verrouillage pour l'entraînement automatique
training_locks = set()
t_lock = threading.Lock()

# Initialisation de la DB au démarrage
init_db()

# Instance du nouveau modèle IA
ml_predictor = MLPredictor()

# --- SCHEDULER ---
scheduler = BackgroundScheduler()
# On ajoute le job avec next_run_time=datetime.now() pour qu'il démarre immédiatement
scheduler.add_job(func=fetch_market_data_job, trigger=IntervalTrigger(minutes=20), id='mkt_job', next_run_time=datetime.now())
# Planification de l'entraînement des modèles IA s'ils n'existent pas encore ou pour les mettre à jour périodiquement
# Ici, on l'exécute une fois au démarrage si les modèles ne sont pas trouvés
def train_models_if_needed():
    symbols_to_train = ["AI.PA", "MC.PA", "MC.PA", "OR.PA", "SAN.PA", "ACA.PA", "BNP.PA", "GLE.PA", "CS.PA", "ABI.PA", "VIE.PA"] # Exemple de quelques symboles
    for symbol in symbols_to_train:
        for horizon in ml_predictor.horizons.keys():
            model_path = os.path.join(ml_predictor.model_dir, f"{symbol}_{horizon}.joblib")
            if not os.path.exists(model_path):
                logger.info(f"Modèle pour {symbol} horizon {horizon} non trouvé, entraînement...")
                ml_predictor.train_for_horizons(symbol)
                break # Entraîner pour ce symbole une fois suffit si on trouve un modèle manquant

scheduler.add_job(func=train_models_if_needed, trigger=IntervalTrigger(days=1), id='train_job', next_run_time=datetime.now() + timedelta(minutes=5)) # Entraînement quotidien après le démarrage

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

    # Initialisation systématique des variables de contexte avec des valeurs par défaut
    sentiment_label = "Neutre"
    sentiment_score = 0
    daily_editorial = "Analyse du marché en cours..."
    global_sentiment_label = "Neutre"
    ai_tip = "Surveillez les points de pivot sur vos valeurs préférées."
    top_sectors, heatmap_data, market_indices, geopolitics = [], [], {}, {}

    try:
        top_sectors, heatmap_data, market_indices, geopolitics, daily_editorial, global_sentiment_label, ai_tip = get_global_context()
    except Exception as e:
        logger.error(f"Error fetching global context: {e}")

    if not symbol:
        return render_template('index.html', symbol="", last_close_price=None, top_sectors=top_sectors, heatmap_data=heatmap_data, market_indices=market_indices, geopolitics=geopolitics, version=VERSION, daily_editorial=daily_editorial, global_sentiment_label=global_sentiment_label, ai_tip=ai_tip, last_update=MARKET_STATE['last_update'])
    # Récupération DATA depuis le cache
    with market_lock:
        info = MARKET_STATE['tickers'].get(symbol)
        df = MARKET_STATE['dataframes'].get(symbol)

    news_list = []
    analyst_info = "N/A"
    sentiment_label = "Neutre"
    
    # Force sync fetch if not in cache or if cache is empty skeleton
    if df is None or (info and info.get('price', 0) == 0):
        try:
            ticker_obj = yf.Ticker(symbol)
            df = ticker_obj.history(period="1y") # On garde 1 an pour l'analyse technique visuelle
            
            # Récupération sécurisée des actualités
            news_list = []
            try:
                if ticker_obj.news:
                    news_list = ticker_obj.news[:5]
            except: 
                logger.warning(f"Impossible de récupérer les news pour {symbol}")
            
            # Récupération des objectifs de cours des analystes
            target_price = "N/A"
            try:
                target_price = ticker_obj.info.get('targetMeanPrice', 'N/A')
                raw_reco = ticker_obj.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
                analyst_info = ANALYST_MAP.get(raw_reco, raw_reco)
            except: pass
            
            if df is not None and not df.empty:
                df.columns = [col.lower() for col in df.columns]
                reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
                
                # Récupération d'infos enrichies pour l'auto-enregistrement
                long_name = symbol
                sector = "Divers"
                try:
                    long_name = ticker_obj.info.get('longName', symbol)
                    sector = ticker_obj.info.get('sector', ticker_obj.info.get('quoteType', 'Inconnu'))
                except: pass

                info = {
                    'price': float(df['close'].iloc[-1]),
                    'change_pct': ((df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2] * 100) if len(df) > 1 else 0,
                    'recommendation': reco, 'reason': reason, 'rsi': rsi, 'mm20': mm20, 'mm50': mm50, 'mm200': mm200,
                    'targets': {'entry': entry, 'exit': exit}, 'sector': sector, 'analyst_reco': analyst_info
                }

                # AUTO-ENREGISTREMENT en base de données pour suivi futur
                try:
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("INSERT OR IGNORE INTO tickers (symbol, name, sector) VALUES (?, ?, ?)", (symbol, long_name, sector))
                        conn.commit()
                        logger.info(f"✅ Auto-enregistrement de {symbol} ({long_name}) réussi.")
                except Exception as db_err:
                    logger.error(f"Erreur auto-enregistrement {symbol}: {db_err}")
        except Exception as e:
            logger.error(f"Sync fetch error for {symbol}: {e}")
    else:
        # Si on a les données du cache, on tente de récupérer la reco analyste et les news
        news_list = []
        try:
            ticker_obj = yf.Ticker(symbol)
            if ticker_obj.news:
                news_list = ticker_obj.news[:5]
            
            analyst_info = info.get('analyst_reco', 'N/A')
            if analyst_info == 'N/A':
                raw_reco = ticker_obj.info.get('recommendationKey', 'N/A').replace('_', ' ').title()
                analyst_info = ANALYST_MAP.get(raw_reco, raw_reco)
            
            target_price = info.get('target_price', 'N/A')
            if target_price == 'N/A':
                target_price = ticker_obj.info.get('targetMeanPrice', 'N/A')
        except: pass

    sentiment_score, sentiment_label = analyze_sentiment(news_list)
    
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
    ai_predictions = None
    if info and df is not None and not df.empty:
        try:
            # Utilise le nouveau modèle pour obtenir des prédictions multi-horizons
            ai_predictions = ml_predictor.predict_future(symbol) 
            
            # Suppression de l'auto-train ici pour éviter de saturer la RAM du serveur web
            if not ai_predictions:
                ai_predictions = {h: "En attente" for h in ml_predictor.horizons.keys()}
        except Exception as e:
            logger.error(f"Error getting AI predictions for {symbol}: {e}")
            ai_predictions = {h: "N/A" for h in ml_predictor.horizons.keys()}
    else:
        ai_predictions = {h: "Données insuffisantes" for h in ml_predictor.horizons.keys()}

    # Calcul sécurisé de la cible IA
    ia_target_val = "N/A"
    try:
        if info and info.get('price') and ai_predictions and isinstance(ai_predictions.get('1m'), (int, float)):
            ia_target_val = info.get('price') * (1 + ai_predictions['1m'] / 100)
    except: pass

    # Préparation sécurisée du contexte pour éviter les erreurs 500
    try:
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
            'short_term_entry_price': f"{info.get('targets', {}).get('entry', 0):.2f}" if info and isinstance(info.get('targets'), dict) else "N/A",
            'short_term_exit_price': f"{info.get('targets', {}).get('exit', 0):.2f}" if info and isinstance(info.get('targets'), dict) else "N/A",
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
            'analyst_target': target_price,
            'ia_target_1m': ia_target_val,
            'sentiment_score': sentiment_score, 
            'sentiment_label': sentiment_label,
            'global_sentiment_label': global_sentiment_label,
            'geopolitics': geopolitics,
            'ai_predictions': ai_predictions,
            'market_indices': market_indices,
            'daily_editorial': daily_editorial,
            'ai_tip': ai_tip
        }
        return render_template('index.html', **context)
    except Exception as e:
        logger.error(f"Critical error rendering template for {symbol}: {e}", exc_info=True)
        return render_template('index.html', 
            symbol=symbol, 
            error="Une erreur est survenue lors de l'analyse.", 
            version=VERSION, 
            top_sectors=top_sectors, 
            heatmap_data=heatmap_data, 
            market_indices=market_indices, 
            geopolitics=geopolitics,
            daily_editorial=daily_editorial,
            global_sentiment_label=global_sentiment_label,
            ai_tip=ai_tip,
            last_update=MARKET_STATE['last_update']
        )

@app.route('/subscriptions', methods=['GET', 'POST'])
def ultra_subscriptions():
    # TEMPORAIRE : On utilise un email par défaut ou la session si dispo
    email = session.get('email') or session.get('pending_email')
    if not email:
        flash("Veuillez vous connecter pour gérer vos alertes", "error")
        return redirect(url_for('ultra_home'))
        
    if request.method == 'POST':
        selected_symbols = request.form.getlist('symbols')
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                # On nettoie les anciens abonnements
                cursor.execute("DELETE FROM alert_subscriptions WHERE email = ?", (email,))
                # On ajoute les nouveaux
                for sym in selected_symbols:
                    cursor.execute("INSERT INTO alert_subscriptions (email, symbol) VALUES (?, ?)", (email, sym))
                conn.commit()
            flash("Vos préférences d'alertes ont été mises à jour !", "success")
        except Exception as e:
            logger.error(f"Error updating subscriptions for {email}: {e}")
            flash("Erreur lors de la mise à jour", "error")

    # Récupération de tous les tickers et des abonnements actuels
    all_tickers = []
    current_subs = []
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, name, sector FROM tickers ORDER BY symbol")
            all_tickers = [{'symbol': r[0], 'name': r[1], 'sector': r[2]} for r in cursor.fetchall()]
            
            cursor.execute("SELECT symbol FROM alert_subscriptions WHERE email = ?", (email,))
            current_subs = [r[0] for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"Error fetching subscription data: {e}")

    return render_template('subscriptions.html', tickers=all_tickers, subs=current_subs, email=email)

@app.route('/sectors')
def ultra_sectors():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sector, COUNT(*) as count FROM tickers GROUP BY sector ORDER BY count DESC")
            sectors_data = [{"name": r[0], "count": r[1]} for r in cursor.fetchall() if r[0]]
            
        top_sectors, heatmap_data, market_indices, geopolitics, daily_editorial, global_sentiment_label, ai_tip = get_global_context()
        
        return render_template('sectors.html', sectors=sectors_data, version=VERSION, last_update=MARKET_STATE['last_update'], market_indices=market_indices)
    except Exception as e:
        logger.error(f"Error in sectors route: {e}")
        return redirect(url_for('ultra_analyze'))

@app.route('/sector/<name>')
def ultra_sector_view(name):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, name, sector FROM tickers WHERE sector = ? ORDER BY symbol", (name,))
            tickers = []
            for sym, full_name, sec in cursor.fetchall():
                with market_lock:
                    info = MARKET_STATE['tickers'].get(sym, {})
                tickers.append({
                    "symbol": sym,
                    "name": full_name,
                    "price": info.get('price', 0),
                    "change": info.get('change_pct', 0),
                    "reco": info.get('recommendation', 'N/A')
                })
        
        top_sectors, heatmap_data, market_indices, geopolitics, daily_editorial, global_sentiment_label, ai_tip = get_global_context()
        
        return render_template('sector_view.html', sector_name=name, tickers=tickers, version=VERSION, last_update=MARKET_STATE['last_update'], market_indices=market_indices)
    except Exception as e:
        logger.error(f"Error in sector view route: {e}")
        return redirect(url_for('ultra_sectors'))

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
