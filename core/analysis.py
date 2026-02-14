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
        
        reco, reason = "Conserver", "Analyse technique neutre"
        
        if mm200 and not pd.isna(mm200):
            if close > mm200:
                if rsi < 45: reco, reason = "Achat", "Tendance haussière & zone d'achat"
                else: reco, reason = "Conserver", "Tendance haussière confirmée"
            else:
                if rsi > 65: reco, reason = "Vente", "Tendance baissière & surachat"
                else: reco, reason = "Prudence", "Sous la moyenne mobile 200"
        
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
