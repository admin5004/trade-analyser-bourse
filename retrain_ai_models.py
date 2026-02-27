import os
import sys
import logging
from datetime import datetime

# Ajouter le chemin du projet
sys.path.append('/home/corentin/trade-analyser-bourse')
from core.ml_processor import MLPredictor

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - RE-TRAINING - %(levelname)s - %(message)s'
)

def run_intensive_training():
    predictor = MLPredictor()
    
    symbols = [
        "AI.PA", "MC.PA", "OR.PA", "SAN.PA", "TTE.PA", 
        "GLE.PA", "BNP.PA", "AIR.PA", "SU.PA", "DG.PA",
        "AAPL", "MSFT", "GOOGL", "TSLA"
    ]
    
    print(f"🚀 Démarrage du réentraînement IA pour {len(symbols)} valeurs...")
    print("-" * 70)
    
    for symbol in symbols:
        try:
            results = predictor.train_for_horizons(symbol)
            if results:
                # On affiche la prédiction à 1 mois (21 jours de bourse)
                pred_1m = results.get('1m', 0)
                print(f"✅ {symbol:<8} : Succès. Projection 1 mois : {pred_1m:>+6.2f}%")
            else:
                print(f"❌ {symbol:<8} : Échec")
        except Exception as e:
            print(f"⚠️ {symbol:<8} : Erreur : {e}")
            
    print("-" * 70)
    print("✨ Réentraînement terminé.")

if __name__ == "__main__":
    run_intensive_training()
