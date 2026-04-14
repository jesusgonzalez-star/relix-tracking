import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()
CONN_STR = (
    f"Driver={{{os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
    f"Server={os.getenv('DB_SERVER', '5CD5173D14\\SQLEXPRESS')};"
    f"Database={os.getenv('DB_NAME', 'Softland_Mock')};"
    f"Trusted_Connection={os.getenv('DB_TRUSTED_CONNECTION', 'yes')};"
)

try:
    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    cursor.execute("SELECT TABLE_SCHEMA + '.' + TABLE_NAME FROM INFORMATION_SCHEMA.TABLES")
    tables = [r[0] for r in cursor.fetchall()]
    with open('tables.txt', 'w') as f:
        f.write('\n'.join(tables))
    print("Done")
except Exception as e:
    with open('tables.txt', 'w') as f:
        f.write(str(e))
