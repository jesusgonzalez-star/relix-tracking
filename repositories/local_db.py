"""
Transacciones explícitas sobre la BD local (misma cadena que LocalDbConfig / DatabaseConnection).
Útil para agrupar varios UPDATE/INSERT con un solo commit o rollback.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Tuple, Any

from utils.db_legacy import DatabaseConnection

logger = logging.getLogger(__name__)


@contextmanager
def local_db_transaction() -> Generator[Tuple[Any, Any], None, None]:
    """
    Entrega (conn, cursor). Hace commit si el bloque termina sin excepción; rollback si no.
    Cierra la conexión al salir.
    """
    conn = DatabaseConnection.get_connection()
    if not conn:
        raise RuntimeError('No fue posible obtener conexión a la base local')
    cursor = conn.cursor()
    try:
        # Asegurar modo transaccional (autocommit off) para MariaDB.
        if hasattr(conn, 'autocommit') and getattr(conn, 'autocommit', False):
            try:
                conn.autocommit = False
            except Exception:
                pass
        yield conn, cursor
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception as rb_exc:
            logger.warning('Rollback BD local: %s', rb_exc)
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
