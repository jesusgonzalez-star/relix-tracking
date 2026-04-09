"""
Script para validar y crear la estructura de base de datos necesaria
Ejecutar: python db_setup.py
"""

import pyodbc
import os
from dotenv import load_dotenv
import logging

load_dotenv()

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONN_STR = (
    f"Driver={{{os.getenv('DB_DRIVER', 'ODBC Driver 17 for SQL Server')}}};"
    f"Server={os.getenv('DB_SERVER', '5CD5173D14\\SQLEXPRESS')};"
    f"Database={os.getenv('DB_NAME', 'Softland_Mock')};"
    f"Trusted_Connection={os.getenv('DB_TRUSTED_CONNECTION', 'yes')};"
)

# Scripts SQL para crear tablas
TABLAS_SQL = {
    'TrackingOrdenes': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'TrackingOrdenes')
        BEGIN
            CREATE TABLE TrackingOrdenes (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                FolioOC INT UNIQUE NOT NULL,
                EstadoGeneral NVARCHAR(50) DEFAULT 'PENDIENTE_EN_SOFTLAND',
                FechaRecepcionBodega DATETIME NULL,
                FechaDespacho DATETIME NULL,
                FechaEntregaCliente DATETIME NULL,
                CreadoPor INT NULL,
                RecibidoPor INT NULL,
                DespachadoPor INT NULL,
                FechaCreacion DATETIME DEFAULT GETDATE(),
                CONSTRAINT CK_EstadoGeneral CHECK (EstadoGeneral IN ('PENDIENTE_EN_SOFTLAND', 'EN_BODEGA', 'DESPACHADO', 'EN_TRANSITO', 'ENTREGADO', 'CANCELADO'))
            );
            CREATE INDEX IX_TrackingOrdenes_FolioOC ON TrackingOrdenes(FolioOC);
            CREATE INDEX IX_TrackingOrdenes_EstadoGeneral ON TrackingOrdenes(EstadoGeneral);
            PRINT 'Tabla TrackingOrdenes creada';
        END
    """,

    'CodigosQR': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'CodigosQR')
        BEGIN
            CREATE TABLE CodigosQR (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                FolioOC INT NOT NULL,
                CodigoQR NVARCHAR(255) UNIQUE NOT NULL,
                FechaCreacion DATETIME DEFAULT GETDATE(),
                FechaExpiracion DATETIME NULL,
                Activo BIT DEFAULT 1,
                Usado BIT DEFAULT 0,
                FechaUsado DATETIME NULL
            );
            CREATE INDEX IX_CodigosQR_CodigoQR ON CodigosQR(CodigoQR);
            CREATE INDEX IX_CodigosQR_FolioOC ON CodigosQR(FolioOC);
            PRINT 'Tabla CodigosQR creada';
        END
    """,

    'EntregasCliente': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'EntregasCliente')
        BEGIN
            CREATE TABLE EntregasCliente (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                FolioOC INT NOT NULL,
                ClienteId INT NULL,
                FechaEntrega DATETIME DEFAULT GETDATE(),
                CodigoQR NVARCHAR(255) NULL,
                FotoEvidencia NVARCHAR(MAX) NULL,
                Geolocalizacion NVARCHAR(MAX) NULL,
                Estado NVARCHAR(50) DEFAULT 'PENDIENTE',
                ConfirmadoPor INT NULL,
                FechaCreacion DATETIME DEFAULT GETDATE()
            );
            CREATE INDEX IX_EntregasCliente_FolioOC ON EntregasCliente(FolioOC);
            CREATE INDEX IX_EntregasCliente_Estado ON EntregasCliente(Estado);
            PRINT 'Tabla EntregasCliente creada';
        END
    """,

    'Despachos': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Despachos')
        BEGIN
            CREATE TABLE Despachos (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                FolioOC INT UNIQUE NOT NULL,
                DespachadoPor INT NULL,
                Transportista NVARCHAR(100) NOT NULL,
                GuiaDespacho NVARCHAR(100) NOT NULL,
                Observaciones NVARCHAR(MAX) NULL,
                FechaDespacho DATETIME DEFAULT GETDATE(),
                FechaCreacion DATETIME DEFAULT GETDATE()
            );
            CREATE INDEX IX_Despachos_FolioOC ON Despachos(FolioOC);
            CREATE INDEX IX_Despachos_GuiaDespacho ON Despachos(GuiaDespacho);
            PRINT 'Tabla Despachos creada';
        END
    """,

    'RecepcionesProducto': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'RecepcionesProducto')
        BEGIN
            CREATE TABLE RecepcionesProducto (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                FolioOC INT NOT NULL,
                ProductoBodegaId INT NULL,
                CantidadRecibida INT NOT NULL,
                RecibidoPor INT NULL,
                TipoRecepcion NVARCHAR(50) DEFAULT 'MANUAL',
                FechaRecepcion DATETIME DEFAULT GETDATE(),
                Observaciones NVARCHAR(MAX) NULL,
                FechaCreacion DATETIME DEFAULT GETDATE()
            );
            CREATE INDEX IX_RecepcionesProducto_FolioOC ON RecepcionesProducto(FolioOC);
            CREATE INDEX IX_RecepcionesProducto_FechaRecepcion ON RecepcionesProducto(FechaRecepcion);
            PRINT 'Tabla RecepcionesProducto creada';
        END
    """,

    'Roles': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Roles')
        BEGIN
            CREATE TABLE Roles (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Nombre NVARCHAR(50) UNIQUE NOT NULL,
                Descripcion NVARCHAR(MAX) NULL,
                FechaCreacion DATETIME DEFAULT GETDATE()
            );
            PRINT 'Tabla Roles creada';
        END
    """,

    'UsuariosSistema': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'UsuariosSistema')
        BEGIN
            CREATE TABLE UsuariosSistema (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                Usuario NVARCHAR(50) UNIQUE NOT NULL,
                PasswordHash NVARCHAR(255) NOT NULL,
                NombreCompleto NVARCHAR(100) NOT NULL,
                Email NVARCHAR(100) NOT NULL,
                RolId INT NOT NULL,
                Activo BIT DEFAULT 1,
                FechaCreacion DATETIME DEFAULT GETDATE(),
                UltimoLogin DATETIME NULL,
                FechaModificacion DATETIME NULL,
                FOREIGN KEY (RolId) REFERENCES Roles(Id)
            );
            CREATE INDEX IX_UsuariosSistema_Usuario ON UsuariosSistema(Usuario);
            CREATE INDEX IX_UsuariosSistema_RolId ON UsuariosSistema(RolId);
            PRINT 'Tabla UsuariosSistema creada';
        END
    """,

    'ProductosBodega': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'ProductosBodega')
        BEGIN
            CREATE TABLE ProductosBodega (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                SoftlandProducto NVARCHAR(100) NOT NULL,
                Descripcion NVARCHAR(MAX) NULL,
                StockActual INT DEFAULT 0,
                StockMinimo INT DEFAULT 10,
                Ubicacion NVARCHAR(100) NULL,
                Activo BIT DEFAULT 1,
                FechaCreacion DATETIME DEFAULT GETDATE()
            );
            CREATE INDEX IX_ProductosBodega_SoftlandProducto ON ProductosBodega(SoftlandProducto);
            PRINT 'Tabla ProductosBodega creada';
        END
    """,

    'Clientes': """
        IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Clientes')
        BEGIN
            CREATE TABLE Clientes (
                Id INT IDENTITY(1,1) PRIMARY KEY,
                UsuarioId INT NULL,
                NombreEmpresa NVARCHAR(100) NOT NULL,
                RUT NVARCHAR(20) NULL,
                Telefono NVARCHAR(20) NULL,
                Direccion NVARCHAR(MAX) NULL,
                Activo BIT DEFAULT 1,
                FechaCreacion DATETIME DEFAULT GETDATE()
            );
            CREATE INDEX IX_Clientes_UsuarioId ON Clientes(UsuarioId);
            PRINT 'Tabla Clientes creada';
        END
    """
}

