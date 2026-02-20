import sqlite3
import bcrypt
import sys
import os

DB_PATH = 'users.db'

def hash_password(password):
    # bcrypt.hashpw retourne des bytes, il faut décoder pour stocker en string dans la DB comme le fait l'app
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def update_password(email, new_password):
    if not os.path.exists(DB_PATH):
        print(f"Base de données non trouvée : {DB_PATH}")
        return False

    hashed = hash_password(new_password)
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Vérifier si l'utilisateur existe
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        
        if not user:
            print(f"L'utilisateur {email} n'existe pas. Création en cours...")
            # Créer l'utilisateur s'il n'existe pas
            from datetime import datetime
            cursor.execute("INSERT INTO users (email, password_hash, created_at, is_active) VALUES (?, ?, ?, 1)", 
                         (email, hashed, datetime.now().isoformat()))
            print(f"Utilisateur {email} créé.")
        else:
            # Mettre à jour le mot de passe et activer le compte
            cursor.execute("UPDATE users SET password_hash = ?, is_active = 1 WHERE email = ?", (hashed, email))
            print(f"Mot de passe mis à jour pour {email}.")
            
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Erreur : {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python reset_password.py <email> <new_password>")
        sys.exit(1)
        
    email = sys.argv[1]
    password = sys.argv[2]
    update_password(email, password)
