import pyodbc
from config import SoftlandConfig
from utils.errors import APIError
import logging

logger = logging.getLogger(__name__)

class SoftlandService:
    @staticmethod
    def get_connection():
        """Obtiene una conexión Read-Only hacia el ERP"""
        try:
            return pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
        except Exception as e:
            logger.error("Error conectando a Softland: %s", e)
            raise APIError("No se pudo conectar al ERP Softland", status_code=503) from e

    @staticmethod
    def obtener_detalle_oc(num_oc: int):
        """
        Consulta estrictamente de LECTURA al ERP usando JOINs.
        Devuelve el encabezado de la OC y la lista de todos sus productos.
        """
        conn = None
        try:
            conn = SoftlandService.get_connection()
            cursor = conn.cursor()
            
            # 1. Obtener Encabezado (Proveedor, etc)
            header_query = """
                SELECT 
                    OC.NumOc AS Folio, 
                    COALESCE(MAX(Aux.NomAux), 'Sin Proveedor') AS NomProv, 
                    OC.FechaOC AS FechaEmision,
                    MAX(CASE WHEN G.Orden IS NOT NULL THEN 1 ELSE 0 END) AS TieneGuiaEntrada
                FROM softland.OW_vsnpTraeEncabezadoOCompra OC
                LEFT JOIN softland.NW_OW_VsnpSaldoDetalleOC S ON OC.NumOc = S.numoc
                LEFT JOIN softland.EC_VsnpTraeAuxiliaresLogCwtauxi Aux ON S.Codaux = Aux.CodAux
                LEFT JOIN softland.IW_vsnpGuiasEntradaxOC G ON OC.NumOc = G.Orden
                WHERE OC.NumOc = ?
                GROUP BY OC.NumOc, OC.FechaOC
            """
            cursor.execute(header_query, (num_oc,))
            header_row = cursor.fetchone()
            
            if not header_row:
                raise APIError(f"Orden de Compra {num_oc} no encontrada en Softland", status_code=404)
                
            # 2. Obtener Lista de Productos
            productos_query = """
                SELECT 
                    P.CodProd AS codigo,
                    MAX(P.DesProd) AS descripcion,
                    COALESCE(
                        MAX(NULLIF(LTRIM(RTRIM(CAST(OD.DetProd AS NVARCHAR(4000)))), '')),
                        MAX(NULLIF(LTRIM(RTRIM(P.Desprod2)), ''))
                    ) AS descripcion_editada,
                    MAX(S.cantidadOC) AS cantidad,
                    MAX(S.ingresada) AS cantidad_recibida
                FROM softland.ow_vsnpMovimIWDetalleOC D
                JOIN softland.IW_vsnpProductos P ON D.codprod = P.CodProd
                LEFT JOIN softland.NW_OW_VsnpSaldoDetalleOC S ON D.numoc = S.numoc AND D.codprod = S.codprod
                LEFT JOIN softland.owordendet OD ON S.numinteroc = OD.NumInterOC AND S.codprod = OD.CodProd
                WHERE D.numoc = ?
                GROUP BY P.CodProd, P.DesProd
                ORDER BY P.DesProd
            """
            cursor.execute(productos_query, (num_oc,))
            
            # Conversión estricta a diccionarios enlazando los nombres de columna del cursor
            productos = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
                
            return {
                "folio": header_row[0],
                "proveedor": header_row[1],
                "fecha_emision": header_row[2],
                "guia_entrada": bool(header_row[3] or 0),
                "productos": productos
            }
            
        except APIError:
            raise
        except Exception as e:
            logger.error("Error consultando OC %s: %s", num_oc, e)
            raise APIError("Error interno al consultar el ERP", status_code=500) from e
        finally:
            if conn:
                conn.close()
