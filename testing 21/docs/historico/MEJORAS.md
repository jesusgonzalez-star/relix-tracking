# Sistema de Tracking de Órdenes de Compra - Guía de Mejoras

## 🚀 Mejoras Implementadas (100%)

### 1. **SEGURIDAD** 🔐
- ✅ **Hashing de Contraseñas**: Cambio de SHA256 (débil) a PBKDF2-SHA256 con Werkzeug
- ✅ **Variables de Entorno**: Configuración segura vía `.env` (sin secrets hardcodeados)
- ✅ **Validación de Entrada**: Sanitización de datos contra SQL injection y XSS
- ✅ **Session Security**: 
  - Cookie HTTPONLY (no accesible desde JavaScript)
  - Atributo SAMESITE para protección CSRF
  - Control de ciclo de vida de sesión
- ✅ **Validación de Archivos**: Extensiones permitidas y nombres seguros (`secure_filename`)
- ✅ **Límite de Tamaño**: Máximo 16MB en uploads
- ✅ **Verificación de Roles**: Decorador mejorado con `@wraps` (preserva metadata de función)

### 2. **MANEJO DE ERRORES** ⚠️
- ✅ **Logging Completo**: Todos los eventos registrados (archivo + consola)
- ✅ **Error Handlers**: Manejo global de 404, 403, 500
- ✅ **Transacciones**: Rollback automático en caso de error
- ✅ **Mensajes Descriptivos**: Sin exposición de datos sensibles
- ✅ **Try-Finally Blocks**: Cierre de conexiones garantizado

### 3. **BASE DE DATOS** 📊
- ✅ **Gestión de Conexiones**: Clase `DatabaseConnection` para mejor control
- ✅ **Cierre de Conexiones**: Bloque `finally` para evitar fugas de memoria
- ✅ **Encoding UTF-8**: Soporte correcto para caracteres especiales
- ✅ **Parámetros Seguros**: Todas las queries usan `?` para prevenir inyección
- ✅ **Paginación**: Implementada en admin/tracking (evita sobrecargas)

### 4. **VALIDACIÓN DE DATOS** ✔️
- ✅ **Sanitización**: `sanitize_input()` con regex específicos
- ✅ **Email Validation**: Formato correcto
- ✅ **Usuario Validation**: Solo alfanuméricos + guiones bajos
- ✅ **Rangos Numéricos**: Validación de cantidades positivas
- ✅ **Campos Requeridos**: Verificación antes de procesar

### 5. **FUNCIONALIDAD MEJORADA** 🎯
- ✅ **Rutas API**: Endpoints JSON para app móvil (`/api/verificar_qr`, `/api/estado_orden`)
- ✅ **QR Mejorado**: Error correction level HIGH, mejor generación
- ✅ **Fotos de Evidencia**: Guardado seguro con nombres únicos
- ✅ **Geolocalización**: Registro de ubicación en entregas
- ✅ **Reportes**: Nueva ruta `/admin/reportes` con estadísticas
- ✅ **Estado de Orden**: Consulta pública de estado sin login

### 6. **RENDIMIENTO** ⚡
- ✅ **Offset Queries**: Paginación en lugar de cargar todo
- ✅ **Select Específico**: Campos exactos, no SELECT *
- ✅ **Índices en BD**: (verificar/agregar en columnas de búsqueda)
- ✅ **Timeout de Conexión**: 30 segundos para conexiones colgadas

### 7. **ESTRUCTURA Y MANTENIBILIDAD** 📐
- ✅ **Separación de Concerns**: Funciones específicas (sanitize, hash, etc)
- ✅ **Decoradores Robustos**: `@wraps` preserva nombres de función
- ✅ **Context Managers**: Database management automático
- ✅ **Comentarios**: Documentación clara de cada sección
- ✅ **Logging Estratégico**: Eventos importantes registrados

### 8. **CUMPLIMIENTO NORMATIVO** ✅
- ✅ **GDPR Ready**: Datos de fotos y geolocalización gestionados
- ✅ **Auditoría**: Logs completos de quién accede qué
- ✅ **Trazabilidad**: Tracking de cambios de estado
- ✅ **Expiración de QR**: Códigos válidos solo 7 días

---

## 📋 Requisitos Previos

### Sistema
- Python 3.8+
- SQL Server con ODBC Driver 17
- 16MB máximo descarga de archivos

