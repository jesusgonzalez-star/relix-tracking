import logging
import threading
import time

import pyodbc

from config import SoftlandConfig
from utils.errors import APIError

logger = logging.getLogger(__name__)

# pyodbc.pooling=True es el default; lo declaramos explícitamente para que cualquier
# import posterior no lo deshabilite por accidente. Activa el pool ODBC a nivel driver.
pyodbc.pooling = True

# Cache en memoria para obtener_detalle_oc (TTL configurable vía SOFTLAND_OC_CACHE_TTL).
_OC_CACHE: dict[int, tuple[float, dict]] = {}
_OC_CACHE_LOCK = threading.Lock()
_OC_CACHE_TTL = 300  # segundos; sobrescribible desde SoftlandConfig si se define.


def _cache_get(num_oc: int):
    ttl = getattr(SoftlandConfig, 'OC_CACHE_TTL', _OC_CACHE_TTL)
    with _OC_CACHE_LOCK:
        entry = _OC_CACHE.get(num_oc)
        if not entry:
            return None
        ts, data = entry
        if (time.time() - ts) > ttl:
            _OC_CACHE.pop(num_oc, None)
            return None
        return data


def _cache_put(num_oc: int, data: dict):
    with _OC_CACHE_LOCK:
        _OC_CACHE[num_oc] = (time.time(), data)
        # Evita crecimiento sin cota: recorta a los 500 más recientes.
        if len(_OC_CACHE) > 500:
            oldest = sorted(_OC_CACHE.items(), key=lambda kv: kv[1][0])[:-500]
            for k, _ in oldest:
                _OC_CACHE.pop(k, None)


def cache_invalidate(num_oc: int | None = None):
    """Invalida cache de OCs. Llamar tras cambios en Softland conocidos."""
    with _OC_CACHE_LOCK:
        if num_oc is None:
            _OC_CACHE.clear()
        else:
            _OC_CACHE.pop(num_oc, None)


class SoftlandService:
    @staticmethod
    def get_connection():
        """Obtiene una conexión Read-Only hacia el ERP (usa pool ODBC)."""
        try:
            return pyodbc.connect(
                SoftlandConfig.get_connection_string(),
                timeout=SoftlandConfig.DB_TIMEOUT,
                readonly=True,
            )
        except Exception as e:
            logger.error("Error conectando a Softland: %s", e)
            raise APIError("No se pudo conectar al ERP Softland", status_code=503) from e

    @staticmethod
    def obtener_detalle_oc(num_oc: int, use_cache: bool = True):
        """
        Consulta estrictamente de LECTURA al ERP con reintentos y cache TTL.
        Reintenta errores transitorios de red (máx 2 veces, backoff exponencial).
        404 (OC inexistente) no reintenta ni se cachea.
        """
        if use_cache:
            cached = _cache_get(num_oc)
            if cached is not None:
                return cached

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                data = SoftlandService._fetch_detalle_oc(num_oc)
                if use_cache:
                    _cache_put(num_oc, data)
                return data
            except APIError as e:
                # No reintentar errores de negocio (404 OC no existe, etc.).
                if e.status_code in (404, 400):
                    raise
                last_exc = e
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise
            except Exception as e:
                last_exc = e
                if attempt < 2:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                logger.error("Error consultando OC %s tras reintentos: %s", num_oc, e)
                raise APIError("Error interno al consultar el ERP", status_code=500) from e
        # Unreachable, salvaguarda
        raise APIError("Error interno al consultar el ERP", status_code=500) from last_exc

    @staticmethod
    def _fetch_detalle_oc(num_oc: int):
        conn = None
        cursor = None
        try:
            conn = SoftlandService.get_connection()
            cursor = conn.cursor()

            header_query = """
                SELECT
                    OC.NumOc AS Folio,
                    COALESCE(MAX(Aux.NomAux), 'Sin Proveedor') AS NomProv,
                    OC.FechaOC AS FechaEmision,
                    MAX(CASE WHEN G.Orden IS NOT NULL THEN 1 ELSE 0 END) AS TieneGuiaEntrada
                FROM softland.OW_vsnpTraeEncabezadoOCompra OC
                LEFT JOIN softland.owordencom OH ON OH.NumInterOC = OC.NumInterOc
                LEFT JOIN softland.EC_VsnpTraeAuxiliaresLogCwtauxi Aux ON OH.CodAux = Aux.CodAux
                LEFT JOIN softland.IW_vsnpGuiasEntradaxOC G ON OC.NumOc = G.Orden
                WHERE OC.NumOc = ?
                GROUP BY OC.NumOc, OC.FechaOC
            """
            cursor.execute(header_query, (num_oc,))
            header_row = cursor.fetchone()

            if not header_row:
                raise APIError(f"Orden de Compra {num_oc} no encontrada en Softland", status_code=404)

            productos_query = """
                SELECT
                    P.CodProd AS codigo,
                    MAX(P.DesProd) AS descripcion,
                    MAX(NULLIF(LTRIM(RTRIM(CAST(OD.DetProd AS NVARCHAR(4000)))), '')) AS descripcion_editada,
                    SUM(TRY_CONVERT(DECIMAL(18,4), COALESCE(OD.Cantidad, 0))) AS cantidad,
                    SUM(TRY_CONVERT(DECIMAL(18,4), COALESCE(OD.Recibido, 0))) AS cantidad_recibida
                FROM softland.OW_vsnpTraeEncabezadoOCompra OC
                INNER JOIN softland.owordendet OD ON OD.NumInterOC = OC.NumInterOc
                INNER JOIN softland.IW_vsnpProductos P ON P.CodProd = OD.CodProd
                WHERE OC.NumOc = ?
                GROUP BY P.CodProd, P.DesProd
                ORDER BY P.DesProd
            """
            cursor.execute(productos_query, (num_oc,))
            productos = [
                dict(zip([column[0] for column in cursor.description], row))
                for row in cursor.fetchall()
            ]

            return {
                "folio": header_row[0],
                "proveedor": header_row[1],
                "fecha_emision": header_row[2],
                "guia_entrada": bool(header_row[3] or 0),
                "productos": productos,
            }
        finally:
            # Cierre garantizado de cursor y conexión incluso en caminos de excepción.
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
