import pyodbc
from config import LocalDbConfig

CONN_STR = LocalDbConfig.get_pyodbc_connection_string()

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
