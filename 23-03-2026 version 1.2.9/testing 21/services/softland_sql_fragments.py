"""
Fragmentos SQL reutilizables para consultas Softland (dashboard bodega, entrega parcial, FAENA).

Centralizar el OUTER APPLY evita divergencias y facilita sustituirlo por una vista agregada indexada.

Notas de escalado (panel arma SQL dinámico en frontend_routes.py):

- Evitar OUTER APPLY por fila sobre NW_OW_VsnpSaldoDetalleOC cuando baste un JOIN a un agregado
  pre-calculado o una vista materializada en SQL Server (QtySolicitadaTotal / QtyIngresadaTotal por NumOc).
- Mantener filtros sargables: NumOc, fechas con TRY_CONVERT donde aplique; evitar funciones sobre la
  columna indexada en el lado izquierdo del predicado cuando sea posible.
- Paginar con ORDER BY + OFFSET/FETCH; no traer todo el maestro ERP a Python.
- Cache corto en memoria (TTL) por clave de filtro; en multi-worker usar un store compartido (p. ej. Redis).
"""

# Agregado por OC sobre NW_OW_VsnpSaldoDetalleOC (mismo alias softland_aggr que usa el dashboard).
SOFTLAND_OC_SALDO_AGG_APPLY = """
                            OUTER APPLY (
                                SELECT
                                    COUNT(1) AS TotalLineas,
                                    SUM(TRY_CONVERT(DECIMAL(18,4), COALESCE(SD.cantidadOC, 0))) AS QtySolicitadaTotal,
                                    SUM(TRY_CONVERT(DECIMAL(18,4), COALESCE(SD.ingresada, 0))) AS QtyIngresadaTotal
                                FROM softland.NW_OW_VsnpSaldoDetalleOC SD WITH (NOLOCK)
                                WHERE SD.numoc = OC.NumOc
                            ) softland_aggr"""
