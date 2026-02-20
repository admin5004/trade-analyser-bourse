
import json
import os
from datetime import datetime

MEMORY_FILE = "/home/corentin/trade-analyser-bourse/market_memory.json"

def save_event_to_memory(symbol, price, volume, change_pct, event_type):
    """Enregistre un événement notable en mémoire pour analyse ultérieure par l'IA."""
    memory = []
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f:
                memory = json.load(f)
        except:
            memory = []
            
    new_event = {
        "symbol": symbol,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price": price,
        "volume": volume,
        "change_pct": change_pct,
        "type": event_type
    }
    
    memory.append(new_event)
    
    # Garder seulement les 100 derniers événements
    if len(memory) > 100:
        memory = memory[-100:]
        
    with open(MEMORY_FILE, 'w') as f:
        json.dump(memory, f, indent=4)
