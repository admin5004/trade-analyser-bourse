import json
import os

class FinancialAI:
    def __init__(self, memory_file="/home/corentin/trade-analyser-bourse/market_memory.json"):
        self.memory_file = memory_file
        self.memory = self.load_memory()

    def load_memory(self):
        if os.path.exists(self.memory_file):
            with open(self.memory_file, 'r') as f:
                return json.load(f)
        return []

    def get_prediction(self, current_price, current_vol, symbol):
        """
        Analyse la situation actuelle par rapport aux souvenirs et aux analyses de news.
        """
        if not self.memory:
            return "Analyse en cours (manque de données historiques)...", 50

        # Récupérer les événements les plus récents pour le symbole donné
        recent_events = [e for e in self.memory if e.get('symbol') == symbol and 'analysis' in e]
        
        if not recent_events:
            return "Tendance neutre. Aucun événement récent analysé.", 50

        last_analyzed_event = recent_events[-1]
        analysis = last_analyzed_event['analysis']
        
        # Logique de prédiction améliorée:
        # On va chercher des mots-clés dans les "potential_causes" et combiner avec le mouvement de prix
        
        prediction = "Tendance neutre."
        confidence = 50
        
        # Analyse des causes potentielles
        causes_text = " ".join(analysis.get('potential_causes', [])).lower()
        
        if "bénéfice net" in causes_text or "croissance" in causes_text:
            prediction = "Prédiction HAUSSIÈRE."
            confidence += 15
        if "baisse de ventes" in causes_text or "chute" in causes_text or "décevants" in causes_text:
            prediction = "Prédiction BAISSIÈRE."
            confidence -= 15
        if "reprise" in causes_text:
            prediction = "Potentiel de REPRISE."
            confidence += 10
        if "actionnaires" in causes_text or "investissement" in causes_text:
            prediction = "Attention aux mouvements des institutionnels."
            confidence += 5
        
        # Ajustement basé sur le mouvement de prix détecté
        if last_analyzed_event['change_pct'] > 0.5: # Forte hausse
            prediction += " Forte impulsion haussière récente."
            confidence += 20
        elif last_analyzed_event['change_pct'] < -0.5: # Forte baisse
            prediction += " Forte impulsion baissière récente."
            confidence -= 20
            
        # S'assurer que la confiance reste entre 0 et 100
        confidence = max(0, min(100, confidence))

        return prediction, confidence
        
    def get_next_session_recommendation(self, symbol: str) -> (str, int):
        """
        Génère une recommandation simple pour la prochaine session basée sur la dernière analyse intraday.
        """
        prediction, confidence = self.get_prediction(0, 0, symbol) # current_price et current_vol sont ignorés pour cette méthode
        
        recommendation = "Observer"
        reco_confidence = 50 # Confiance spécifique à la recommandation
        
        if "HAUSSIÈRE" in prediction and confidence >= 75:
            recommendation = "Surveillance Achat (Haute Confiance)"
            reco_confidence = confidence
        elif "HAUSSIÈRE" in prediction and confidence >= 60:
            recommendation = "Surveillance Achat (Confiance Modérée)"
            reco_confidence = confidence
        elif "BAISSIÈRE" in prediction and confidence >= 75:
            recommendation = "Surveillance Vente (Haute Confiance)"
            reco_confidence = confidence
        elif "BAISSIÈRE" in prediction and confidence >= 60:
            recommendation = "Surveillance Vente (Confiance Modérée)"
            reco_confidence = confidence
        
        return recommendation, reco_confidence

# Instance globale
ai_brain = FinancialAI()
