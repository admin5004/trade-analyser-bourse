
import sys
import os
import yfinance as yf
from datetime import datetime
import pandas as pd

# Ajouter le chemin du projet pour l'importation des modules core
sys.path.append('/home/corentin/trade-analyser-bourse')
try:
    from core.analysis import analyze_stock
except ImportError:
    # Fallback si l'import échoue (au cas où core.analysis n'est pas dans le path)
    print("Erreur d'importation de core.analysis. Vérifiez le chemin.")
    sys.exit(1)

def analyze_specific_stock(symbol):
    print(f"Analyse pour {symbol}...")
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period="1y", timeout=15)
        
        if df is None or df.empty:
            print(f"Aucune donnée trouvée pour {symbol}.")
            return

        # Normaliser les colonnes en minuscules pour core.analysis
        df.columns = [col.lower() for col in df.columns]
        
        # Calculs de base pour l'affichage
        close_now = df['close'].iloc[-1]
        close_prev = df['close'].iloc[-2] if len(df) > 1 else close_now
        change_pct = ((close_now - close_prev) / close_prev * 100) if close_prev != 0 else 0
        
        # Appel à la fonction d'analyse du cœur
        # La signature attendue semble être: analyze_stock(df) -> reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit
        # Je vais vérifier la signature exacte dans core/analysis.py si cela échoue, mais je me base sur auto_tech_analysis.py
        result = analyze_stock(df)
        
        # Déballage des résultats (basé sur auto_tech_analysis.py)
        # reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = result
        # Attention: auto_tech_analysis.py fait: reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
        
        reco = result[0]
        reason = result[1]
        rsi = result[2]
        
        print(f"\nRésultats pour {symbol}:")
        print(f"Prix actuel: {close_now:.2f} ({change_pct:+.2f}%)")
        print(f"RSI: {rsi:.2f}")
        print(f"Recommandation: {reco}")
        print(f"Raison: {reason}")
        print("-" * 30)

    except Exception as e:
        print(f"Erreur lors de l'analyse de {symbol}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # Symboles pour Xiaomi
    symbols = ['1810.HK', 'XIACY']
    for sym in symbols:
        analyze_specific_stock(sym)
