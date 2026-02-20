import json
import os
import sys
# import yfinance as yf # Import de yfinance - Plus nécessaire ici

# Ajout du chemin pour importer tes modules core
sys.path.append('/home/corentin/trade-analyser-bourse')
from core.news import get_combined_news # Import de get_combined_news
from core.social_intelligence import load_social_config # Pour les symboles à analyser

def load_memory(memory_file="/home/corentin/trade-analyser-bourse/market_memory.json"):
    if os.path.exists(memory_file):
        with open(memory_file, 'r') as f:
            return json.load(f)
    return []

def correlate_and_analyze(symbol_to_analyze: str = None):
    """
    Analyse les événements du marché et les corrèle avec toutes les actualités disponibles (yfinance, Google News, réseaux sociaux officiels).
    Si symbol_to_analyze est None, analyse tous les symboles présents dans la mémoire.
    """
    events = load_memory()
    if not events:
        print("Aucun événement en mémoire à analyser.")
        return

    print("--- Analyse Intelligente des événements ---")
    
    # Récupérer la liste des symboles à analyser
    symbols_in_memory = {event.get('symbol', 'UNKNOWN') for event in events if 'symbol' in event}
    
    social_config = load_social_config()
    if symbol_to_analyze:
        symbols_to_process = {symbol_to_analyze}
    else:
        symbols_to_process = symbols_in_memory.union(set(social_config.keys()))

    # --- ÉTAPE NOUVELLE : S'assurer que les symboles configurés ont au moins une entrée ---
    from datetime import datetime
    for s in symbols_to_process:
        if s not in symbols_in_memory:
            print(f"Création d'un événement initial pour {s}...")
            events.append({
                "symbol": s,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "price": 0,
                "volume": 0,
                "change_pct": 0,
                "type": "INITIAL_ANALYSIS"
            })

    new_memory = [] # Pour stocker les événements mis à jour
    
    for event in events:
        if 'analysis' not in event and event.get('symbol') in symbols_to_process:
            symbol = event['symbol']
            time_str = event['time']
            print(f"Analyse de l'événement à {time_str} pour {symbol}...")
            
            ticker_obj = None 
            
            # Récupération de toutes les news combinées (yfinance, Google, Social)
            all_relevant_news = get_combined_news(ticker_obj, symbol, name=symbol)
            
            # Filtrer et formater pour l'analyse
            relevant_news_titles = [n['title'] for n in all_relevant_news if n['title']]
            
            event['analysis'] = {
                'potential_causes': relevant_news_titles[:8],
                'verdict': f"Analyse préventive multi-sources pour {symbol}."
            }
        new_memory.append(event)
    
    # Sauvegarde
    with open("/home/corentin/trade-analyser-bourse/market_memory.json", 'w') as f:
        json.dump(new_memory, f, indent=4)
    print("✓ Mémoire mise à jour avec l'analyse sociale et dirigeants.")

if __name__ == "__main__":
    # Par défaut, analyser tous les symboles qui ont des événements non analysés
    correlate_and_analyze()