# Vista para combinar datos
VISTA_SQL = """
    IF EXISTS (SELECT * FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_NAME = 'vw_OrdenesConTracking')
        DROP VIEW vw_OrdenesConTracking;

    GO

    CREATE VIEW vw_OrdenesConTracking AS
    SELECT
        C.Folio,
        C.FechaEmision,
        P.NomProv as Proveedor,
        C.MontoTotal,
        'SOFTLAND' as EstadoSoftland,
        COALESCE(T.EstadoGeneral, 'PENDIENTE_EN_SOFTLAND') as EstadoTracking,
        T.FechaRecepcionBodega,
        T.FechaDespacho,
        T.FechaEntregaCliente,
        (SELECT COUNT(*) FROM RecepcionesProducto WHERE FolioOC = C.Folio) as ProductosRecibidos,
        (SELECT COUNT(*) FROM Despachos WHERE FolioOC = C.Folio) as DespachosRealizados,
        C.Folio as ClienteId
    FROM cwCabeceraOC C
    LEFT JOIN cwProveedores P ON C.CodProv = P.CodProv
    LEFT JOIN TrackingOrdenes T ON C.Folio = T.FolioOC;
"""


def crear_tablas():
    """Crea todas las tablas necesarias"""
    try:
        conn = pyodbc.connect(CONN_STR, timeout=10)
        cursor = conn.cursor()

        logger.info("Iniciando creación de estructura de base de datos...")

        # Crear tablas
        for nombre_tabla, sql in TABLAS_SQL.items():
            try:
                cursor.execute(sql)
                conn.commit()
                logger.info(f"✓ {nombre_tabla}")
            except Exception as e:
                logger.error(f"✗ {nombre_tabla}: {str(e)}")

        # Crear vista
        try:
            cursor.execute(VISTA_SQL)
            conn.commit()
            logger.info("✓ Vista vw_OrdenesConTracking")
        except Exception as e:
            logger.error(f"✗ Vista: {str(e)}")

        cursor.close()
        conn.close()

        logger.info("✅ Estructura de base de datos lista")

    except pyodbc.Error as e:
        logger.error(f"Error de conexión: {str(e)}")
        return False

    return True


