import smtplib
import os
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("TradingEngine.Mailer")

def send_auth_email(target_email, subject, body_html):
    """Envoie un mail via le serveur SMTP de Free."""
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.free.fr")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER") # Votre adresse @free.fr
    smtp_password = os.environ.get("SMTP_PASSWORD") # Votre mot de passe mail Free

    if not smtp_user or not smtp_password:
        logger.error("Configuration SMTP manquante dans le fichier .env")
        return False

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = target_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body_html, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls() # Sécurisation de la connexion
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        logger.error(f"Erreur d'envoi mail : {e}")
        return False
