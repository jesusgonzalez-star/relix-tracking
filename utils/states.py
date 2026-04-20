"""Constantes canónicas de estado para tracking y líneas de envío.

Módulo centralizado: importar desde aquí en lugar de duplicar strings.

NOTA sobre convención de nombres:
  - Los valores canónicos coinciden con lo almacenado en la BD local.
  - Algunos usan mixed-case ('En Ruta', 'Entregado') por razones legacy;
    cambiarlos requiere migración de datos en tablas existentes y
    refactor de ~40 callsites + templates.
  - Usar siempre _state_in() o normalize_state() de _helpers.py para
    comparaciones seguras, NUNCA comparar con == directamente en código
    nuevo.
"""

# ── Estados de cabecera DespachosTracking / DespachosEnvio ────────────
ST_INGRESADO = 'INGRESADO'
ST_EN_BODEGA = 'EN_BODEGA'
ST_EN_RUTA = 'En Ruta'               # legacy: mixed-case almacenado en BD
ST_ENTREGADO = 'Entregado'           # legacy: mixed-case almacenado en BD
ST_CANCELADO = 'CANCELADO'
ST_ANULADO = 'ANULADO'
ST_PENDIENTE_SOFTLAND = 'PENDIENTE_EN_SOFTLAND'
ST_DISPONIBLE_BODEGA = 'DISPONIBLE EN BODEGA'  # legacy: con espacios en BD

# Conjunto de todos los estados válidos para inserción/actualización
VALID_TRACKING_STATES = frozenset({
    ST_INGRESADO,
    ST_EN_BODEGA,
    ST_EN_RUTA,
    ST_ENTREGADO,
    ST_CANCELADO,
    ST_ANULADO,
    ST_PENDIENTE_SOFTLAND,
    ST_DISPONIBLE_BODEGA,
})

# Mapa de normalización: variantes almacenadas → valor canónico
STORAGE_STATE_MAP = {
    'INGRESADO': ST_INGRESADO,
    'EN BODEGA': ST_EN_BODEGA,
    'EN_BODEGA': ST_EN_BODEGA,
    'DISPONIBLE EN BODEGA': ST_DISPONIBLE_BODEGA,
    'EN RUTA': ST_EN_RUTA,
    'ENTREGADO': ST_ENTREGADO,
    'PENDIENTE EN SOFTLAND': ST_PENDIENTE_SOFTLAND,
    'PENDIENTE_EN_SOFTLAND': ST_PENDIENTE_SOFTLAND,
    'CANCELADO': ST_CANCELADO,
    'ANULADO': ST_ANULADO,
}

# ── Estados de línea de envío (DespachosEnvioDetalle) ─────────────────
LST_EN_RUTA = 'EN_RUTA'
LST_ENTREGADO = 'ENTREGADO'
LST_PARCIAL = 'PARCIAL'
LST_RECHAZADO = 'RECHAZADO'

VALID_LINE_STATES = frozenset({
    LST_EN_RUTA,
    LST_ENTREGADO,
    LST_PARCIAL,
    LST_RECHAZADO,
})

# ── Mapeo API → BD (contrato estable para clientes móviles) ──────────
API_TO_DB_ESTADO = {
    'BODEGA': ST_EN_BODEGA,
    'TRANSITO': ST_EN_RUTA,
    'ENTREGADO': ST_ENTREGADO,
}

# ── Matriz de transiciones válidas para DespachosTracking ─────────────
# Clave: estado actual; valor: conjunto de estados destino permitidos.
# Flujo forward-only. Estados terminales (ENTREGADO, CANCELADO, ANULADO)
# no admiten transición. CANCELADO/ANULADO siempre disponibles como salida
# de emergencia desde cualquier estado no-terminal.
VALID_TRANSITIONS = {
    # Creación inicial: cualquier estado (una OC puede llegar ya en bodega o en ruta).
    None: {ST_INGRESADO, ST_EN_BODEGA, ST_DISPONIBLE_BODEGA, ST_PENDIENTE_SOFTLAND,
           ST_EN_RUTA, ST_ENTREGADO, ST_CANCELADO, ST_ANULADO},
    ST_INGRESADO: {ST_EN_BODEGA, ST_DISPONIBLE_BODEGA, ST_PENDIENTE_SOFTLAND,
                   ST_CANCELADO, ST_ANULADO},
    # PENDIENTE → BODEGA/DISPONIBLE (cuando Softland confirma). Ya no regresa a INGRESADO.
    ST_PENDIENTE_SOFTLAND: {ST_EN_BODEGA, ST_DISPONIBLE_BODEGA,
                            ST_CANCELADO, ST_ANULADO},
    ST_EN_BODEGA: {ST_DISPONIBLE_BODEGA, ST_EN_RUTA, ST_CANCELADO, ST_ANULADO},
    ST_DISPONIBLE_BODEGA: {ST_EN_RUTA, ST_CANCELADO, ST_ANULADO},
    # EN_RUTA: solo avanza (ENTREGADO) o se cancela. No regresa a bodega.
    # Self-transition permitida para re-reportes (ej. GPS pings).
    ST_EN_RUTA: {ST_EN_RUTA, ST_ENTREGADO, ST_CANCELADO, ST_ANULADO},
    ST_ENTREGADO: set(),
    ST_CANCELADO: set(),
    ST_ANULADO: set(),
}


def is_valid_transition(current: str | None, target: str) -> bool:
    """Retorna True si pasar de `current` a `target` es una transición permitida."""
    cur = STORAGE_STATE_MAP.get((current or '').strip().upper().replace('_', ' '),
                                current) if current else None
    allowed = VALID_TRANSITIONS.get(cur, set())
    return target in allowed
