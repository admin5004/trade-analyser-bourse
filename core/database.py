import sqlite3
import logging

logger = logging.getLogger("TradingEngine.Database")
DB_NAME = "users.db"

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
    except Exception as e:
        logger.error(f"DB Error: {e}")

def get_db_connection():
    return sqlite3.connect(DB_NAME)
