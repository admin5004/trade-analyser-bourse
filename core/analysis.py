import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from textblob import TextBlob
import logging
from core.geopolitics import analyze_global_risk

logger = logging.getLogger("TradingEngine.Analysis")

def analyze_stock(df):
    try:
        # --- RÉCUPÉRATION DU CONTEXTE GÉOPOLITIQUE ---
        geo_score, geo_verdict, _ = analyze_global_risk()
        
        if df is None or len(df) < 30:
            return "Neutre", "Données insuffisantes", 50, 0, 0, None, 0, 0, 0
            
        # --- NORMALISATION DES COLONNES (Gère tous les formats de yfinance) ---
        new_columns = []
        for col in df.columns:
            if isinstance(col, tuple):
                new_columns.append(str(col[0]).lower())
            else:
                new_columns.append(str(col).lower())
        df.columns = new_columns
            
        # --- CALCULS TECHNIQUES AVANCÉS (Inspirés par la finance quantitative) ---
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        if len(df) >= 200:
            df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True) # Force de la tendance
        df.ta.bbands(length=20, std=2, append=True) # Volatilité
        
        last = df.iloc[-1]
        close = last.get('close', 0)
        rsi = last.get('RSI_14', 50)
        adx = last.get('ADX_14', 0)
        mm20 = last.get('SMA_20', 0)
        mm50 = last.get('SMA_50', 0)
        mm200 = last.get('SMA_200')
        bb_upper = last.get('BBU_20_2.0', 0)
        bb_lower = last.get('BBL_20_2.0', 0)
        
        reco, reason = "Conserver", "Le titre est en phase d'attente. Aucun signal fort d'achat ou de vente n'est détecté pour le moment."
        
        # --- LOGIQUE DE DÉCISION MULTI-FACTEURS ---
        
        # 1. Évaluation de la Force de Tendance (ADX)
        trend_status = "stable"
        if adx > 25: trend_status = "bien orientée"
        if adx > 50: trend_status = "très forte (attention, le mouvement pourrait s'essouffler)"

        if mm200 and not pd.isna(mm200):
            if close > mm200: # Tendance de fond HAUSSIÈRE
                if rsi < 40:
                    reco, reason = "Achat", f"Le titre est dans une bonne dynamique à long terme (au-dessus de sa moyenne 200 jours). Le RSI ({rsi:.0f}) montre une petite baisse passagère, ce qui offre un bon point d'entrée pour acheter."
                elif rsi > 70:
                    reco, reason = "Prudence", f"La tendance est solide, mais le titre a beaucoup monté récemment (RSI à {rsi:.1f}). Il est préférable d'attendre un petit repli avant d'acheter, ou de prendre quelques bénéfices."
                else:
                    if close > bb_upper:
                        reco, reason = "Achat Fort", f"Signal de force majeur : le titre accélère et sort de son couloir habituel de prix. La tendance est {trend_status}."
                    else:
                        reco, reason = "Conserver", f"La tendance de fond reste positive. Le prix se maintient bien au-dessus de sa moyenne de long terme (200 jours). C'est un comportement sain."
            else: # Tendance de fond BAISSIÈRE
                if rsi > 65:
                    reco, reason = "Vendre", f"Méfiance : le titre tente de remonter mais il reste sous sa tendance de fond (moyenne 200 jours). Le RSI ({rsi:.0f}) indique que ce rebond perd déjà de sa force."
                elif rsi < 25:
                    reco, reason = "Spéculatif", "Le titre a lourdement chuté et semble 'survendu'. Un rebond technique est possible, mais c'est un pari risqué car la tendance générale reste baissière."
                else:
                    reco, reason = "Vendre", "Le titre montre des signes de faiblesse et reste sous sa moyenne mobile 200 jours. La prudence est de mise, la direction reste orientée à la baisse."

        # --- AJUSTEMENT PAR LE RISQUE GÉOPOLITIQUE ---
        if geo_score < 35: # Risque Géopolitique ÉLEVÉ ou ALERTE ROUGE
            if reco in ["Achat", "Achat Fort"]:
                reco = "Prudence"
                reason = f"⚠️ [ALERTE GÉOPOLITIQUE] : {geo_verdict}. Bien que les signaux techniques soient d'achat, le contexte mondial est trop instable pour ouvrir de nouvelles positions."
            elif reco == "Conserver":
                reco = "Prudence"
                reason = f"⚠️ [ALERTE GÉOPOLITIQUE] : {geo_verdict}. La situation globale incite à la prudence malgré une configuration technique neutre."
            elif reco == "Vendre":
                reason = f"🚨 [ALERTE GÉOPOLITIQUE] : {geo_verdict}. La tendance baissière de l'action est aggravée par un risque systémique majeur."

        # 2. Détection de Squeeze de Volatilité
        bb_width = (bb_upper - bb_lower) / mm20 if mm20 != 0 else 1
        if bb_width < 0.05:
            reason += " | NOTE : Les prix sont très resserrés, un mouvement important (hausse ou baisse) se prépare probablement."
        
        return reco, reason, float(rsi), float(mm20), float(mm50), None, float(mm200 or 0), float(close*0.98), float(close*1.05)
    except Exception as e:
        logger.error(f"Analysis Error: {e}")
        return "Erreur", "Problème technique", 50, 0, 0, None, 0, 0, 0
    except Exception as e:
        logger.error(f"Analysis Error: {e}")
        return "Erreur", "Problème technique", 50, 0, 0, None, 0, 0, 0

