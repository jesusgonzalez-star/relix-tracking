import pyodbc
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

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
    cursor.execute("SELECT Id, Nombre FROM Roles")
    roles = {r[1]: r[0] for r in cursor.fetchall()}

    admin_h = generate_password_hash('Admin123!', method='pbkdf2:sha256', salt_length=16)
    bodega_h = generate_password_hash('Bodega123!', method='pbkdf2:sha256', salt_length=16)
    cliente_h = generate_password_hash('Cliente123!', method='pbkdf2:sha256', salt_length=16)

    # Upsert Bodega
    cursor.execute("SELECT Id FROM UsuariosSistema WHERE Usuario = 'bodega'")
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE UsuariosSistema SET PasswordHash = ?, RolId = ?, Activo = 1 WHERE Usuario = 'bodega'", (bodega_h, roles['BODEGA']))
    else:
        cursor.execute("UPDATE UsuariosSistema SET Usuario='bodega', PasswordHash=?, Activo=1 WHERE Usuario='bodega1'", (bodega_h,))
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO UsuariosSistema (Usuario, PasswordHash, NombreCompleto, Email, RolId, Activo) VALUES (?, ?, ?, ?, ?, 1)",
                           ('bodega', bodega_h, 'Bodega Base', 'bodega@test.com', roles['BODEGA']))

    # Upsert Cliente
    cursor.execute("SELECT Id FROM UsuariosSistema WHERE Usuario = 'cliente'")
    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE UsuariosSistema SET PasswordHash = ?, RolId = ?, Activo = 1 WHERE Usuario = 'cliente'", (cliente_h, roles['CLIENTE']))
    else:
        cursor.execute("UPDATE UsuariosSistema SET Usuario='cliente', PasswordHash=?, Activo=1 WHERE Usuario='cliente1'", (cliente_h,))
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO UsuariosSistema (Usuario, PasswordHash, NombreCompleto, Email, RolId, Activo) VALUES (?, ?, ?, ?, ?, 1)",
                           ('cliente', cliente_h, 'Cliente Base', 'cliente@test.com', roles['CLIENTE']))

    conn.commit()
    cursor.execute("SELECT Usuario, Activo, r.Nombre FROM UsuariosSistema u JOIN Roles r ON u.RolId = r.Id")
    for r in cursor.fetchall():
        print(f"User: {r[0]}, Active: {r[1]}, Role: {r[2]}")
    conn.close()
    
except Exception as e:
    import traceback
    traceback.print_exc()
