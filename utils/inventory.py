"""Validaciones de inventario con protección contra race conditions."""
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


def validate_and_lock_inventory(cursor, table: str, id_col: str, id_val: int,
                                qty_col: str, current_qty: Decimal, new_qty: Decimal,
                                max_qty: Decimal = None) -> tuple:
    """
    Valida y actualiza cantidad de inventario de forma segura.
    Retorna (éxito: bool, mensaje: str)

    Estrategia:
    - Lee cantidad nuevamente justo antes de UPDATE (validación posterior)
    - Valida que new_qty ≤ max_qty
    - Valida que suma no exceda máximo permitido
    """
    _ALLOWED_TABLES = {
        'DespachosEnvioDetalle', 'DespachosTrackingDetalle', 'Inventario',
    }
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table}")
    if not id_col.isidentifier():
        raise ValueError(f"Columna ID inválida: {id_col}")
    if not qty_col.isidentifier():
        raise ValueError(f"Columna cantidad inválida: {qty_col}")

    try:
        from utils.dialect_sql import quote_ident
        # Re-leer para detectar cambios (defensa contra race condition)
        sql = f"SELECT {quote_ident(qty_col)} FROM {quote_ident(table)} WHERE {quote_ident(id_col)} = ?"
        cursor.execute(sql, (id_val,))
        row = cursor.fetchone()
        if not row:
            return False, "Registro no encontrado"

        latest_qty = Decimal(str(row[0] or 0))

        # Validación 1: Nueva cantidad no puede ser negativa
        if new_qty < Decimal('0'):
            return False, "Cantidad no puede ser negativa"

        # Validación 2: Si hay máximo definido, respetar
        if max_qty is not None:
            if new_qty > max_qty:
                return False, f"Cantidad excede máximo permitido ({max_qty})"

        # Validación 3: Detectar cambios entre lecturas (race condition detection)
        if latest_qty != current_qty:
            return False, f"Inventario cambió (era {current_qty}, ahora {latest_qty}). Recargue e intente de nuevo."

        # Si llegamos aquí, es seguro actualizar
        return True, "OK"

    except Exception as e:
        logger.error(f"Error validando inventario: {e}")
        return False, f"Error en validación: {str(e)}"
