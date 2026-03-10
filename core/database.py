import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'users.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    # Activation du mode WAL pour la concurrence (lectures et écritures simultanées)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Table existante pour les utilisateurs
            cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                username TEXT UNIQUE, 
                password TEXT, 
                email TEXT UNIQUE, 
                email_verified INTEGER DEFAULT 0,
                verification_token TEXT,
                reset_token TEXT,
                failed_login_attempts INTEGER DEFAULT 0,
                lock_until TEXT,
                mfa_secret TEXT,
                mfa_enabled INTEGER DEFAULT 0,
                registered_devices TEXT,
                last_login TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Table pour le cache des news
            cursor.execute('''CREATE TABLE IF NOT EXISTS news_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                title TEXT,
                link TEXT,
                pubDate TEXT,
                source TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Table pour les actions suivies (watchlist)
            cursor.execute('''CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                symbol TEXT,
                name TEXT,
                sector TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(email, symbol)
            )''')
            
            # Table pour les leads
            cursor.execute('''CREATE TABLE IF NOT EXISTS leads (email TEXT PRIMARY KEY, signup_date TEXT, marketing_consent INTEGER DEFAULT 0, ip_address TEXT)''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS search_history (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT, symbol TEXT, found INTEGER, timestamp TEXT)''')
            
            # Nouvelle table pour les abonnements aux alertes
            cursor.execute('''CREATE TABLE IF NOT EXISTS alert_subscriptions (
                email TEXT,
                symbol TEXT,
                PRIMARY KEY (email, symbol)
            )''')
            
            # Liste des actions du CAC 40 pour initialisation
            cac40 = [
                ('^FCHI', 'CAC 40', 'Indices'), ('^SBF120', 'SBF 120', 'Indices'),
                ('AC.PA', 'Accor', 'Consommation'), ('AI.PA', 'Air Liquide', 'Industrie'),
                ('AIR.PA', 'Airbus', 'Aéronautique'), ('ALO.PA', 'Alstom', 'Industrie'),
                ('MT.AS', 'ArcelorMittal', 'Matériaux'), ('CS.PA', 'AXA', 'Finance'), ('BNP.PA', 'BNP Paribas', 'Finance'), ('EN.PA', 'Bouygues', 'Industrie'),
                ('CAP.PA', 'Capgemini', 'Technologie'), ('CA.PA', 'Carrefour', 'Consommation'), ('ACA.PA', 'Crédit Agricole', 'Finance'), ('BN.PA', 'Danone', 'Consommation'),
                ('DSY.PA', 'Dassault Systèmes', 'Technologie'), ('EDEN.PA', 'Edenred', 'Finance'), ('ENGI.PA', 'Engie', 'Services Publics'), ('EL.PA', 'EssilorLuxottica', 'Santé'),
                ('ERF.PA', 'Eurofins Scientific', 'Santé'), ('RMS.PA', 'Hermès', 'Luxe'), ('KER.PA', 'Kering', 'Luxe'), ('OR.PA', "L'Oréal", 'Consommation'),
                ('LR.PA', 'Legrand', 'Industrie'), ('MC.PA', 'LVMH', 'Luxe'), ('ML.PA', 'Michelin', 'Industrie'), ('ORA.PA', 'Orange', 'Télécoms'),
                ('PUB.PA', 'Publicis', 'Consommation'), ('RI.PA', 'Pernod Ricard', 'Consommation'), ('RNO.PA', 'Renault', 'Consommation'), ('SAF.PA', 'Safran', 'Aéronautique'),
                ('SGO.PA', 'Saint-Gobain', 'Industrie'), ('SAN.PA', 'Sanofi', 'Santé'), ('SU.PA', 'Schneider Electric', 'Industrie'), ('GLE.PA', 'Société Générale', 'Finance'),
                ('STLAP.PA', 'Stellantis', 'Consommation'), ('STMPA.PA', 'STMicroelectronics', 'Technologie'), ('TEP.PA', 'Teleperformance', 'Industrie'), ('HO.PA', 'Thales', 'Aéronautique'),
                ('TTE.PA', 'TotalEnergies', 'Énergie'), ('URW.PA', 'Unibail-Rodamco-Westfield', 'Immobilier'), ('VIE.PA', 'Veolia', 'Services Publics'), ('DG.PA', 'Vinci', 'Industrie'),
                ('WLN.PA', 'Worldline', 'Technologie')
            ]
            
            # On ne peuple pas ici pour éviter les doublons complexes, mais la table est prête
            conn.commit()
            return True
    except Exception as e:
        print(f"Erreur init_db: {e}")
        return False
