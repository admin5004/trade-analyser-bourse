import os
import pandas as pd
import numpy as np
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator, EMAIndicator
from xgboost import XGBRegressor
import joblib
from datetime import datetime, timedelta

class MLPredictor:
    def __init__(self, model_dir="/home/corentin/trade-analyser-bourse/models"):
        self.model_dir = model_dir
        if not os.path.exists(self.model_dir):
            os.makedirs(self.model_dir)
        
        # Horizons de prédiction en jours de bourse (environ)
        self.horizons = {
            "1w": 5,
            "1m": 21,
            "3m": 63,
            "6m": 126
        }
        self.models = {}

    def fetch_data(self, symbol):
        """Récupère 2 ans d'historique maximum"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=2*365)
        
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date)
        return df

    def prepare_features(self, df):
        """Calcule les indicateurs techniques (Features)"""
        # RSI
        df['rsi'] = RSIIndicator(close=df['Close']).rsi()
        
        # MACD
        macd = MACD(close=df['Close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        
        # Moyennes mobiles
        df['sma_20'] = SMAIndicator(close=df['Close'], window=20).sma_indicator()
        df['ema_50'] = EMAIndicator(close=df['Close'], window=50).ema_indicator()
        
        # Volatilité et Momentum
        df['returns'] = df['Close'].pct_change()
        df['volatility'] = df['returns'].rolling(window=20).std()
        
        # Supprimer les lignes avec des valeurs manquantes dues au calcul des indicateurs
        return df.dropna()

    def train_for_horizons(self, symbol):
        """Entraîne un modèle pour chaque horizon de temps"""
        raw_df = self.fetch_data(symbol)
        if raw_df.empty or len(raw_df) < 150:
            print(f"Pas assez de données pour {symbol}")
            return False

        df = self.prepare_features(raw_df)
        
        features = ['rsi', 'macd', 'macd_signal', 'sma_20', 'ema_50', 'volatility', 'returns']
        
        training_results = {}

        for name, days in self.horizons.items():
            # Créer la cible (Target): le retour futur à X jours
            # On veut prédire la variation en pourcentage
            df_target = df.copy()
            df_target['target'] = df_target['Close'].shift(-days) / df_target['Close'] - 1
            
            # Supprimer les dernières lignes car on ne connaît pas encore leur futur
            train_data = df_target.dropna()
            
            if train_data.empty:
                continue

            X = train_data[features]
            y = train_data['target']
            
            # Modèle XGBoost
            model = XGBRegressor(n_estimators=100, learning_rate=0.05, max_depth=5)
            model.fit(X, y)
            
            # Sauvegarde
            model_path = os.path.join(self.model_dir, f"{symbol}_{name}.joblib")
            joblib.dump(model, model_path)
            self.models[name] = model
            
            # Calculer une erreur approximative sur le dernier point pour info
            last_pred = model.predict(X.tail(1))[0]
            training_results[name] = last_pred * 100 # En pourcentage
            
        print(f"✓ Modèles entraînés pour {symbol}")
        return training_results

    def predict_future(self, symbol):
        """Prédit les rendements pour tous les horizons à partir du prix actuel"""
        raw_df = self.fetch_data(symbol)
        df = self.prepare_features(raw_df)
        last_features = df[ ['rsi', 'macd', 'macd_signal', 'sma_20', 'ema_50', 'volatility', 'returns'] ].tail(1)
        
        predictions = {}
        for name in self.horizons.keys():
            model_path = os.path.join(self.model_dir, f"{symbol}_{name}.joblib")
            if os.path.exists(model_path):
                model = joblib.load(model_path)
                pred = model.predict(last_features)[0]
                predictions[name] = round(float(pred) * 100, 2)
        
        return predictions

if __name__ == "__main__":
    # Test sur Air Liquide (AI.PA)
    predictor = MLPredictor()
    print("Entraînement en cours...")
    results = predictor.train_for_horizons("AI.PA")
    print(f"Prédictions actuelles pour AI.PA : {predictor.predict_future('AI.PA')}")
