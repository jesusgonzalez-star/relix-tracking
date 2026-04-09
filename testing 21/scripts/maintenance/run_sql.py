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
    conn.autocommit = True
    cursor = conn.cursor()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    sql_path = os.path.join(base_dir, 'database_softland_tracking.sql')
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql = f.read()

    # Split by GO blocks
    blocks = [b.strip() for b in sql.split('GO') if b.strip()]

    for block in blocks:
        try:
            cursor.execute(block)
            print("Successfully executed a block.")
        except Exception as e:
            if "already exists" in str(e) or "already an object named" in str(e):
                print("Object already exists.")
            else:
                print(f"Error executing block: {e}")

    conn.close()
    print("Database schema updated successfully.")
except Exception as e:
    print(f"Connection/execution error: {e}")
