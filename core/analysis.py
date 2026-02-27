import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from textblob import TextBlob
import logging

logger = logging.getLogger("TradingEngine.Analysis")

def analyze_stock(df):
    try:
        if df is None or len(df) < 30:
            return "Neutre", "Données insuffisantes", 50, 0, 0, None, 0, 0, 0
            
        # --- CALCULS TECHNIQUES AVANCÉS (Inspirés par la finance quantitative) ---
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        if len(df) >= 200:
            df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        df.ta.adx(length=14, append=True) # Force de la tendance
        df.ta.bbands(length=20, std=2, append=True) # Volatilité
        
        last = df.iloc[-1]
        close = last['close']
        rsi = last.get('RSI_14', 50)
        adx = last.get('ADX_14', 0)
        mm200 = last.get('SMA_200')
        bb_upper = last.get('BBU_20_2.0', 0)
        bb_lower = last.get('BBL_20_2.0', 0)
        
        reco, reason = "Conserver", "Le titre consolide horizontalement sans direction claire."
        
        # --- LOGIQUE DE DÉCISION MULTI-FACTEURS ---
        
        # 1. Évaluation de la Force de Tendance (ADX)
        trend_status = "faible"
        if adx > 25: trend_status = "établie"
        if adx > 50: trend_status = "très forte (risque d'épuisement)"

        if mm200 and not pd.isna(mm200):
            if close > mm200: # Tendance de fond HAUSSIÈRE
                if rsi < 40:
                    reco, reason = "Achat", f"Opportunité de rebond sur tendance haussière. Le RSI ({rsi:.0f}) indique une correction saine dans une dynamique de fond positive."
                elif rsi > 70:
                    reco, reason = "Prudence", f"Tendance haussière en surchauffe. Le RSI ({rsi:.1f}) et le prix au-dessus de la MM200 suggèrent une prise de bénéfices prudente."
                else:
                    if close > bb_upper:
                        reco, reason = "Achat Fort", f"Cassure haussière de volatilité. Le titre sort par le haut de ses bandes de Bollinger avec une tendance {trend_status}."
                    else:
                        reco, reason = "Conserver", f"Dynamique positive maintenue. La tendance est {trend_status} et le prix reste bien orienté au-dessus de sa moyenne 200 jours."
            else: # Tendance de fond BAISSIÈRE
                if rsi > 65:
                    reco, reason = "Vendre", f"Rebond technique en zone de résistance. Sous la MM200, le RSI ({rsi:.0f}) montre que le rebond s'essouffle déjà."
                elif rsi < 25:
                    reco, reason = "Spéculatif", "Survente extrême en tendance baissière. Risque élevé de 'couteau qui tombe', mais potentiel de rebond technique violent."
                else:
                    reco, reason = "Vendre", "Le titre reste sous pression. Sous la moyenne mobile 200 jours, les probabilités restent orientées à la baisse."
        
        # 2. Détection de Squeeze de Volatilité (Recherches académiques sur les cycles)
        bb_width = (bb_upper - bb_lower) / last.get('SMA_20', 1)
        if bb_width < 0.05: # Moins de 5% d'écart
            reason += " ATTENTION : Squeeze de volatilité détecté. Un mouvement violent (hausse ou baisse) est imminent."
        
        return reco, reason, float(rsi), float(last.get('SMA_20', 0)), float(last.get('SMA_50', 0)), None, float(mm200 or 0), float(close*0.98), float(close*1.05)
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
