import yfinance as yf
import threading
import logging
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from .database import get_db_connection
from .analysis import analyze_stock
from .memory_manager import save_event_to_memory
import sys
import os

# Import dynamique pour éviter les cycles ou si le fichier est à la racine
sys.path.append('/home/corentin/trade-analyser-bourse')
try:
    from intel_correlator import correlate_and_analyze
except ImportError:
    correlate_and_analyze = None

from .alerts import scan_for_critical_alerts
from .geopolitics import analyze_global_risk

logger = logging.getLogger("TradingEngine.Market")

market_lock = threading.Lock()
MARKET_STATE = {
    'last_update': None,
    'tickers': {},  
    'dataframes': {},
    'sectors': {},
    'geopolitics': {
        'risk_score': 50,
        'verdict': "Initialisation...",
        'top_events': []
    },
    'last_error': None
}

def process_single_symbol(symbol, sector_name):
    """Analyse un seul symbole avec sécurité de timeout."""
    try:
        ticker = yf.Ticker(symbol)
        # Timeout strict de 10s pour Yahoo Finance (Évite de bloquer les workers)
        df = ticker.history(period="1y", timeout=10)
        
        if df is None or df.empty:
            logger.warning(f"No data for {symbol}")
            return symbol, None, None
        
        # On aplatit les colonnes si c'est un MultiIndex (nouveauté yfinance)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]
        df.columns = [str(col).lower() for col in df.columns]
        close_now = df['close'].iloc[-1]
        close_prev = df['close'].iloc[-2] if len(df) > 1 else close_now
        change_pct = ((close_now - close_prev) / close_prev * 100) if close_prev != 0 else 0
        
        # Fundamentals
        pe, dy = None, None
        try:
            info_data = ticker.info
            pe = info_data.get('trailingPE')
            raw_yield = info_data.get('dividendYield')
            if raw_yield:
                dy = float(raw_yield) if raw_yield > 1.0 else float(raw_yield) * 100
        except: pass

        reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
        
        ticker_data = {
            'price': float(close_now),
            'change_pct': float(change_pct),
            'sector': sector_name,
            'recommendation': reco,
            'reason': reason,
            'rsi': rsi,
            'mm20': mm20,
            'mm50': mm50,
            'mm200': mm200,
            'targets': {'entry': entry, 'exit': exit},
            'pe': pe,
            'yield': dy,
            'vol_spike': 1.0
        }

        # Mise à jour immédiate du cache global si appelée hors job global
        with market_lock:
            MARKET_STATE['tickers'][symbol] = ticker_data
            MARKET_STATE['dataframes'][symbol] = df

        # --- DÉTECTION ÉVÉNEMENT MÉMOIRE ---
        if abs(change_pct) >= 0.5:
            save_event_to_memory(symbol, float(close_now), int(df['volume'].iloc[-1]), float(change_pct), "PRICE_MOVE")

        return symbol, ticker_data, df
    except Exception as e:
        logger.warning(f"Failed {symbol}: {e}")
        return symbol, {'price': 0, 'change_pct': 0, 'sector': sector_name, 'vol_spike': 1.0}, None

def fetch_market_data_job():
    logger.info("📡 ENGINE: Cycle started (Parallel Mode)...")
    symbols_info = {}
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM tickers")
            for row in cursor.fetchall(): symbols_info[row[0]] = row[1]
    except Exception as e:
        logger.error(f"Database error: {e}")
        return
    
    symbols = list(symbols_info.keys())
    temp_tickers, temp_dfs = {}, {}
    
    # Parallélisation avec un maximum de 5 workers pour ne pas se faire bannir par yfinance
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_symbol = {executor.submit(process_single_symbol, s, symbols_info[s]): s for s in symbols}
        for future in as_completed(future_to_symbol):
            symbol, ticker_data, df = future.result()
            temp_tickers[symbol] = ticker_data
            if df is not None:
                temp_dfs[symbol] = df
            
    with market_lock:
        MARKET_STATE['tickers'].update(temp_tickers)
        MARKET_STATE['dataframes'].update(temp_dfs)
        MARKET_STATE['last_update'] = datetime.now().isoformat()
        
        # --- ANALYSE GÉOPOLITIQUE GLOBALE ---
        try:
            logger.info("🌍 GEOPOLITICS: Analyzing global risk...")
            risk_score, verdict, top_events = analyze_global_risk()
            MARKET_STATE['geopolitics'] = {
                'risk_score': risk_score,
                'verdict': verdict,
                'top_events': top_events
            }
        except Exception as e:
            logger.error(f"Geopolitics Analysis Error: {e}")
    
    # --- LANCEMENT ANALYSE IA ---
    if correlate_and_analyze:
        try:
            logger.info("🧠 IA: Starting correlation analysis...")
            correlate_and_analyze()
        except Exception as e:
            logger.error(f"IA Correlation Error: {e}")

    # --- SCAN D'ALERTES CRITIQUES ---
    try:
        logger.info("🔔 ALERTS: Scanning for critical signals...")
        scan_for_critical_alerts(MARKET_STATE)
    except Exception as e:
        logger.error(f"Alert Scanning Error: {e}")

    logger.info(f"✅ ENGINE: Cycle complete. {len(MARKET_STATE['tickers'])} assets.")

