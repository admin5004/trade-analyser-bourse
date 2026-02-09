#!/usr/bin/env python3
"""
Gestionnaire Multi-API pour Données Boursières
Compatible Linux Mint / Ubuntu
"""

import os
import requests
import json
from typing import Dict, List, Optional
from datetime import datetime
import yfinance as yf


class StockAPIManager:
    """Gestionnaire intelligent qui utilise plusieurs APIs gratuites"""
    
    def __init__(self, config_file: str = "api_config.json"):
        self.config_file = config_file
        self.api_keys = self.load_config()
        self.api_call_count = {
            'alpha_vantage': 0,
            'finnhub': 0,
            'twelve_data': 0,
            'yahoo': 0
        }
        
    def load_config(self) -> Dict:
        """Charge les clés API depuis le fichier de configuration"""
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return json.load(f)
        return {
            'alpha_vantage': '',
            'finnhub': '',
            'twelve_data': ''
        }
    
    def save_config(self, keys: Dict):
        """Sauvegarde les clés API"""
        with open(self.config_file, 'w') as f:
            json.dump(keys, f, indent=4)
        print(f"✓ Configuration sauvegardée dans {self.config_file}")
    
    def get_stock_quote_yahoo(self, symbol: str) -> Optional[Dict]:
        """
        Récupère le cours via Yahoo Finance (GRATUIT, ILLIMITÉ)
        Meilleur pour: Tous les marchés, données fiables
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            hist = ticker.history(period="1d")
            
            if hist.empty:
                return None
                
            self.api_call_count['yahoo'] += 1
            
            return {
                'symbol': symbol,
                'price': float(hist['Close'].iloc[-1]),
                'open': float(hist['Open'].iloc[-1]),
                'high': float(hist['High'].iloc[-1]),
                'low': float(hist['Low'].iloc[-1]),
                'volume': int(hist['Volume'].iloc[-1]),
                'previous_close': info.get('previousClose', 'N/A'),
                'market': info.get('exchange', 'N/A'),
                'source': 'Yahoo Finance',
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            print(f"❌ Yahoo Finance erreur pour {symbol}: {str(e)}")
            return None
    
    def get_stock_quote_alpha_vantage(self, symbol: str) -> Optional[Dict]:
        """
        Récupère le cours via Alpha Vantage
        Limite: 25 requêtes/jour (gratuit)
        Meilleur pour: Données US, forex
        """
        if not self.api_keys.get('alpha_vantage'):
            print("⚠️  Clé Alpha Vantage manquante")
            return None
            
        try:
            url = f"https://www.alphavantage.co/query"
            params = {
                'function': 'GLOBAL_QUOTE',
                'symbol': symbol,
                'apikey': self.api_keys['alpha_vantage']
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if 'Global Quote' in data and data['Global Quote']:
                quote = data['Global Quote']
                self.api_call_count['alpha_vantage'] += 1
                
                return {
                    'symbol': symbol,
                    'price': float(quote.get('05. price', 0)),
                    'open': float(quote.get('02. open', 0)),
                    'high': float(quote.get('03. high', 0)),
                    'low': float(quote.get('04. low', 0)),
                    'volume': int(quote.get('06. volume', 0)),
                    'previous_close': float(quote.get('08. previous close', 0)),
                    'change_percent': quote.get('10. change percent', 'N/A'),
                    'source': 'Alpha Vantage',
                    'timestamp': datetime.now().isoformat()
                }
            return None
            
        except Exception as e:
            print(f"❌ Alpha Vantage erreur pour {symbol}: {str(e)}")
            return None
    
    def get_stock_quote_finnhub(self, symbol: str) -> Optional[Dict]:
        """
        Récupère le cours via Finnhub
        Limite: 60 requêtes/minute (gratuit)
        Meilleur pour: Données temps réel US
        """
        if not self.api_keys.get('finnhub'):
            print("⚠️  Clé Finnhub manquante")
            return None
            
        try:
            url = f"https://finnhub.io/api/v1/quote"
            params = {
                'symbol': symbol,
                'token': self.api_keys['finnhub']
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('c'):  # current price
                self.api_call_count['finnhub'] += 1
                
                return {
                    'symbol': symbol,
                    'price': float(data['c']),
                    'open': float(data['o']),
                    'high': float(data['h']),
                    'low': float(data['l']),
                    'previous_close': float(data['pc']),
                    'change': float(data['d']),
                    'change_percent': float(data['dp']),
                    'source': 'Finnhub',
                    'timestamp': datetime.now().isoformat()
                }
            return None
            
        except Exception as e:
            print(f"❌ Finnhub erreur pour {symbol}: {str(e)}")
            return None
    
    def get_stock_quote_twelve_data(self, symbol: str) -> Optional[Dict]:
        """
        Récupère le cours via Twelve Data
        Limite: 800 requêtes/jour (gratuit)
        Meilleur pour: Mix de marchés internationaux
        """
        if not self.api_keys.get('twelve_data'):
            print("⚠️  Clé Twelve Data manquante")
            return None
            
        try:
            url = f"https://api.twelvedata.com/quote"
            params = {
                'symbol': symbol,
                'apikey': self.api_keys['twelve_data']
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get('close'):
                self.api_call_count['twelve_data'] += 1
                
                return {
                    'symbol': symbol,
                    'price': float(data['close']),
                    'open': float(data['open']),
                    'high': float(data['high']),
                    'low': float(data['low']),
                    'volume': int(data.get('volume', 0)),
                    'previous_close': float(data.get('previous_close', 0)),
                    'change': float(data.get('change', 0)),
                    'change_percent': data.get('percent_change', 'N/A'),
                    'source': 'Twelve Data',
                    'timestamp': datetime.now().isoformat()
                }
            return None
            
        except Exception as e:
            print(f"❌ Twelve Data erreur pour {symbol}: {str(e)}")
            return None
    
    def get_stock_quote(self, symbol: str, preferred_api: str = 'auto') -> Optional[Dict]:
        """
        Récupère le cours en utilisant la meilleure API disponible
        
        Args:
            symbol: Symbole boursier (ex: 'AAPL', 'MC.PA' pour LVMH sur Euronext)
            preferred_api: 'auto', 'yahoo', 'alpha_vantage', 'finnhub', 'twelve_data'
        """
        print(f"\n🔍 Recherche de {symbol}...")
        
        # Stratégie auto: commence par Yahoo (gratuit illimité)
        if preferred_api == 'auto' or preferred_api == 'yahoo':
            result = self.get_stock_quote_yahoo(symbol)
            if result:
                return result
        
        # Essaie les autres APIs si Yahoo échoue
        apis_to_try = []
        
        if preferred_api == 'auto':
            # Ordre de préférence basé sur les limites
            apis_to_try = [
                ('twelve_data', self.get_stock_quote_twelve_data),
                ('finnhub', self.get_stock_quote_finnhub),
                ('alpha_vantage', self.get_stock_quote_alpha_vantage)
            ]
        else:
            # API spécifique demandée
            api_map = {
                'alpha_vantage': self.get_stock_quote_alpha_vantage,
                'finnhub': self.get_stock_quote_finnhub,
                'twelve_data': self.get_stock_quote_twelve_data
            }
            if preferred_api in api_map:
                apis_to_try = [(preferred_api, api_map[preferred_api])]
        
        for api_name, api_func in apis_to_try:
            result = api_func(symbol)
            if result:
                return result
        
        print(f"❌ Impossible de récupérer les données pour {symbol}")
        return None
    
    def get_multiple_quotes(self, symbols: List[str]) -> List[Dict]:
        """Récupère plusieurs cours en optimisant les appels API"""
        results = []
        
        for symbol in symbols:
            quote = self.get_stock_quote(symbol)
            if quote:
                results.append(quote)
        
        return results
    
    def show_stats(self):
        """Affiche les statistiques d'utilisation des APIs"""
        print("\n📊 Statistiques d'utilisation des APIs:")
        print("=" * 50)
        for api, count in self.api_call_count.items():
            print(f"{api.replace('_', ' ').title()}: {count} requêtes")
        print("=" * 50)


