import logging
import json
import os
from typing import List, Dict
import subprocess # Pour appeler la commande shell de google_web_search

logger = logging.getLogger("TradingEngine.SocialIntelligence")

CONFIG_FILE = os.path.join(os.path.dirname(__file__), '..', 'config', 'social_config.json')

def load_social_config() -> Dict:
    """Charge la configuration sociale depuis social_config.json."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def _run_google_web_search_command(query: str, collected_queries: List[str]) -> List[Dict]:
    """Collecte la requête pour exécution par l'agent et retourne un résultat factice pour le script."""
    collected_queries.append(query)
    # Retourne toujours un résultat factice pour que le script Python continue de s'exécuter
    return [{
        'title': f"Simulated Result for '{query}'",
        'link': f"https://example.com/search?q={query}",
        'snippet': "This is a simulated search result for testing purposes."
    }]

def fetch_official_social_news(symbol: str) -> (List[Dict], List[str]):
    """
    Récupère les actualités pertinentes des comptes sociaux officiels et collecte les requêtes générées,
    en utilisant les informations du fichier de configuration.
    """
    config = load_social_config()
    company_data = config.get(symbol)

    if not company_data:
        logger.warning(f"Aucune configuration sociale trouvée pour le symbole {symbol}.")
        return [], []

    company_name = company_data.get("company_name")
    exec_names = company_data.get("exec_names", [])
    fund_names = company_data.get("fund_names", [])

    all_social_news = []
    generated_queries = []
    
    # 1. Recherche pour l'entreprise
    company_queries = [
        f'"{company_name}" official twitter news',
        f'"{company_name}" linkedin announcements',
        f'"{company_name}" financial news'
    ]
    for query in company_queries:
        results = _run_google_web_search_command(query, generated_queries)
        for res in results:
            if any(domain in res.get('link', '') for domain in ['twitter.com', 'linkedin.com', 'boursorama.com', 'lesechos.fr', 'example.com']): # Ajout example.com pour le mock
                all_social_news.append({
                    'title': res.get('title'),
                    'link': res.get('link'),
                    'source': 'Social Media (Official)',
                    'query': query
                })

    # 2. Recherche pour les cadres dirigeants
    if exec_names:
        for exec_name in exec_names:
            exec_queries = [
                f'"{exec_name}" "{company_name}" twitter',
                f'"{exec_name}" "{company_name}" linkedin'
            ]
            for query in exec_queries:
                results = _run_google_web_search_command(query, generated_queries)
                for res in results:
                    if any(domain in res.get('link', '') for domain in ['twitter.com', 'linkedin.com', 'example.com']):
                        all_social_news.append({
                            'title': res.get('title'),
                            'link': res.get('link'),
                            'source': f'Executive Social ({exec_name})',
                            'query': query
                        })
    
    # 3. Recherche pour les fonds d'investissement actionnaires
    if fund_names:
        for fund_name in fund_names:
            fund_queries = [
                f'"{fund_name}" "{company_name}" investment news',
                f'"{fund_name}" twitter'
            ]
            for query in fund_queries:
                results = _run_google_web_search_command(query, generated_queries)
                for res in results:
                    if any(domain in res.get('link', '') for domain in ['twitter.com', 'bloomberg.com', 'reuters.com', 'example.com']):
                        all_social_news.append({
                            'title': res.get('title'),
                            'link': res.get('link'),
                            'source': f'Fund Social ({fund_name})',
                            'query': query
                        })
                    
    return all_social_news, generated_queries

# --- Exemple d'utilisation (pour les tests) ---
if __name__ == "__main__":
    symbol_example = "MC.PA" # Testons avec LVMH
    print(f"Recherche d'actualités sociales officielles pour {symbol_example} en utilisant la configuration...")
    social_news, generated_queries = fetch_official_social_news(symbol_example)
    
    if social_news:
        print(f"\n{len(social_news)} actualités sociales officielles trouvées:")
        for item in social_news[:5]:
            print(f"- [{item.get('source')}] {item.get('title') or 'N/A'} ({item.get('link') or 'N/A'})")
    else:
        print("Aucune actualité sociale officielle trouvée.")
        
    if generated_queries:
        print("\nRequêtes générées pour Google Web Search:")
        for q in generated_queries:
            print(f"- {q}")