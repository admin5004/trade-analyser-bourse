import requests
import time
import logging
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# Remplacez par votre URL Render (ex: https://votre-app.onrender.com/status)
TARGET_URL = "http://127.0.0.1:5000/status"
CHECK_INTERVAL = 300  # Vérification toutes les 5 minutes
STALE_THRESHOLD = 20  # Alerte si les données ont plus de 20 minutes

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - MONITOR - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("engine_monitor.log"),
        logging.StreamHandler()
    ]
)

def notify_alert(message):
    """Envoie une notification système sur Linux Mint"""
    import os
    try:
        os.system(f'notify-send "⚠️ Trading Engine Alert" "{message}"')
    except Exception:
        pass
    logging.error(f"ALERT: {message}")

def check_status():
    try:
        response = requests.get(TARGET_URL, timeout=10)
        if response.status_code != 200:
            notify_alert(f"Server returned status {response.status_code}")
            return

        data = response.json()
        
        # 1. Vérification du Scheduler
        if not data.get('engine_running'):
            notify_alert("The background engine has STOPPED!")
            return

        # 2. Vérification de la fraîcheur des données
        last_update_str = data.get('last_update')
        if last_update_str:
            last_update = datetime.fromisoformat(last_update_str)
            age = (datetime.now() - last_update).total_seconds() / 60
            
            if age > STALE_THRESHOLD:
                notify_alert(f"Data is stale! Last update was {int(age)} minutes ago.")
            else:
                logging.info(f"Engine Healthy: {data['cached_instruments']} instruments in cache. Age: {int(age)} min.")
        else:
            logging.warning("Engine started but no data loaded yet.")

    except requests.exceptions.RequestException as e:
        notify_alert(f"Connection failed: {e}")

if __name__ == "__main__":
    logging.info(f"Starting monitoring for {TARGET_URL}")
    while True:
        check_status()
        time.sleep(CHECK_INTERVAL)
