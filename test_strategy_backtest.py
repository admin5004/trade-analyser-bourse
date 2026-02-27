import pandas as pd
import yfinance as yf
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta

def backtest_strategy(symbol, years=2):
    print(f"=== BACKTESTING SCIENTIFIQUE : {symbol} ({years} ans) ===")
    
    # 1. Récupération des données
    end_date = datetime.now()
    start_date = end_date - timedelta(days=years*365)
    df = yf.Ticker(symbol).history(start=start_date, end=end_date)
    
    if df.empty:
        print("Erreur : Pas de données.")
        return

    df.columns = [col.lower() for col in df.columns]

    # 2. Calcul des indicateurs
    df.ta.adx(length=14, append=True)
    df.ta.bbands(length=20, std=2, append=True)
    df.ta.rsi(length=14, append=True)
    df.ta.sma(length=200, append=True)
    
    # Nettoyage
    df = df.dropna()

    # Identification dynamique des colonnes Bollinger (pour compatibilité versions)
    bb_upper_col = [c for c in df.columns if 'BBU' in c][0]
    bb_lower_col = [c for c in df.columns if 'BBL' in c][0]
    adx_col = [c for c in df.columns if 'ADX' in c][0]

    # 3. Simulation
    capital = 10000
    position = 0
    trades = 0
    
    close = df['close']
    adx = df[adx_col]
    bb_upper = df[bb_upper_col]
    bb_lower = df[bb_lower_col]
    rsi = df['RSI_14']
    sma200 = df['SMA_200']

    for i in range(1, len(df)):
        # ACHAT
        if position == 0:
            if adx.iloc[i] > 20 and close.iloc[i] > bb_upper.iloc[i] and close.iloc[i] > sma200.iloc[i]:
                position = capital / close.iloc[i]
                trades += 1

        # VENTE
        elif position > 0:
            if close.iloc[i] < bb_lower.iloc[i] or rsi.iloc[i] > 80:
                capital = position * close.iloc[i]
                position = 0

    if position > 0:
        capital = position * close.iloc[-1]
    
    final_return = ((capital / 10000) - 1) * 100
    hold_return = ((close.iloc[-1] / close.iloc[0]) - 1) * 100
    
    print(f"Rendement Stratégie : {final_return:>+8.2f}%")
    print(f"Rendement Buy & Hold : {hold_return:>+8.2f}%")
    print(f"Surperformance : {final_return - hold_return:>+8.2f}% ({trades} trades)")
    print("-" * 50)
    return final_return

if __name__ == "__main__":
    symbols = ["AI.PA", "MC.PA", "TTE.PA", "AAPL", "TSLA", "MSFT", "GOOGL"]
    for s in symbols:
        try:
            backtest_strategy(s)
        except Exception as e:
            print(f"Erreur pour {s}: {e}")
