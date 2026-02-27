
import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime

# Ajouter le chemin du projet pour l'importation des modules core
sys.path.append('/home/corentin/trade-analyser-bourse')
from core.analysis import analyze_stock

def get_analysis_for_symbols(symbols):
    results = []
    print(f"{'SYMBOLE':<10} | {'PRIX':<8} | {'VAR %':<7} | {'RSI':<5} | {'RECO':<12} | {'RAISON'}")
    print("-" * 100)
    
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y", timeout=15)
            if df is None or df.empty:
                continue
            
            df.columns = [col.lower() for col in df.columns]
            close_now = df['close'].iloc[-1]
            close_prev = df['close'].iloc[-2] if len(df) > 1 else close_now
            change_pct = ((close_now - close_prev) / close_prev * 100) if close_prev != 0 else 0
            
            reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
            
            print(f"{symbol:<10} | {close_now:>8.2f} | {change_pct:>+6.2f}% | {rsi:>5.1f} | {reco:<12} | {reason}")
            
            results.append({
                'symbol': symbol,
                'price': close_now,
                'change_pct': change_pct,
                'rsi': rsi,
                'recommendation': reco,
                'reason': reason
            })
        except Exception as e:
            print(f"Erreur pour {symbol}: {e}")
            
    return results

if __name__ == "__main__":
    # Liste de symboles représentatifs pour l'analyse automatique
    test_symbols = ['AAPL', 'GOOGL', 'TSLA', 'MC.PA', 'OR.PA', 'GLE.PA', 'TTE.PA', 'AIR.PA']
    get_analysis_for_symbols(test_symbols)
