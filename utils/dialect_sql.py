"""
Helpers SQL para la base local MariaDB/MySQL.
Softland (SQL Server) sigue igual y no usa este módulo.

Uso:
    from utils.dialect_sql import now_sql, list_tables_sql, cast_decimal

    cursor.execute(f"UPDATE X SET UpdatedAt = {now_sql()} WHERE Id = ?", (id,))
    cursor.execute(list_tables_sql())
    cursor.execute(f"SELECT {cast_decimal('Qty')} AS q FROM ...")
"""
from __future__ import annotations


def now_sql() -> str:
    """Expresión SQL para el timestamp actual UTC (MariaDB)."""
    return "UTC_TIMESTAMP()"


def list_tables_sql() -> str:
    """Query para listar tablas de la BD actual (MariaDB)."""
    return (
        "SELECT TABLE_NAME FROM information_schema.tables "
        "WHERE table_schema = DATABASE()"
    )


def table_exists_sql() -> str:
    """Query parametrizada para verificar si existe una tabla por nombre (MariaDB)."""
    return (
        "SELECT TABLE_NAME FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND TABLE_NAME = ?"
    )


def cast_decimal(expr: str, precision: int = 18, scale: int = 4) -> str:
    """Devuelve ``CAST(expr AS DECIMAL(p,s))`` (MariaDB)."""
    return f"CAST({expr} AS DECIMAL({precision},{scale}))"


def autoincrement_sql() -> str:
    """Palabra clave para columnas autoincrement en DDL crudo (MariaDB)."""
    return "AUTO_INCREMENT"


def quote_ident(name: str) -> str:
    """Escapa un identificador (tabla/columna) con backticks MariaDB."""
    if not name or not all(c.isalnum() or c == '_' for c in name):
        raise ValueError(f'Identificador no válido: {name!r}')
    return f'`{name}`'
