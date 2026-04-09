CREATE SCHEMA softland;
GO

-- Diccionarios
CREATE TABLE softland.EC_VsnpTraeAuxiliaresLogCwtauxi (
    CodAux NVARCHAR(20) NOT NULL,
    NomAux NVARCHAR(200) NULL
);

CREATE TABLE softland.IW_vsnpProductos (
    CodProd NVARCHAR(50) NOT NULL,
    DesProd NVARCHAR(255) NULL,
    DesUMed NVARCHAR(20) NULL
);

-- Flujo de Tracking
CREATE TABLE softland.Dw_VsnpRequerimientosMateriasPrimas (
    Orden INT NOT NULL,
    Solicitante NVARCHAR(100) NULL,
    FechaIni DATETIME NULL,
    Cantidad DECIMAL(18,4) NULL
);

CREATE TABLE softland.OW_vsnpTraeEncabezadoOCompra (
    NumOc INT NOT NULL PRIMARY KEY,
    Fecha DATETIME NULL,
    CentroCosto NVARCHAR(50) NULL
);

CREATE TABLE softland.ow_vsnpMovimIWDetalleOC (
    numoc INT NOT NULL,
    codprod NVARCHAR(50) NOT NULL
);

CREATE TABLE softland.NW_OW_VsnpSaldoDetalleOC (
    numoc INT NOT NULL,
    codprod NVARCHAR(50) NOT NULL,
    cantidadOC DECIMAL(18,4) NULL,
    ingresada DECIMAL(18,4) NULL,
    saldo DECIMAL(18,4) NULL,
    Codaux NVARCHAR(20) NULL
);

CREATE TABLE softland.IW_vsnpGuiasEntradaxOC (
    DesBode NVARCHAR(100) NULL,
    Orden INT NOT NULL
);

-- Capa local de despacho (Tabla nueva e independiente de Softland)
CREATE TABLE DespachosTracking (
    Id INT IDENTITY(1,1) PRIMARY KEY,
    NumOc INT NOT NULL,
    Estado NVARCHAR(50) DEFAULT 'En Ruta', -- Estados: 'En Ruta', 'Entregado'
    FechaHoraSalida DATETIME DEFAULT GETDATE(),
    FechaHoraEntrega DATETIME NULL,
    UrlFotoEvidencia NVARCHAR(MAX) NULL,
    CodigoQR NVARCHAR(MAX) NULL,
    RegistradoPor INT NULL,
    Transportista NVARCHAR(100) NULL,
    GuiaDespacho NVARCHAR(50) NULL,
    Observaciones NVARCHAR(MAX) NULL
);
GO