def setup_wizard():
    """Assistant de configuration pour les clés API"""
    print("\n" + "=" * 60)
    print("🔧 CONFIGURATION DES CLÉS API")
    print("=" * 60)
    print("\nCe script va t'aider à configurer tes clés API gratuites.")
    print("Tu peux laisser vide si tu n'as pas encore de clé.\n")
    
    keys = {}
    
    print("📌 YAHOO FINANCE")
    print("   → GRATUIT et ILLIMITÉ (pas de clé nécessaire)")
    print("   → Fonctionne immédiatement!\n")
    
    print("📌 ALPHA VANTAGE (optionnel)")
    print("   → Inscription: https://www.alphavantage.co/support/#api-key")
    print("   → Limite: 25 requêtes/jour (gratuit)")
    alpha_key = input("   Clé Alpha Vantage (Enter pour ignorer): ").strip()
    keys['alpha_vantage'] = alpha_key
    
    print("\n📌 FINNHUB (optionnel)")
    print("   → Inscription: https://finnhub.io/register")
    print("   → Limite: 60 requêtes/minute")
    finnhub_key = input("   Clé Finnhub (Enter pour ignorer): ").strip()
    keys['finnhub'] = finnhub_key
    
    print("\n📌 TWELVE DATA (optionnel)")
    print("   → Inscription: https://twelvedata.com/pricing")
    print("   → Limite: 800 requêtes/jour")
    twelve_key = input("   Clé Twelve Data (Enter pour ignorer): ").strip()
    keys['twelve_data'] = twelve_key
    
    manager = StockAPIManager()
    manager.save_config(keys)
    
    print("\n✅ Configuration terminée!")
    return manager


