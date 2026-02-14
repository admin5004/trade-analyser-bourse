import yfinance as yf
import threading
import logging
import time
from datetime import datetime
from .database import get_db_connection
from .analysis import analyze_stock

logger = logging.getLogger("TradingEngine.Market")

market_lock = threading.Lock()
MARKET_STATE = {
    'last_update': None,
    'tickers': {},  
    'dataframes': {},
    'sectors': {},
    'last_error': None
}

def fetch_market_data_job():
    logger.info("📡 ENGINE: Cycle started...")
    symbols_info = {}
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, sector FROM tickers")
            for row in cursor.fetchall(): symbols_info[row[0]] = row[1]
    except Exception: return
    
    symbols = list(symbols_info.keys())
    temp_tickers, temp_dfs = {}, {}
    
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y", timeout=20)
            if df is None or df.empty:
                temp_tickers[symbol] = {'price': 0, 'change_pct': 0, 'sector': symbols_info.get(symbol, 'Autre'), 'vol_spike': 1.0}
                continue
            
            df.columns = [col.lower() for col in df.columns]
            close_now = df['close'].iloc[-1]
            close_prev = df['close'].iloc[-2] if len(df) > 1 else close_now
            change_pct = ((close_now - close_prev) / close_prev * 100) if close_prev != 0 else 0
            
            # Fundamentals
            try:
                info_data = ticker.info
                pe = info_data.get('trailingPE')
                raw_yield = info_data.get('dividendYield')
                dy = 0
                if raw_yield:
                    # Si yfinance renvoie > 1.0, c'est probablement déjà en pourcentage (ex: 2.4 pour 2.4%)
                    # Sinon c'est un ratio (ex: 0.024 pour 2.4%)
                    dy = float(raw_yield) if raw_yield > 1.0 else float(raw_yield) * 100
            except: pe, dy = None, None

            reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
            
            temp_dfs[symbol] = df
            temp_tickers[symbol] = {
                'price': float(close_now),
                'change_pct': float(change_pct),
                'sector': symbols_info.get(symbol, 'Autre'),
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
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"Failed {symbol}: {e}")
            temp_tickers[symbol] = {'price': 0, 'change_pct': 0, 'sector': symbols_info.get(symbol, 'Autre'), 'vol_spike': 1.0}
            
    with market_lock:
        MARKET_STATE['tickers'].update(temp_tickers)
        MARKET_STATE['dataframes'].update(temp_dfs)
        MARKET_STATE['last_update'] = datetime.now().isoformat()
    logger.info(f"✅ ENGINE: Cycle complete. {len(MARKET_STATE['tickers'])} assets.")

def get_global_context():
    with market_lock:
        live_tickers = dict(MARKET_STATE['tickers'])
    
    heatmap_data = []
    sector_perf = {}
    
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
    
    return top_sectors, sorted(heatmap_data, key=lambda x: x['symbol'])
