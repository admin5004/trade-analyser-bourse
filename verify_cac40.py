import os
import sqlite3
import pandas as pd
import yfinance as yf
import time
from app import analyze_stock

DB_NAME = "users.db"

def verify_cac40():
    print("🚀 Démarrage de la vérification du CAC40...")
    cac40_symbols = []
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, name FROM tickers")
            cac40_symbols = cursor.fetchall()
    except Exception as e:
        print(f"❌ Erreur DB: {e}")
        return

    results = []
    for symbol, name in cac40_symbols:
        print(f"🔍 Test de {symbol} ({name})...", end=" ", flush=True)
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1mo")
            if df is None or df.empty:
                print("❌ AUCUNE DONNÉE")
                results.append((symbol, "ERREUR", "Pas de données"))
                continue
            
            df.columns = [col.lower() for col in df.columns]
            # analyze_stock returns 9 values
            analysis = analyze_stock(df)
            reco = analysis[0]
            
            print(f"✅ OK ({reco})")
            results.append((symbol, reco, "Success"))
        except Exception as e:
            print(f"💥 CRASH: {e}")
            results.append((symbol, "CRASH", str(e)))
        time.sleep(0.2)

    print("\n--- RAPPORT FINAL ---")
    success = [r for r in results if r[1] not in ["ERREUR", "CRASH"]]
    print(f"Succès: {len(success)}/40")
    if len(results) > 0 and len(success) < len(results):
        failed = [r[0] for r in results if r[1] in ["ERREUR", "CRASH"]]
        print(f"Échecs détectés ({len(failed)}) : {failed}")

if __name__ == "__main__":
    verify_cac40()