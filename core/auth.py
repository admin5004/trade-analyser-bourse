import bcrypt
import secrets
import string
import datetime
from .database import get_db_connection

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def generate_code(length=6):
    return ''.join(secrets.choice(string.digits) for _ in range(length))

def generate_token(length=32):
    return secrets.token_urlsafe(length)

def register_device(user_id, device_id, device_name):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO devices (user_id, device_id, device_name, last_login)
                VALUES (?, ?, ?, ?)
            """, (user_id, device_id, device_name, datetime.datetime.now().isoformat()))
            conn.commit()
            return True
    except Exception:
        return False

def is_device_recognized(user_id, device_id):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
        return cursor.fetchone() is not None
