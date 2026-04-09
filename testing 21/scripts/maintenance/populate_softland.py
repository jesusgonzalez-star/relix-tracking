import pyodbc
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
CONN_STR = (
    f"Driver={{{os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
    f"Server={os.getenv('DB_SERVER', '5CD5173D14\\SQLEXPRESS')};"
    f"Database={os.getenv('DB_NAME', 'Softland_Mock')};"
    f"Trusted_Connection={os.getenv('DB_TRUSTED_CONNECTION', 'yes')};"
)


def populate_mock():
    try:
        conn = pyodbc.connect(CONN_STR)
        cursor = conn.cursor()

        # 1. Auxiliares (Proveedores)
        proveedores = [
            ('PROV01', 'Aguas Del Norte SPA'),
            ('PROV02', 'Filtros Industriales Limitada'),
            ('PROV03', 'Suministros Hidráulicos S.A.')
        ]
        cursor.execute("DELETE FROM softland.EC_VsnpTraeAuxiliaresLogCwtauxi")
        cursor.executemany("INSERT INTO softland.EC_VsnpTraeAuxiliaresLogCwtauxi (CodAux, NomAux) VALUES (?, ?)", proveedores)

        # 2. Productos
        productos = [
            ('P001', 'Filtro de Ósmosis Inversa', 'UN'),
            ('P002', 'Membrana 8x40', 'UN'),
            ('P003', 'Bomba Dosificadora', 'UN')
        ]
        cursor.execute("DELETE FROM softland.IW_vsnpProductos")
        cursor.executemany("INSERT INTO softland.IW_vsnpProductos (CodProd, DesProd, DesUMed) VALUES (?, ?, ?)", productos)

        now = datetime.now()

        # CLEAR ALL
        cursor.execute("DELETE FROM DespachosTracking")
        cursor.execute("DELETE FROM softland.IW_vsnpGuiasEntradaxOC")
        cursor.execute("DELETE FROM softland.Dw_VsnpRequerimientosMateriasPrimas")
        cursor.execute("DELETE FROM softland.NW_OW_VsnpSaldoDetalleOC")
        cursor.execute("DELETE FROM softland.ow_vsnpMovimIWDetalleOC")
        cursor.execute("DELETE FROM softland.OW_vsnpTraeEncabezadoOCompra")

        # 3. Órdenes de Compra
        # OC 1001: PENDIENTE EN SOFTLAND (Solo OC, sin Guía)
        cursor.execute("INSERT INTO softland.OW_vsnpTraeEncabezadoOCompra (NumOc, Fecha, CentroCosto) VALUES (?, ?, ?)", (1001, now - timedelta(days=5), 'CC01'))
        cursor.execute("INSERT INTO softland.ow_vsnpMovimIWDetalleOC (numoc, codprod) VALUES (?, ?)", (1001, 'P001'))
        cursor.execute("INSERT INTO softland.NW_OW_VsnpSaldoDetalleOC (numoc, codprod, Codaux) VALUES (?, ?, ?)", (1001, 'P001', 'PROV01'))
        cursor.execute("INSERT INTO softland.Dw_VsnpRequerimientosMateriasPrimas (Orden, Solicitante) VALUES (?, ?)", (1001, 'Minera Escondida'))

        # OC 1002: EN BODEGA (Tiene Guía)
        cursor.execute("INSERT INTO softland.OW_vsnpTraeEncabezadoOCompra (NumOc, Fecha, CentroCosto) VALUES (?, ?, ?)", (1002, now - timedelta(days=4), 'CC01'))
        cursor.execute("INSERT INTO softland.ow_vsnpMovimIWDetalleOC (numoc, codprod) VALUES (?, ?)", (1002, 'P002'))
        cursor.execute("INSERT INTO softland.NW_OW_VsnpSaldoDetalleOC (numoc, codprod, Codaux) VALUES (?, ?, ?)", (1002, 'P002', 'PROV02'))
        cursor.execute("INSERT INTO softland.Dw_VsnpRequerimientosMateriasPrimas (Orden, Solicitante) VALUES (?, ?)", (1002, 'Planta Desaladora Norte'))
        cursor.execute("INSERT INTO softland.IW_vsnpGuiasEntradaxOC (DesBode, Orden) VALUES (?, ?)", ('Bodega Central', 1002))

        # OC 1003: DESPACHADO (Tiene Guia + DespachosTracking = En Ruta)
        cursor.execute("INSERT INTO softland.OW_vsnpTraeEncabezadoOCompra (NumOc, Fecha, CentroCosto) VALUES (?, ?, ?)", (1003, now - timedelta(days=3), 'CC02'))
        cursor.execute("INSERT INTO softland.ow_vsnpMovimIWDetalleOC (numoc, codprod) VALUES (?, ?)", (1003, 'P003'))
        cursor.execute("INSERT INTO softland.NW_OW_VsnpSaldoDetalleOC (numoc, codprod, Codaux) VALUES (?, ?, ?)", (1003, 'P003', 'PROV03'))
        cursor.execute("INSERT INTO softland.Dw_VsnpRequerimientosMateriasPrimas (Orden, Solicitante) VALUES (?, ?)", (1003, 'Proyecto Atacama'))
        cursor.execute("INSERT INTO softland.IW_vsnpGuiasEntradaxOC (DesBode, Orden) VALUES (?, ?)", ('Bodega Central', 1003))
        cursor.execute("INSERT INTO DespachosTracking (NumOc, Estado, Transportista, GuiaDespacho) VALUES (?, ?, ?, ?)", (1003, 'En Ruta', 'Transvip Norte', 'GD-003'))

        # OC 1004: ENTREGADO
        cursor.execute("INSERT INTO softland.OW_vsnpTraeEncabezadoOCompra (NumOc, Fecha, CentroCosto) VALUES (?, ?, ?)", (1004, now - timedelta(days=10), 'CC03'))
        cursor.execute("INSERT INTO softland.ow_vsnpMovimIWDetalleOC (numoc, codprod) VALUES (?, ?)", (1004, 'P001'))
        cursor.execute("INSERT INTO softland.NW_OW_VsnpSaldoDetalleOC (numoc, codprod, Codaux) VALUES (?, ?, ?)", (1004, 'P001', 'PROV01'))
        cursor.execute("INSERT INTO softland.Dw_VsnpRequerimientosMateriasPrimas (Orden, Solicitante) VALUES (?, ?)", (1004, 'Aguas Antofagasta'))
        cursor.execute("INSERT INTO softland.IW_vsnpGuiasEntradaxOC (DesBode, Orden) VALUES (?, ?)", ('Bodega Central', 1004))
        cursor.execute("INSERT INTO DespachosTracking (NumOc, Estado, FechaHoraSalida, FechaHoraEntrega, UrlFotoEvidencia, Transportista, GuiaDespacho) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (1004, 'Entregado', now - timedelta(days=2), now - timedelta(days=1), 'https://via.placeholder.com/300', 'Logística Express', 'GD-004'))

        conn.commit()
        print("Mock Data Inserted successfully!")
        conn.close()
    except Exception as e:
        print(f"Error populating: {e}")


if __name__ == '__main__':
    populate_mock()
