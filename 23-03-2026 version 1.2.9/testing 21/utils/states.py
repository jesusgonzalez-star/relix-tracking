"""Constantes canónicas de estado para tracking y líneas de envío.

Módulo centralizado: importar desde aquí en lugar de duplicar strings.
"""

# ── Estados de cabecera DespachosTracking / DespachosEnvio ────────────
ST_INGRESADO = 'INGRESADO'
ST_EN_BODEGA = 'EN_BODEGA'
ST_EN_RUTA = 'En Ruta'
ST_ENTREGADO = 'Entregado'
ST_CANCELADO = 'CANCELADO'
ST_ANULADO = 'ANULADO'
ST_PENDIENTE_SOFTLAND = 'PENDIENTE_EN_SOFTLAND'
ST_DISPONIBLE_BODEGA = 'DISPONIBLE EN BODEGA'

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