def verificar_tablas():
    """Verifica que todas las tablas existan"""
    try:
        conn = pyodbc.connect(CONN_STR, timeout=10)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = 'dbo'
            AND TABLE_NAME IN ('TrackingOrdenes', 'CodigosQR', 'EntregasCliente',
                               'Despachos', 'RecepcionesProducto', 'ProductosBodega', 'Clientes')
        """)

        tablas_existentes = {row[0] for row in cursor.fetchall()}
        tablas_requeridas = set(TABLAS_SQL.keys())

        if tablas_requeridas.issubset(tablas_existentes):
            logger.info(f"✅ Todas las {len(tablas_requeridas)} tablas están presentes")
            return True
        else:
            faltantes = tablas_requeridas - tablas_existentes
            logger.warning(f"❌ Tablas faltantes: {faltantes}")
            return False

    except Exception as e:
        logger.error(f"Error verificando tablas: {str(e)}")
        return False


if __name__ == '__main__':
    import sys

    # Verificar primero
    if verificar_tablas():
        logger.info("No se necesitan cambios")
        sys.exit(0)

    # Crear si es necesario
    if crear_tablas():
        logger.info("✨ Base de datos configurada exitosamente")
        sys.exit(0)
    else:
        logger.error("❌ Error configurando base de datos")
        sys.exit(1)
