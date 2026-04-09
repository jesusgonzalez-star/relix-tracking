import pyodbc
from config import LocalDbConfig

class DatabaseConnection:
    """Gestor de conexiones transaccionales para consultas heredadas del frontend (Jinja2)"""
    @classmethod
    def get_connection(cls):
        # Genera la cadena RAW (Driver, Server, Database) desde LocalDbConfig
        # Por seguridad y simplicidad, recreamos la cadena usando Trusted_Connection
        conn_str = (
            f"Driver={{ODBC Driver 17 for SQL Server}};"
            f"Server={LocalDbConfig.LOCAL_SERVER};"
            f"Database={LocalDbConfig.LOCAL_DB_NAME};"
            f"Trusted_Connection=yes;"
        )
        try:
            return pyodbc.connect(conn_str, timeout=30)
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error de conexión GUI: {e}")
            raise
