import psycopg2
from psycopg2.extras import RealDictCursor

DB_HOST = "localhost"
DB_NAME = "fileshare_db"
DB_USER = "postgres"
DB_PASSWORD = "admin123" 
DB_PORT = "5432"

# Tworzy i zwraca połączenie z bazą danych PostgreSQL 
def get_connection():
    connection = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        port=DB_PORT,
        cursor_factory=RealDictCursor
    )
    return connection

