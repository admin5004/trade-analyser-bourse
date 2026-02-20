import yfinance as yf
import pandas as pd
from datetime import datetime
import json
import os
import sys # Ajout de l'import de sys

def get_market_data(symbol):
    print(f"--- Analyse Intraday pour {symbol} ---")
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="2d", interval="5m")
    return df

def detect_significant_events(df, symbol, volume_threshold=1.5, price_threshold=0.005):
    events = []
    if len(df) < 11: return events
    
    df['vol_avg'] = df['Volume'].rolling(window=10).mean()
    
    for i in range(1, len(df)):
        current_vol = df['Volume'].iloc[i]
        avg_vol = df['vol_avg'].iloc[i-1]
        price_change = abs(df['Close'].iloc[i] - df['Open'].iloc[i]) / df['Open'].iloc[i]
        
        if (not pd.isna(avg_vol) and current_vol > (avg_vol * volume_threshold)) or price_change > price_threshold:
            event = {
                'symbol': symbol, # Ajout du symbole à l'événement
                'time': df.index[i].strftime('%Y-%m-%d %H:%M:%S'),
                'price': round(float(df['Close'].iloc[i]), 2),
                'volume': int(current_vol),
                'change_pct': round(price_change * 100, 2),
                'type': 'VOL_SPIKE' if (not pd.isna(avg_vol) and current_vol > (avg_vol * volume_threshold)) else 'PRICE_MOVE'
            }
            events.append(event)
    return events

def save_to_memory(new_events, memory_file="market_memory.json"):
    memory_path = os.path.join("/home/corentin/trade-analyser-bourse", memory_file)
    if os.path.exists(memory_path):
        with open(memory_path, 'r') as f:
            memory = json.load(f)
    else:
        memory = []
    
    # Créer un ensemble de clés uniques (symbole, temps) pour les événements déjà mémorisés
    existing_unique_keys = {(e['symbol'], e['time']) for e in memory if 'symbol' in e and 'time' in e}
    added = 0
    for e in new_events:
        unique_key = (e['symbol'], e['time']) # Création de la clé unique pour le nouvel événement
        if unique_key not in existing_unique_keys:
            memory.append(e)
            added += 1
            
    with open(memory_path, 'w') as f:
        json.dump(memory, f, indent=4)
    print(f"✓ {added} nouveaux événements mémorisés dans {memory_file}.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        symbol = sys.argv[1].upper() # Utiliser l'argument passé en ligne de commande
    else:
        symbol = "MC.PA" # Valeur par défaut
        
    data = get_market_data(symbol)
    if not data.empty:
        events = detect_significant_events(data, symbol) # Passer le symbole
        save_to_memory(events)
        if events:
            print(f"\nDerniers événements détectés pour {symbol}:")
            for e in events[-3:]:
                print(f"[{e['time']}] {e['type']}: {e['price']}€ ({e['change_pct']}%)")
