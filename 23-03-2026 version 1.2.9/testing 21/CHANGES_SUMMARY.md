# Resumen de Cambios: Configuración ODBC Driver 18 para Linux

## 📋 Descripción

Se han implementado mejoras robustas para la conexión a SQL Server en entornos Linux con ODBC Driver 18, que requiere parámetros específicos de seguridad (`TrustServerCertificate` y `Encrypt`) para aceptar conexiones con certificados autofirmados.

---

## 🔧 Cambios en Archivos Existentes

### 1. **config.py**

#### Adiciones:
- **Importación de `re`**: Para expresiones regulares en validación de URIs
- **Nueva función `obfuscate_password_in_uri()`**: 
  - Ofusca contraseñas en URIs SQLAlchemy para logs seguros
  - Reemplaza `password` con `***` en mensajes de diagnóstico
  - Ejemplo: `mssql+pyodbc://user:***@host/db?...`

#### Mejoras en métodos existentes:

**`SoftlandConfig.get_connection_string()`**:
- Validación robusta de valores para `Encrypt` y `TrustServerCertificate`
- Valores permitidos:
  - **Encrypt**: `yes`, `no`, `optional`, `mandatory`
  - **TrustServerCertificate**: `yes`, `no`, `true`, `false`
- Fallback automático a valores seguros si hay error en configuración
- Mejor documentación del propósito (ApplicationIntent=ReadOnly)

**`LocalDbConfig.build_sqlalchemy_uri()`**:
- Parámetros de seguridad dinámicos para Driver 18
- Soporta servidores con espacios en el nombre
- Codificación URL-safe de todos los parámetros
- Validación de Encrypt y TrustServerCertificate

**`LocalDbConfig.get_pyodbc_connection_string()`**:
- Misma validación que build_sqlalchemy_uri()
- Soporta autenticación SQL y Trusted Connection
- Parámetros de seguridad inyectados automáticamente para Driver 18

---

### 2. **app.py**

#### Adiciones:
- **Importación de `re`** y **`obfuscate_password_in_uri`**
- **Logs de diagnóstico pre-inicialización DB**:
  - Registra URI SQLAlchemy con contraseña ofuscada
  - Registra cadena de conexión pyodbc con contraseña ofuscada
  - Ejecuta en el contexto de la aplicación (app_context)

#### Código agregado:

```python
# ANTES de db.init_app(app)
db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
if db_uri:
    obfuscated_uri = obfuscate_password_in_uri(db_uri)
    app.logger.info(f'Base de datos local (SQLAlchemy): {obfuscated_uri}')

# DENTRO de app_context()
pyodbc_conn_str = LocalDbConfig.get_pyodbc_connection_string()
obfuscated_pyodbc = re.sub(r'PWD=[^;]*', 'PWD=***', pyodbc_conn_str, flags=re.IGNORECASE)
app.logger.info(f'Base de datos local (pyodbc legacy): {obfuscated_pyodbc}')
```

---

## 📁 Archivos Nuevos

### 1. **DEPLOYMENT_ODBC_DRIVER18.md**

Guía completa de despliegue que incluye:
- Variables de entorno requeridas para LocalDbConfig y SoftlandConfig
- Ejemplo completo de archivo `.env` para producción
- Explicación de cada parámetro de seguridad (Encrypt, TrustServerCertificate)
- Troubleshooting de errores comunes
- Checklist de despliegue

**Uso**: Consulta este archivo cuando configures el entorno en Linux/producción.

---

### 2. **validate_db_config.py**

Script de validación que:
- Verifica todas las variables de entorno están configuradas
- Valida parámetros de seguridad (valores permitidos)
- Comprueba disponibilidad de pyodbc y drivers ODBC
- Proporciona retroalimentación clara (✓ OK, ⚠ Warning, ❌ Error)

**Uso**:
```bash
python validate_db_config.py
```

**Output esperado**:
```
✓ LOCAL_SERVER: 5CD5173D14\SQLEXPRESS
✓ LOCAL_DB_NAME: Softland_Mock
✓ LOCAL_DB_USER: app_user
✓ LOCAL_DB_ENCRYPT: no
✓ LOCAL_DB_TRUST_CERT: yes
  → Aceptará certificados autofirmados
✓ pyodbc disponible
✓ ODBC Driver 18 for SQL Server encontrado
```

---

## 🔐 Flujo de Configuración Dinámico

```
┌─ Environment Variables (o .env) ─┐
│  LOCAL_DB_ENCRYPT=no             │
│  LOCAL_DB_TRUST_CERT=yes          │
│  DB_DRIVER=ODBC Driver 18...     │
└──────────────────┬────────────────┘
                   │
         ┌─────────▼─────────┐
         │ config.py Methods │
         │ (Build URI/ConnStr)│
         └────────┬──────────┘
                  │
      ┌───────────┴─────────────┐
      │                         │
  ┌───▼─────────┐        ┌─────▼────────┐
  │ SQLAlchemy  │        │ pyodbc Raw   │
  │ (ORM, API)  │        │ (Legacy, GUI)│
  └─────────────┘        └──────────────┘
```

---

## 🧪 Testing Recomendado

### 1. **Test de Inicialización**
```bash
export DEBUG=False
export LOCAL_DB_USER=tu_usuario
export LOCAL_DB_PASS=tu_password
export LOCAL_DB_ENCRYPT=no
export LOCAL_DB_TRUST_CERT=yes
python -c "from app import create_app; app = create_app()"
# Revisar logs: debe mostrar URIs sin contraseña
```

