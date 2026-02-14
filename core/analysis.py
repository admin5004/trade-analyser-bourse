import pandas as pd
import pandas_ta as ta
import plotly.graph_objects as go
from textblob import TextBlob
import logging

logger = logging.getLogger("TradingEngine.Analysis")

def analyze_stock(df):
    try:
        if df is None or len(df) < 10:
            return "Neutre", "Données insuffisantes", 50, 0, 0, None, 0, 0, 0
            
        df.ta.sma(length=20, append=True)
        df.ta.sma(length=50, append=True)
        if len(df) >= 200:
            df.ta.sma(length=200, append=True)
        df.ta.rsi(length=14, append=True)
        
        last = df.iloc[-1]
        close = last['close']
        rsi = last.get('RSI_14', 50)
        mm200 = last.get('SMA_200')
        
        reco, reason = "Conserver", "Le titre consolide horizontalement sans direction claire."
        
        if mm200 and not pd.isna(mm200):
            if close > mm200:
                if rsi < 35: reco, reason = "Achat", f"Le titre est en tendance haussière long terme (au-dessus de la MM200) mais subit une correction excessive à court terme (RSI à {rsi:.0f}). C'est une opportunité d'achat sur repli."
                elif rsi < 50: reco, reason = "Achat Fort", "Momentum haussier sain. Le prix est au-dessus de sa moyenne 200 jours et le RSI montre que le titre n'est pas encore surchargé."
                elif rsi > 75: reco, reason = "Prudence", "Tendance haussière confirmée mais le titre est en zone de surchauffe (RSI élevé). Risque de prise de bénéfices imminent."
                else: reco, reason = "Conserver", "Le titre maintient sa dynamique haussière au-dessus de la MM200. Pas de signal de retournement, la tendance reste porteuse."
            else:
                if rsi > 65: reco, reason = "Vente", f"Signal de vente technique : le titre est sous sa MM200 (tendance baissière) et tente un rebond qui sature déjà (RSI à {rsi:.0f})."
                elif rsi < 30: reco, reason = "Spéculatif", "Le titre est en pleine chute libre sous la MM200. Bien que survendu, le couteau tombe encore. Attendre une stabilisation."
                else: reco, reason = "Vendre", "Tendance baissière de fond. Le cours est durablement installé sous sa moyenne mobile 200 jours, agissant comme une résistance majeure."
        
        # Ajout d'une analyse de convergence des moyennes mobiles
        mm20 = last.get('SMA_20', 0)
        mm50 = last.get('SMA_50', 0)
        if mm20 > mm50 and close > mm20:
            reason += " Les moyennes mobiles de court terme confirment une accélération positive du cours."
        elif mm20 < mm50 and close < mm20:
            reason += " Le croisement baissier des moyennes mobiles de court terme suggère une poursuite de la correction."
        
        return reco, reason, float(rsi), float(last.get('SMA_20', 0)), float(last.get('SMA_50', 0)), None, float(mm200 or 0), float(close*0.98), float(close*1.05)
    except Exception as e:
        logger.error(f"Analysis Error: {e}")
        return "Erreur", "Problème technique", 50, 0, 0, None, 0, 0, 0

def analyze_sentiment(news_list):
    if not news_list: return 0, "Neutre"
    sentiments = []
    for n in news_list:
        text = n.get('title', '')
        blob = TextBlob(text)
        sentiments.append(blob.sentiment.polarity)
    avg = sum(sentiments) / len(sentiments) if sentiments else 0
    label = "Positif" if avg > 0.1 else "Négatif" if avg < -0.1 else "Neutre"
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
