import pyodbc
from werkzeug.security import generate_password_hash
from config import LocalDbConfig

CONN_STR = LocalDbConfig.get_pyodbc_connection_string()

try:
    conn = pyodbc.connect(CONN_STR)
    cursor = conn.cursor()
    
    admin_h = generate_password_hash('Admin123!', method='pbkdf2:sha256', salt_length=16)
    bodega_h = generate_password_hash('Bodega123!', method='pbkdf2:sha256', salt_length=16)
    cliente_h = generate_password_hash('Cliente123!', method='pbkdf2:sha256', salt_length=16)
    
    cursor.execute("UPDATE UsuariosSistema SET PasswordHash = ? WHERE Usuario = 'admin'", (admin_h,))
    cursor.execute("UPDATE UsuariosSistema SET PasswordHash = ? WHERE Usuario LIKE 'bodega%'", (bodega_h,))
    cursor.execute("UPDATE UsuariosSistema SET PasswordHash = ? WHERE Usuario LIKE 'cliente%'", (cliente_h,))
    conn.commit()
    print("Hashes updated successfully")
    conn.close()
except Exception as e:
    print(f"Error: {e}")
