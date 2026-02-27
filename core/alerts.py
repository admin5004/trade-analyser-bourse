
import logging
from datetime import datetime
from core.mailer import send_auth_email
from core.database import get_db_connection

logger = logging.getLogger("TradingEngine.Alerts")

def scan_for_critical_alerts(market_state):
    """
    Analyse le MARKET_STATE pour trouver des signaux critiques 
    et envoyer des alertes aux utilisateurs concernés.
    """
    alerts = []
    tickers = market_state.get('tickers', {})
    
    for symbol, data in tickers.items():
        reco = data.get('recommendation', '')
        reason = data.get('reason', '')
        rsi = data.get('rsi', 50)
        
        # 1. Détection de Squeeze (imminent mouvement violent)
        if "Squeeze" in reason:
            alerts.append({
                'symbol': symbol,
                'type': 'SQUEEZE DE VOLATILITÉ',
                'description': f"Les bandes de Bollinger se resserrent sur {symbol}. Un mouvement majeur est proche.",
                'priority': 'HAUTE'
            })
            
        # 2. Détection de retournement haussier (RSI survendu + MM200 OK)
        if "Achat" in reco and rsi < 35:
            alerts.append({
                'symbol': symbol,
                'type': 'OPPORTUNITÉ REBOND',
                'description': f"{symbol} est survendu (RSI: {rsi:.1f}) mais reste en tendance haussière long terme.",
                'priority': 'MOYENNE'
            })
            
        # 3. Alerte de surchauffe (RSI > 80)
        if rsi > 80:
            alerts.append({
                'symbol': symbol,
                'type': 'SURCHAUFFE EXTRÊME',
                'description': f"{symbol} est en zone de risque de correction immédiate (RSI: {rsi:.1f}).",
                'priority': 'URGENT'
            })

    if alerts:
        send_global_alert_report(alerts)
    
    return alerts

def send_global_alert_report(alerts):
    """Envoie un rapport récapitulatif des alertes aux administrateurs/utilisateurs."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # On récupère tous les utilisateurs actifs
            cursor.execute("SELECT email FROM users WHERE is_active = 1")
            users = [row[0] for row in cursor.fetchall()]
            
            for email in users:
                # Récupérer les abonnements de l'utilisateur
                cursor.execute("SELECT symbol FROM alert_subscriptions WHERE email = ?", (email,))
                subs = [row[0] for row in cursor.fetchall()]
                
                # Filtrer les alertes pour cet utilisateur
                if subs:
                    user_alerts = [a for a in alerts if a['symbol'] in subs]
                else:
                    # Si aucun abonnement, on envoie tout par défaut (ou rien, selon votre choix)
                    user_alerts = alerts 

                if user_alerts:
                    send_individual_alert(email, user_alerts)
                    
    except Exception as e:
        logger.error(f"Erreur envoi alertes personnalisées: {e}")

def send_individual_alert(email, user_alerts):
    subject = f"🔔 Alertes Personnalisées - {len(user_alerts)} signaux"
    
    html = f"<h2>Vos Alertes de Marché ({datetime.now().strftime('%d/%m %H:%M')})</h2>"
    
    for a in sorted(user_alerts, key=lambda x: x['priority'] == 'HAUTE', reverse=True):
        color = "red" if a['priority'] in ['HAUTE', 'URGENT'] else "orange"
        html += f"""
        <div style="border-left: 5px solid {color}; padding: 10px; margin-bottom: 15px; background: #f9f9f9;">
            <b style="color: {color};">[{a['type']}] {a['symbol']}</b><br>
            {a['description']}
        </div>
        """
    
    html += "<p><small>Vous recevez ce message car vous suivez ces valeurs sur Trading Analyzer Pro.</small></p>"
    send_auth_email(email, subject, html)
    logger.info(f"Alerte envoyée à {email} pour {len(user_alerts)} valeurs.")
