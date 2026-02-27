import os
import sys
import pandas as pd
import yfinance as yf
import sqlite3
from datetime import datetime

# Ajouter le chemin du projet pour l'importation des modules core
sys.path.append('/home/corentin/trade-analyser-bourse')
from core.analysis import analyze_stock

def get_all_symbols():
    try:
        conn = sqlite3.connect('/home/corentin/trade-analyser-bourse/users.db')
        cursor = conn.cursor()
        cursor.execute('SELECT symbol, sector FROM tickers')
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        print(f"Erreur DB: {e}")
        return []

def run_comprehensive_analysis():
    symbols_info = get_all_symbols()
    results = []
    
    print(f"Démarrage de l'analyse technique sur {len(symbols_info)} valeurs...")
    print("-" * 120)
    print(f"{'SYMBOLE':<10} | {'SECTEUR':<15} | {'PRIX':<8} | {'VAR %':<7} | {'RSI':<5} | {'RECO':<12} | {'TENDANCE'}")
    print("-" * 120)
    
    for symbol, sector in symbols_info:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="1y", timeout=10)
            if df is None or df.empty:
                continue
            
            df.columns = [col.lower() for col in df.columns]
            close_now = df['close'].iloc[-1]
            close_prev = df['close'].iloc[-2] if len(df) > 1 else close_now
            change_pct = ((close_now - close_prev) / close_prev * 100) if close_prev != 0 else 0
            
            reco, reason, rsi, mm20, mm50, mm100, mm200, entry, exit = analyze_stock(df)
            
            # Détermination simplifiée de la tendance pour l'affichage
            trend = "HAUSSIÈRE" if close_now > mm200 else "BAISSIÈRE"
            
            print(f"{symbol:<10} | {sector[:15]:<15} | {close_now:>8.2f} | {change_pct:>+6.2f}% | {rsi:>5.1f} | {reco:<12} | {trend}")
            
            results.append({
                'symbol': symbol,
                'sector': sector,
                'price': close_now,
                'change_pct': change_pct,
                'rsi': rsi,
                'recommendation': reco,
                'reason': reason,
                'trend': trend
            })
        except Exception as e:
            pass
            
    # --- SYNTHÈSE ---
    print("\n" + "=" * 50)
    print("🎯 OPPORTUNITÉS D'ACHAT (RECO: Achat Fort / Achat)")
    print("=" * 50)
    buys = [r for r in results if "Achat" in r['recommendation']]
    for b in sorted(buys, key=lambda x: x['rsi']):
        print(f"✅ {b['symbol']:<10} ({b['sector']}): RSI {b['rsi']:.1f} - {b['recommendation']}")
        
    print("\n" + "=" * 50)
    print("⚠️ POINTS DE VIGILANCE (SURACHAT / SURVENTE)")
    print("=" * 50)
    oversold = [r for r in results if r['rsi'] < 30]
    overbought = [r for r in results if r['rsi'] > 70]
    
    if oversold:
        print("--- SURVENDU (Opportunités potentielles de rebond) ---")
        for o in oversold:
            print(f"📉 {o['symbol']:<10} : RSI {o['rsi']:.1f}")
            
    if overbought:
        print("--- SURACHETÉ (Risque de correction) ---")
        for o in overbought:
            print(f"🔥 {o['symbol']:<10} : RSI {o['rsi']:.1f}")

    print("\n" + "=" * 50)
    print("📊 RÉSUMÉ DU MARCHÉ")
    print("=" * 50)
    up = len([r for r in results if r['trend'] == "HAUSSIÈRE"])
    down = len([r for r in results if r['trend'] == "BAISSIÈRE"])
    print(f"Actions en tendance HAUSSIÈRE : {up}")
    print(f"Actions en tendance BAISSIÈRE : {down}")
    print(f"Sentiment global : {'POSITIF' if up > down else 'NÉGATIF'}")
    print("=" * 50)

if __name__ == "__main__":
    run_comprehensive_analysis()
