"""
Constantes y utilidades SQL reutilizables.
Centraliza patrones que se repiten decenas de veces en las rutas.
"""
import logging
from contextlib import contextmanager

import pyodbc

from config import SoftlandConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fragmentos SQL reutilizables
# ---------------------------------------------------------------------------

def norm_estado(alias: str, col: str = "Estado") -> str:
    """UPPER(LTRIM(RTRIM(REPLACE(COALESCE(<alias>.<col>, ''), '_', ' '))))"""
    return (
        f"UPPER(LTRIM(RTRIM(REPLACE(COALESCE({alias}.{col}, ''), '_', ' '))))"
    )


def norm_estado_linea(alias: str) -> str:
    """Normalización para EstadoLinea (usa ISNULL en vez de COALESCE por costumbre SQL Server)."""
    return (
        f"UPPER(LTRIM(RTRIM(REPLACE(ISNULL({alias}.EstadoLinea, ''), '_', ' '))))"
    )


# Condición reutilizable: excluir envíos anulados/cancelados
EXCLUDED_STATES = "('ANULADO', 'CANCELADO')"


def where_active_envio(alias: str) -> str:
    """Cláusula WHERE para excluir envíos anulados/cancelados."""
    return f"{norm_estado(alias)} NOT IN {EXCLUDED_STATES}"


# ---------------------------------------------------------------------------
# Context manager para conexiones Softland (read-only)
# ---------------------------------------------------------------------------

@contextmanager
def softland_connection(timeout: int | None = None):
    """
    Context manager para conexiones de solo lectura a Softland ERP.
    Uso:
        with softland_connection() as cursor:
            cursor.execute("SELECT ...")
    """
    conn = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=timeout or SoftlandConfig.DB_TIMEOUT)
    try:
        yield conn, conn.cursor()
    finally:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def softland_cursor(timeout: int | None = None):
    """Versión simplificada que solo entrega el cursor."""
    with softland_connection(timeout) as (conn, cursor):
        yield cursor