### 2. **Test de Validación**
```bash
python validate_db_config.py
# Debe pasar todas las validaciones sin errores críticos
```

### 3. **Test de Conectividad SQL Directa**
```bash
# Verificar driver ODBC disponible
odbcinst -q -d -n "ODBC Driver 18 for SQL Server"

# Probar conexión manualmente
sqlcmd -S tu-servidor\\SQLEXPRESS -U usuario -P password -Q "SELECT 1"
```

---

## 📊 Variables de Entorno: Referencia Rápida

| Variable | Config | Requerida | Ejemplo | Notas |
|----------|--------|-----------|---------|-------|
| `LOCAL_SERVER` | LocalDbConfig | ✓ | `5CD5173D14\SQLEXPRESS` | Servidor + Instancia |
| `LOCAL_DB_NAME` | LocalDbConfig | ✓ | `Softland_Mock` | Nombre base de datos |
| `LOCAL_DB_USER` | LocalDbConfig | ✓ (Prod) | `app_user` | Usuario SQL Auth |
| `LOCAL_DB_PASS` | LocalDbConfig | ✓ (Prod) | `mypass123` | Contraseña SQL Auth |
| `LOCAL_DB_DRIVER` | LocalDbConfig | - | `ODBC Driver 18...` | Default: Driver 17 |
| `LOCAL_DB_ENCRYPT` | LocalDbConfig | ✓ (Driver 18) | `no` | yes/no/optional/mandatory |
| `LOCAL_DB_TRUST_CERT` | LocalDbConfig | ✓ (Driver 18) | `yes` | yes/no/true/false |
| `DB_SERVER` | SoftlandConfig | ✓ | `RELIX-SQL01\SOFTLAND` | Servidor Softland |
| `DB_NAME` | SoftlandConfig | ✓ | `ZDESARROLLO` | Base Softland |
| `DB_USER` | SoftlandConfig | ✓ | `JGonzalez` | Usuario Softland |
| `DB_PASS` | SoftlandConfig | ✓ | `softlandpwd` | Contraseña Softland |
| `DB_DRIVER` | SoftlandConfig | - | `ODBC Driver 18...` | Default: Driver 17 |
| `SOFTLAND_ENCRYPT` | SoftlandConfig | ✓ (Driver 18) | `no` | yes/no/optional/mandatory |
| `SOFTLAND_TRUST_CERT` | SoftlandConfig | ✓ (Driver 18) | `yes` | yes/no/true/false |

---

## 🚀 Checklist de Implementación

- [x] Parámetros de seguridad inyectados dinámicamente en URIs
- [x] Variables de entorno para `LOCAL_DB_ENCRYPT` y `LOCAL_DB_TRUST_CERT`
- [x] Variables de entorno para `SOFTLAND_ENCRYPT` y `SOFTLAND_TRUST_CERT`
- [x] Validación robusta de parámetros permitidos
- [x] Logging de diagnóstico con contraseñas ofuscadas
- [x] Soporte para pyodbc raw (DatabaseConnection)
- [x] Documentación completa de despliegue
- [x] Script de validación pre-despliegue
- [x] Soporte para ambas auth methods (SQL Auth + Trusted Connection)

---

## ⚡ Próximos Pasos para Linux/Producción

1. **Instalar ODBC Driver 18**:
   ```bash
   curl https://packages.microsoft.com/keys/microsoft.asc | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc
   sudo add-apt-repository "$(wget -qO- https://packages.microsoft.com/config/ubuntu/22.04/mssql-server.list)"
   sudo apt-get update
   sudo apt-get install msodbcsql18
   ```

2. **Crear archivo `.env`**:
   ```bash
   cp DEPLOYMENT_ODBC_DRIVER18.md .env.example
   # Editar .env.example con valores reales y guardarlo como .env
   ```

3. **Validar configuración**:
   ```bash
   python validate_db_config.py
   ```

4. **Probar arranque**:
   ```bash
   python app.py
   # Revisar logs para URIs ofuscadas
   ```

5. **Desplegar con uWSGI/Gunicorn**:
   ```bash
   gunicorn -w 4 -b 0.0.0.0:5000 app:create_app()
   ```

---

## 📞 Troubleshooting Rápido

| Error | Causa | Solución |
|-------|-------|----------|
| `SSL Provider: certificate verify failed` | Cert autofirmado rechazado | `LOCAL_DB_TRUST_CERT=yes` |
| `Login timeout expired` | Credenciales/conectividad | Verificar usuario/contraseña/firewall |
| `Encrypt parameter must be mandatory or optional` | Valor inválido | Use solo: `yes`, `no`, `optional`, `mandatory` |
| `pyodbc.Error: [unixODBC][Driver Manager]` | Driver ODBC no instalado | Instalar `msodbcsql18` |
| `AttributeError: 'NoneType' object has no attribute 'split'` | Credenciales vacías | Definir `LOCAL_DB_USER` y `LOCAL_DB_PASS` |

---

## 📚 Referencias

- **Documentación oficial ODBC Driver 18**: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
- **SQLAlchemy MSSQL Dialects**: https://docs.sqlalchemy.org/en/20/dialects/mssql.html
- **pyodbc Wiki**: https://github.com/mkleehammer/pyodbc/wiki

---

**Última actualización**: 2026-04-16  
**Versión**: 1.0  
**Aplicación**: Flask Tracking Logístico  
**Entorno**: Linux (Ubuntu) + SQL Server + ODBC Driver 18
