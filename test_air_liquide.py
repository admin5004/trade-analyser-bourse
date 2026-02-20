import yfinance as yf
import pandas as pd
import pandas_ta as ta
import sys
import os

# Ajouter le chemin du projet pour pouvoir importer core
sys.path.append('/home/corentin/trade-analyser-bourse')
from core.analysis import analyze_stock

def test_air_liquide():
    symbol = "AI.PA"
    print(f"--- Test de récupération des données pour {symbol} ---")
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="1y", timeout=20)
    
    if df is None or df.empty:
        print("Erreur: DataFrame vide ou None")
        return
        
    print(f"Données récupérées: {len(df)} lignes.")
    df.columns = [col.lower() for col in df.columns]
    
    print("\n--- Test de l'analyse ---")
    try:
        reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
        print(f"Recommandation: {reco}")
        print(f"Raison: {reason}")
        print(f"RSI: {rsi}")
        print(f"MM200: {mm200}")
    except Exception as e:
        print(f"EXCEPTION pendant l'analyse: {e}")

    print("\n--- Test de ticker.info ---")
    try:
        info = ticker.info
        print(f"PE: {info.get('trailingPE')}")
        print(f"Dividend Yield: {info.get('dividendYield')}")
    except Exception as e:
        print(f"EXCEPTION pendant ticker.info: {e}")

if __name__ == '__main__':
    test_air_liquide()