def display_quote(quote: Dict):
    """Affiche joliment un cours boursier"""
    if not quote:
        return
    
    print("\n" + "=" * 60)
    print(f"📈 {quote['symbol']} - {quote.get('market', 'N/A')}")
    print("=" * 60)
    print(f"Prix actuel:     {quote['price']:.2f}")
    print(f"Ouverture:       {quote.get('open', 'N/A'):.2f}")
    print(f"Plus haut:       {quote.get('high', 'N/A'):.2f}")
    print(f"Plus bas:        {quote.get('low', 'N/A'):.2f}")
    print(f"Clôture préc.:   {quote.get('previous_close', 'N/A')}")
    
    if 'change_percent' in quote:
        print(f"Variation:       {quote['change_percent']}")
    
    if 'volume' in quote:
        print(f"Volume:          {quote['volume']:,}")
    
    print(f"\n📡 Source: {quote['source']}")
    print(f"⏰ {quote['timestamp']}")
    print("=" * 60)


def main():
    """Fonction principale avec menu interactif"""
    print("\n" + "=" * 60)
    print("📊 GESTIONNAIRE MULTI-API DONNÉES BOURSIÈRES")
    print("=" * 60)
    
    # Vérifie si la config existe
    if not os.path.exists("api_config.json"):
        print("\n⚠️  Première utilisation détectée")
        choice = input("Lancer l'assistant de configuration? (o/n): ").lower()
        if choice == 'o':
            manager = setup_wizard()
        else:
            manager = StockAPIManager()
    else:
        manager = StockAPIManager()
        print("✓ Configuration chargée")
    
    while True:
        print("\n" + "-" * 60)
        print("MENU:")
        print("1. Récupérer un cours boursier")
        print("2. Récupérer plusieurs cours")
        print("3. Voir les statistiques")
        print("4. Reconfigurer les clés API")
        print("5. Exemples de symboles")
        print("6. Quitter")
        print("-" * 60)
        
        choice = input("\nChoix: ").strip()
        
        if choice == '1':
            symbol = input("\nSymbole boursier (ex: AAPL, MC.PA, VOW3.DE): ").strip().upper()
            quote = manager.get_stock_quote(symbol)
            if quote:
                display_quote(quote)
        
        elif choice == '2':
            symbols_input = input("\nSymboles séparés par des espaces: ").strip().upper()
            symbols = symbols_input.split()
            quotes = manager.get_multiple_quotes(symbols)
            for quote in quotes:
                display_quote(quote)
        
        elif choice == '3':
            manager.show_stats()
        
        elif choice == '4':
            setup_wizard()
            manager = StockAPIManager()
        
        elif choice == '5':
            print("\n📚 EXEMPLES DE SYMBOLES:")
            print("\n🇺🇸 S&P 500 / NASDAQ:")
            print("   AAPL  - Apple")
            print("   MSFT  - Microsoft")
            print("   GOOGL - Google")
            print("   TSLA  - Tesla")
            print("\n🇫🇷 Euronext Paris:")
            print("   MC.PA    - LVMH")
            print("   OR.PA    - L'Oréal")
            print("   SAN.PA   - Sanofi")
            print("   AI.PA    - Air Liquide")
            print("   FDJ.PA   - Française des Jeux")
            print("\n🇬🇧 Londres (LSE):")
            print("   HSBA.L   - HSBC")
            print("   BP.L     - BP")
            print("   VOD.L    - Vodafone")
            print("\n🇩🇪 Francfort (XETRA):")
            print("   VOW3.DE  - Volkswagen")
            print("   SIE.DE   - Siemens")
            print("   SAP.DE   - SAP")
        
        elif choice == '6':
            print("\n👋 À bientôt!")
            manager.show_stats()
            break
        
        else:
            print("❌ Choix invalide")


if __name__ == "__main__":
    main()