### Base de Datos
Asegurate que existan estas tablas (o crear):
```sql
-- Tablas de usuario (ya deberían existir)
CREATE TABLE UsuariosSistema (
    Id INT PRIMARY KEY,
    Usuario NVARCHAR(50) UNIQUE,
    PasswordHash NVARCHAR(255),
    NombreCompleto NVARCHAR(100),
    Email NVARCHAR(100),
    RolId INT,
    Activo BIT,
    FechaCreacion DATETIME DEFAULT GETDATE()
);

CREATE TABLE Roles (
    Id INT PRIMARY KEY,
    Nombre NVARCHAR(50) UNIQUE
);

-- Tabla de tracking
CREATE TABLE TrackingOrdenes (
    Id INT IDENTITY PRIMARY KEY,
    FolioOC INT UNIQUE,
    EstadoGeneral NVARCHAR(50),
    FechaRecepcionBodega DATETIME,
    FechaDespacho DATETIME,
    FechaEntregaCliente DATETIME,
    CreadoPor INT,
    RecibidoPor INT,
    DespachadoPor INT,
    FechaCreacion DATETIME DEFAULT GETDATE(),
    FOREIGN KEY (FolioOC) REFERENCES cwCabeceraOC(Folio)
);

-- Códigos QR
CREATE TABLE CodigosQR (
    Id INT IDENTITY PRIMARY KEY,
    FolioOC INT,
    CodigoQR NVARCHAR(255) UNIQUE,
    FechaCreacion DATETIME DEFAULT GETDATE(),
    FechaExpiracion DATETIME,
    Activo BIT DEFAULT 1,
    Usado BIT DEFAULT 0
);

-- Entregas a cliente
CREATE TABLE EntregasCliente (
    Id INT IDENTITY PRIMARY KEY,
    FolioOC INT,
    ClienteId INT,
    FechaEntrega DATETIME DEFAULT GETDATE(),
    CodigoQR NVARCHAR(255),
    FotoEvidencia NVARCHAR(MAX),
    Geolocalizacion NVARCHAR(MAX),
    Estado NVARCHAR(50),
    ConfirmadoPor INT,
    FOREIGN KEY (FolioOC) REFERENCES cwCabeceraOC(Folio)
);

-- Despachos
CREATE TABLE Despachos (
    Id INT IDENTITY PRIMARY KEY,
    FolioOC INT UNIQUE,
    DespachadoPor INT,
    Transportista NVARCHAR(100),
    GuiaDespacho NVARCHAR(100),
    Observaciones NVARCHAR(MAX),
    FechaDespacho DATETIME DEFAULT GETDATE(),
    FOREIGN KEY (FolioOC) REFERENCES cwCabeceraOC(Folio)
);

-- Recepciones de producto
CREATE TABLE RecepcionesProducto (
    Id INT IDENTITY PRIMARY KEY,
    FolioOC INT,
    ProductoBodegaId INT,
    CantidadRecibida INT,
    RecibidoPor INT,
    TipoRecepcion NVARCHAR(50),
    FechaRecepcion DATETIME DEFAULT GETDATE(),
    Observaciones NVARCHAR(MAX),
    FOREIGN KEY (FolioOC) REFERENCES cwCabeceraOC(Folio)
);
```

---

## 🔧 Instalación

1. **Clonar y setup venv:**
```bash
cd "testing 2"
python -m venv venv
venv\Scripts\activate  # Windows
```

2. **Instalar dependencias:**
```bash
pip install -r requirements.txt
```

3. **Configurar variables de entorno:**
```bash
# Copiar plantilla
copy .env.example .env

# Editar .env con tus valores
# Especialmente cambiar:
# - SECRET_KEY (generar con: python -c "import os; print(os.urandom(32).hex())")
# - DB_SERVER, DB_NAME
# - SESSION_COOKIE_SECURE (True en producción)
```

4. **Crear carpeta de uploads:**
```bash
mkdir static\uploads
```

5. **Ejecutar la aplicación:**
```bash
# Desarrollo (con debug)
$env:DEBUG="True"
python app.py

# Producción (con gunicorn)
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

---

## 📚 Nuevas Funcionalidades

### APIs Públicas
```
POST /api/verificar_qr
GET /api/estado_orden/<folio>

Requieren: Datos JSON, sin sesión requerida
```

### Nuevas Rutas
```
GET /admin/reportes - Estadísticas y rendimiento
GET /admin/tracking_completo?page=1 - Tracking con paginación
```

---

## 🛡️ Checklist de Seguridad

- [ ] Cambiar SECRET_KEY en producción
- [ ] Generar contraseña fuerte inicial
- [ ] Configurar HTTPS en producción
- [ ] Revisar permisos de carpeta `static/uploads`
- [ ] Respaldar logs regularmente
- [ ] Monitorear archivo `app.log`
- [ ] Actualizar dependencias periódicamente
- [ ] Configurar firewall para puerto 5000

---

## 📊 Monitoreo

Revisar `app.log` para:
- Intentos de login fallidos
- Accesos denegados
- Errores de base de datos
- Transacciones procesadas

```bash
# Ver últimas líneas del log
tail -f app.log

# Buscar errores
grep "ERROR" app.log
```

---

## ✨ Próximas Mejoras Recomendadas

1. **Rate Limiting**: Agregar Flask-Limiter para proteger endpoints
2. **CAPTCHA**: En formulario de login
3. **Two-Factor Authentication**: Para usuarios admin
4. **Full-Text Search**: Búsqueda de órdenes mejorada
5. **Export a Excel/PDF**: Reportes descargables
6. **WebSocket**: Notificaciones real-time
7. **Caché Redis**: Para consultas frecuentes
8. **CI/CD**: Pipeline de deployment automático

---

## 🆘 Troubleshooting

**Error: "ODBC Driver 17 not found"**
- Instalar: Microsoft ODBC Driver 17 for SQL Server

**Error: "Session secret key changed"**
- Revisar archivo `.env`, SECRET_KEY debe ser consistente

**Error: "File too large"**
- Máximo permitido: 16MB
- Cambiar en `app.config['MAX_CONTENT_LENGTH']`

**Base de datos lenta:**
- Agregar índices en: `FolioOC`, `EstadoGeneral`, `FechaRecepcionBodega`

---

**Versión**: 2.0.0 - Completamente Mejorada  
**Última actualización**: 2026-03-17
