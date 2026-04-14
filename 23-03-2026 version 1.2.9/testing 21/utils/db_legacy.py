import logging

import pyodbc

from config import LocalDbConfig

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """
    Conexión pyodbc al mismo servidor/base que SQLAlchemy (LocalDbConfig).
    En Linux use LOCAL_DB_USER + LOCAL_DB_PASS; en Windows dev puede usarse Trusted_Connection.
    """

    @classmethod
    def get_connection(cls):
        conn_str = LocalDbConfig.get_pyodbc_connection_string()
        try:
            return pyodbc.connect(conn_str, timeout=30)
        except Exception as e:
            logger.error('Error de conexión BD local (panel): %s', e)
            raise
