import mariadb
import config
import logging
import sys
import asyncio

try:
    pool_connection = mariadb.connect(
        user=config.DB_USER,
        password=config.DB_PASS,
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
        pool_name="mypool",
        pool_size=10,
    )
    logging.info("[DBManager] 🔗 Connected to DB successfully using connection pool.")
except mariadb.Error as e:
    logging.error(f"[DBManager] ❌ Error connecting to DB: {e}")
    sys.exit(1)

def get_connection():
    """
    Récupère une connexion depuis le pool. 
    Notez que si une connexion existe déjà dans le pool, 
    mariadb.connect() avec le même pool_name renverra une connexion du pool.
    """
    return mariadb.connect(
        user=config.DB_USER,
        password=config.DB_PASS,
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
        pool_name="mypool"
    )

async def run_db_query(query: str, params: tuple = (), commit: bool = False, fetch_one: bool = False, fetch_all: bool = False):
    """
    Exécute une requête de manière asynchrone en déléguant l'appel bloquant à un thread séparé.
    Pour chaque requête, on obtient une connexion du pool et on la ferme après usage (renvoyée au pool).
    """
    def _execute():
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(query, params)
        result = None
        if commit:
            conn.commit()
        elif fetch_one:
            result = cursor.fetchone()
        elif fetch_all:
            result = cursor.fetchall()
        cursor.close()
        conn.close()
        return result

    return await asyncio.to_thread(_execute)