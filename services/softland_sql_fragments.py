"""
Fragmentos SQL reutilizables para consultas Softland (dashboard bodega, entrega parcial, FAENA).

Centralizar los fragmentos evita divergencias.

Notas de escalado (panel arma SQL dinámico en frontend_routes.py):

- Mantener filtros sargables: NumOc, fechas con TRY_CONVERT donde aplique; evitar funciones sobre la
  columna indexada en el lado izquierdo del predicado cuando sea posible.
- Paginar con ORDER BY + OFFSET/FETCH; no traer todo el maestro ERP a Python.
- Cache corto en memoria (TTL) por clave de filtro; en multi-worker usar un store compartido (p. ej. Redis).

Diseño del agregado:
- Antes se usaba la vista ``softland.NW_OW_VsnpSaldoDetalleOC`` pero esa vista invoca la función
  ``softland.ow_fdblRecepNoInvOC`` que requiere permisos EXECUTE no siempre disponibles.
- El reemplazo usa las tablas base ``owordencom`` (encabezado) + ``owordendet`` (detalle), con las que
  obtenemos las mismas columnas relevantes: numoc, Codaux, codprod, cantidadOC (=Cantidad),
  ingresada (=Recibido), numlinea, saldo.
"""

# Derived table que reemplaza a softland.NW_OW_VsnpSaldoDetalleOC usando tablas base.
# Expone las mismas columnas clave que el resto del código consumía del view original.
SOFTLAND_SALDO_DETALLE_OC_SRC = """
    (SELECT
        OH.NumOC       AS numoc,
        OH.NumInterOC  AS numinteroc,
        OH.CodAux      AS Codaux,
        D.CodProd      AS codprod,
        D.NumLinea     AS numlinea,
        D.Cantidad     AS cantidadOC,
        D.Recibido     AS ingresada,
        D.Saldo        AS saldo
     FROM softland.owordencom OH WITH (NOLOCK)
     INNER JOIN softland.owordendet D WITH (NOLOCK) ON D.NumInterOC = OH.NumInterOC)
"""


# Agregado por OC (mismo alias softland_aggr que usa el dashboard).
SOFTLAND_OC_SALDO_AGG_APPLY = """
                            OUTER APPLY (
                                SELECT
                                    COUNT(1) AS TotalLineas,
                                    SUM(TRY_CONVERT(DECIMAL(18,4), COALESCE(D.Cantidad, 0))) AS QtySolicitadaTotal,
                                    SUM(TRY_CONVERT(DECIMAL(18,4), COALESCE(D.Recibido, 0))) AS QtyIngresadaTotal
                                FROM softland.owordendet D WITH (NOLOCK)
                                WHERE D.NumInterOC = OC.NumInterOc
                            ) softland_aggr"""
