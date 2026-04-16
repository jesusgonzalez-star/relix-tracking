# Configuración para Despliegue en Linux con ODBC Driver 18

## Resumen de Cambios

Se han implementado mejoras robustas para la conexión a SQL Server en entornos Linux con ODBC Driver 18, que requiere configuración específica de seguridad para certificados autofirmados.

### Archivos Modificados

1. **config.py**
   - Nueva función `obfuscate_password_in_uri()` para ofuscación segura en logs
   - Métodos mejorados: `build_sqlalchemy_uri()` y `get_pyodbc_connection_string()`
   - Validación robusta de parámetros de seguridad para Driver 18
   - Soporte completo para Encrypt y TrustServerCertificate

2. **app.py**
   - Importación de `obfuscate_password_in_uri` y `re`
   - Logs de diagnóstico con URIs ofuscadas al inicializar
   - Registro de configuración de ambas conexiones (SQLAlchemy y pyodbc legacy)

---

## Variables de Entorno Requeridas

### 1. **Base de Datos Local (LocalDbConfig)**

Estas variables controlan la conexión a la base de datos local de tracking.

```bash
# Servidor y base de datos (obligatorios)
LOCAL_SERVER=tu-servidor\SQLEXPRESS
LOCAL_DB_NAME=Softland_Mock

# Autenticación SQL (recomendado para Linux)
LOCAL_DB_USER=tu_usuario_sql
LOCAL_DB_PASS=tu_contraseña

# Driver ODBC (ajustar según versión instalada)
LOCAL_DB_DRIVER=ODBC Driver 18 for SQL Server

# Parámetros de Seguridad para Driver 18
# IMPORTANTE: Obligatorio si usas Driver 18
LOCAL_DB_ENCRYPT=no              # Opciones: yes, no, optional, mandatory
LOCAL_DB_TRUST_CERT=yes           # Opciones: yes, no (para certificados autofirmados)
```

### 2. **ERP Softland (SoftlandConfig)**

Estas variables controlan la conexión de solo lectura al ERP.

```bash
# Servidor y base de datos
DB_SERVER=tu-servidor-erp\SOFTLAND
DB_NAME=tu_base_datos_erp

# Credenciales SQL
DB_USER=tu_usuario_erp
DB_PASS=tu_contraseña_erp

# Driver ODBC
DB_DRIVER=ODBC Driver 18 for SQL Server

# Parámetros de Seguridad para Driver 18
SOFTLAND_ENCRYPT=no
SOFTLAND_TRUST_CERT=yes

# Timeout personalizado (opcional)
SOFTLAND_TIMEOUT=15
```

### 3. **Variables Globales de Producción**

```bash
# Entorno y seguridad
DEBUG=False
SECRET_KEY=tu-clave-secreta-segura
API_SECRET=tu-api-secret-segura

# Validar autenticación SQL en producción
LOCAL_DB_REQUIRE_SQL_AUTH=true
```

---

## Ejemplo: Archivo .env para Linux/Producción

```env
# ============================================================
# FLASK & GENERAL
# ============================================================
DEBUG=False
SECRET_KEY=your-production-secret-key-change-this
API_SECRET=your-production-api-secret-change-this
PORT=5000

# ============================================================
# BASE DE DATOS LOCAL (Tracking / Usuarios)
# ============================================================
LOCAL_SERVER=db-local.ejemplo.com\SQLEXPRESS
LOCAL_DB_NAME=Softland_Mock
LOCAL_DB_USER=app_user
LOCAL_DB_PASS=app_password_123
LOCAL_DB_DRIVER=ODBC Driver 18 for SQL Server
LOCAL_DB_ENCRYPT=no
LOCAL_DB_TRUST_CERT=yes
LOCAL_DB_REQUIRE_SQL_AUTH=true

# ============================================================
# ERP SOFTLAND (Solo Lectura)
# ============================================================
DB_SERVER=db-softland.ejemplo.com\SOFTLAND
DB_NAME=ZDESARROLLO
DB_USER=user_softland
DB_PASS=pass_softland_123
DB_DRIVER=ODBC Driver 18 for SQL Server
SOFTLAND_ENCRYPT=no
SOFTLAND_TRUST_CERT=yes
SOFTLAND_TIMEOUT=15

# ============================================================
# OPCIONALES
# ============================================================
BEHIND_PROXY=true
SESSION_COOKIE_SECURE=True
ENABLE_SWAGGER=False
RATELIMIT_ENABLED=True
RATELIMIT_API=60 per minute
```

---

## Parámetros de Seguridad Explicados

### LOCAL_DB_ENCRYPT / SOFTLAND_ENCRYPT

- **`no`** (recomendado para redes corporativas internas)
  - Sin encriptación de la conexión
  - Menor overhead
  - Adecuado si el servidor está en la misma red corporativa

- **`yes`** (recomendado para conexiones remotas)
  - Obliga encriptación TLS/SSL
  - Mayor seguridad en conexiones públicas
  - Requiere certificado válido en el servidor