def analyze_sentiment(news_list):
    if not news_list: return 0, "Neutre"
    
    # --- DICTIONNAIRE FINANCIER PONDÉRÉ (Standard Académique) ---
    FIN_LEXICON = {
        # Positif
        'croissance': 0.8, 'profit': 0.9, 'dividende': 0.7, 'hausse': 0.6, 'envolée': 0.8,
        'acquisition': 0.6, 'contrat': 0.7, 'excédent': 0.8, 'surperformer': 0.9,
        'recommandation': 0.5, 'fusion': 0.6, 'record': 0.8, 'succès': 0.7, 'objectif': 0.5,
        'achat': 0.7, 'strong buy': 1.0, 'positive': 0.6, 'croissant': 0.6,
        
        # Négatif
        'chute': -0.8, 'baisse': -0.6, 'perte': -0.9, 'déficit': -0.9, 'alerte': -0.7,
        'avertissement': -0.8, 'sanction': -0.7, 'effondre': -0.9, 'sous-performer': -0.9,
        'litige': -0.6, 'procès': -0.7, 'dette': -0.5, 'restructuration': -0.4,
        'décevant': -0.7, 'crise': -0.8, 'krach': -1.0, 'vente': -0.7, 'negative': -0.6,
        'inflation': -0.4, 'incertitude': -0.5, 'plonge': -0.8
    }

    sentiments = []
    for n in news_list:
        text = n.get('title', '').lower()
        
        # 1. Analyse par dictionnaire financier (Prioritaire)
        fin_score = 0
        words = text.split()
        matches = 0
        for word, score in FIN_LEXICON.items():
            if word in text:
                fin_score += score
                matches += 1
        
        # Si on a trouvé des termes financiers, on privilégie ce score
        if matches > 0:
            final_score = fin_score / matches
        else:
            # 2. Backup vers TextBlob si aucun mot clé financier n'est trouvé
            blob = TextBlob(text)
            final_score = blob.sentiment.polarity
            
        sentiments.append(final_score)
        
    avg = sum(sentiments) / len(sentiments) if sentiments else 0
    
    # Classification plus fine
    if avg > 0.2: label = "Très Positif"
    elif avg > 0.05: label = "Positif"
    elif avg < -0.2: label = "Très Négatif"
    elif avg < -0.05: label = "Négatif"
    else: label = "Neutre"
    
    return avg, label

def create_stock_chart(df, symbol):
    try:
        fig = go.Figure()
        
        # Chandeliers
        fig.add_trace(go.Candlestick(x=df.index, open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Cours'))
        
        # Moyennes Mobiles
        if 'SMA_20' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], name='MM20', line=dict(color='blue', width=1)))
        
        if 'SMA_50' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['SMA_50'], name='MM50', line=dict(color='orange', width=1.5)))
            
        if 'SMA_200' in df.columns:
            fig.add_trace(go.Scatter(x=df.index, y=df['SMA_200'], name='MM200', line=dict(color='red', width=2)))

        fig.update_layout(
            title=f'Analyse Technique - {symbol}',
            height=500,
            template='plotly_white',
            margin=dict(l=10, r=10, t=50, b=10),
            xaxis_rangeslider_visible=False,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(type="date")
        )
        return fig.to_html(full_html=False, include_plotlyjs='cdn', div_id='main-plotly-chart')
    except Exception as e:
        logger.error(f"Chart Error: {e}")
        return "<p style='color:red;'>Erreur lors de la génération du graphique.</p>"