def get_global_context():
    with market_lock:
        live_tickers = dict(MARKET_STATE['tickers'])
        geopolitics = dict(MARKET_STATE['geopolitics'])
    
    heatmap_data = []
    sector_perf = {}
    indices = {}
    
    # Récupération des indices majeurs
    for idx_sym in ['^FCHI', '^SBF120', '^VIX']:
        info = live_tickers.get(idx_sym)
        if info:
            indices[idx_sym.replace('^', '')] = {
                'symbol': idx_sym,
                'price': info.get('price'),
                'change': info.get('change_pct', 0),
                'reco': info.get('recommendation', 'Neutre')
            }

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM tickers")
            db_symbols = cursor.fetchall()
            
            for s, sector in db_symbols:
                info = live_tickers.get(s)
                if not info or info.get('price', 0) == 0:
                    continue
                
                change = info.get('change_pct', 0)
                
                # Heatmap
                intensity = min(abs(change) * 20, 100)
                heatmap_data.append({
                    'symbol': s.replace('.PA', ''),
                    'change': change,
                    'full_symbol': s,
                    'intensity': intensity
                })
                
                # Sectors
                if sector not in sector_perf:
                    sector_perf[sector] = []
                sector_perf[sector].append(change)
                
    except Exception as e:
        logger.error(f"Error in get_global_context: {e}")
    
    top_sectors = []
    for sec, changes in sector_perf.items():
        if changes:
            avg_change = sum(changes) / len(changes)
            top_sectors.append({'name': sec, 'change': avg_change})
            
    # Trier les secteurs par performance décroissante
    top_sectors = sorted(top_sectors, key=lambda x: x['change'], reverse=True)
    
    # --- Synthèse Éditoriale ---
    daily_editorial = "Le marché montre une dynamique intéressante. "
    sentiment_label = "Neutre"
    ai_tip = "Surveillez les points de pivot sur vos valeurs préférées."
    
    if top_sectors:
        best_sector = top_sectors[0]['name']
        worst_sector = top_sectors[-1]['name']
        if top_sectors[0]['change'] > 0.5:
            daily_editorial = f"Aujourd'hui, le secteur {best_sector} tire le marché vers le haut avec une belle performance. C'est un signal positif pour les valeurs cycliques. "
            sentiment_label = "Positif"
            ai_tip = "C'est peut-être le moment de renforcer vos positions sur les leaders sectoriels."
        elif top_sectors[-1]['change'] < -0.5:
            daily_editorial = f"Prudence aujourd'hui : le secteur {worst_sector} pèse sur la tendance. Les investisseurs semblent plus frileux, cherchant des refuges sécurisés. "
            sentiment_label = "Prudent"
            ai_tip = "Attendez une stabilisation des volumes avant de nouvelles entrées sur les secteurs en baisse."
        
        # Ajout d'une info sur l'indice phare (CAC 40)
        cac_info = indices.get('FCHI')
        if cac_info and cac_info['change'] > 1:
            daily_editorial += "Le CAC 40 franchit des seuils importants, confirmant un appétit pour le risque."
        elif cac_info and cac_info['change'] < -1:
            daily_editorial += "La cassure des supports sur l'indice phare suggère une vigilance accrue."

    return top_sectors, sorted(heatmap_data, key=lambda x: x['symbol']), indices, geopolitics, daily_editorial, sentiment_label, ai_tip