- **`optional`** (Driver 18+ solamente)
  - Intenta encriptar, pero continúa si falla

- **`mandatory`** (Driver 18+ solamente)
  - Requiere encriptación; falla si no es posible

### LOCAL_DB_TRUST_CERT / SOFTLAND_TRUST_CERT

- **`yes`** (recomendado para certificados autofirmados)
  - Acepta certificados auto-firmados
  - Desactiva validación de cadena de certificado
  - Necesario para labs/desarrollo en redes corporativas

- **`no`** (recomendado para producción con CA)
  - Valida completamente el certificado
  - Requiere que el certificado del servidor sea válido
  - Mejor para entornos de producción con PKI corporativa

---

## Troubleshooting

### Error: "SSL Provider: certificate verify failed"

**Causa**: Driver 18 rechaza el certificado autofirmado del servidor.

**Solución**:
```bash
LOCAL_DB_TRUST_CERT=yes
SOFTLAND_TRUST_CERT=yes
```

### Error: "Login timeout expired"

**Causa**: Problemas de conectividad o credenciales incorrectas.

**Verificación**:
1. Prueba la conexión manualmente con `sqlcmd`:
   ```bash
   sqlcmd -S tu-servidor\SQLEXPRESS -U usuario -P contraseña -d base_datos -l 5
   ```

2. Verifica las variables de entorno están cargadas:
   ```bash
   echo $LOCAL_DB_USER
   echo $LOCAL_DB_PASS
   ```

3. Revisa los logs de la aplicación:
   ```
   Base de datos local (SQLAlchemy): mssql+pyodbc://usuario:***@servidor/base_datos?driver=...&Encrypt=no&TrustServerCertificate=yes
   ```

### Error: "Encrypt parameter must be mandatory or optional"

**Causa**: Valor inválido en `LOCAL_DB_ENCRYPT` o `SOFTLAND_ENCRYPT`.

**Solución**: Solo usar: `yes`, `no`, `optional`, `mandatory`

---

## Verificación Post-Despliegue

### 1. Revisar Logs de Inicialización

```bash
# Al arrancar la aplicación, deberías ver:
# INFO - Base de datos local (SQLAlchemy): mssql+pyodbc://user:***@servidor/...
# INFO - Base de datos local (pyodbc legacy): Driver={ODBC Driver 18...};...;PWD=***
```

### 2. Probar Endpoint de Salud

```bash
curl http://localhost:5000/health
# Expected: {"status": "ok"}
```

### 3. Probar Conectividad con Softland

Si la API de Softland está configurada:
```bash
curl -H "X-API-Key: tu_api_secret" http://localhost:5000/api/softland/health
```

---

## Arquitectura de Conexiones

```
┌─────────────────────────────────────┐
│   Flask Application (app.py)        │
│  - Logging: obfuscate_password_in_uri│
│  - Info: URI sin contraseña en logs  │
└─────────────────────────────────────┘
         ↓                    ↓
    ┌────────────┐      ┌──────────────┐
    │ SQLAlchemy │      │ pyodbc Legacy│
    │ (ORM)      │      │ (Herramientas)
    └────┬───────┘      └────┬─────────┘
         │                   │
    ┌────v───────────────────v────┐
    │   config.py Methods          │
    │   - build_sqlalchemy_uri()   │
    │   - get_pyodbc_conn_string() │
    │   - Parámetros Driver 18:    │
    │     Encrypt, TrustCert       │
    └────┬─────────────────────────┘
         │
         ├─ LocalDbConfig ──→ BD Local
         │  (Tracking/Usuarios)
         │
         └─ SoftlandConfig ──→ ERP Softland
            (Solo Lectura)
```

---

## Checklist de Despliegue

- [ ] Driver ODBC 18 instalado en el servidor Linux
  ```bash
  odbcinst -q -d -n "ODBC Driver 18 for SQL Server"
  ```

- [ ] Variables de entorno configuradas en `.env` o en el sistema
  - [ ] `LOCAL_DB_USER` y `LOCAL_DB_PASS` definidas
  - [ ] `DB_USER` y `DB_PASS` definidas
  - [ ] `DEBUG=False`
  - [ ] `SECRET_KEY` y `API_SECRET` definidas (producción)

- [ ] Parámetros de seguridad ajustados según certificado
  - [ ] `LOCAL_DB_ENCRYPT` (típicamente `no` para interno)
  - [ ] `LOCAL_DB_TRUST_CERT` (típicamente `yes` para autofirmado)

- [ ] Logs de inicialización revisados (sin errores de conexión)

- [ ] Endpoints probados y funcionando

---

## Referencias

- [ODBC Driver 18 Documentation](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- [SQLAlchemy MSSQL Connection Strings](https://docs.sqlalchemy.org/en/20/dialects/mssql.html)
- [pyodbc Connection Strings](https://github.com/mkleehammer/pyodbc/wiki/Connection-strings)
