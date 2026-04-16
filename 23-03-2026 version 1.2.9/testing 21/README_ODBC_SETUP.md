# 🗂️ Índice: Configuración ODBC Driver 18

Todos los archivos necesarios para desplegar la aplicación Flask en Linux con SQL Server y ODBC Driver 18.

---

## 📖 Documentación

### Para Desarrolladores
- **[IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)** ⭐ Lee esto primero
  - Resumen de cambios realizados
  - Tareas completadas
  - Testing y validación

### Para Operaciones (DevOps/SRE)
- **[QUICKSTART_LINUX_DEPLOY.md](QUICKSTART_LINUX_DEPLOY.md)** 🚀 Guía paso a paso
  - 1. Instalar ODBC Driver 18
  - 2. Configurar variables de entorno
  - 3. Validar configuración
  - 4. Desplegar con Gunicorn
  - 5. Configurar Systemd
  - 6. Setup Nginx

### Para Arquitectos/Consultores
- **[DEPLOYMENT_ODBC_DRIVER18.md](DEPLOYMENT_ODBC_DRIVER18.md)** 📋 Referencia técnica detallada
  - Variables de entorno completas
  - Ejemplo `.env` para producción
  - Explicación de parámetros de seguridad
  - Troubleshooting de errores
  - Arquitectura de conexiones

### Técnico (Para Ingenieros)
- **[CHANGES_SUMMARY.md](CHANGES_SUMMARY.md)** 🔧 Detalles de implementación
  - Cambios en config.py
  - Cambios en app.py
  - Archivos nuevos
  - Flujo de configuración
  - Testing recomendado

---

## 🔍 Por Tarea

### Necesito... Configurar la aplicación para Linux

1. Leer: [QUICKSTART_LINUX_DEPLOY.md](QUICKSTART_LINUX_DEPLOY.md)
2. Ejecutar: `python validate_db_config.py`
3. Editar: `.env` (crear basado en template)
4. Desplegar

### Necesito... Entender qué cambió

1. Leer: [IMPLEMENTATION_REPORT.md](IMPLEMENTATION_REPORT.md)
2. Consultar: [CHANGES_SUMMARY.md](CHANGES_SUMMARY.md)
3. Revisar: `config.py` (líneas 105-240)
4. Revisar: `app.py` (líneas 70-74, 113-122)

### Necesito... Configurar las variables de entorno

1. Consultar: [DEPLOYMENT_ODBC_DRIVER18.md](DEPLOYMENT_ODBC_DRIVER18.md) (Variables de Entorno)
2. Crear: `.env` basado en template
3. Validar: `python validate_db_config.py`

### Necesito... Solucionar un error de conexión

1. Ejecutar: `python validate_db_config.py`
2. Consultar: [DEPLOYMENT_ODBC_DRIVER18.md](DEPLOYMENT_ODBC_DRIVER18.md) (Troubleshooting)
3. Revisar: logs de aplicación

### Necesito... Desplegar en producción

1. Seguir: [QUICKSTART_LINUX_DEPLOY.md](QUICKSTART_LINUX_DEPLOY.md) (paso a paso)
2. Usar: [DEPLOYMENT_ODBC_DRIVER18.md](DEPLOYMENT_ODBC_DRIVER18.md) (como referencia)
3. Validar: `python validate_db_config.py` (antes de desplegar)

---

## ⚙️ Scripts Disponibles

### `validate_db_config.py`
Script de validación pre-despliegue.

```bash
python validate_db_config.py
```

**Qué valida**:
- Variables de entorno (LOCAL_DB_*, DB_*, etc.)
- Valores permitidos de parámetros de seguridad
- Disponibilidad de pyodbc
- Disponibilidad de ODBC drivers

**Salida**:
- ✓ OK
- ⚠ Warnings (revisar pero podrían no ser bloqueantes)
- ❌ Errores críticos (deben corregirse)

---

## 📝 Variables de Entorno Resumen

### Base de Datos Local

```env
LOCAL_SERVER=servidor\SQLEXPRESS
LOCAL_DB_NAME=base_de_datos
LOCAL_DB_USER=usuario_sql
LOCAL_DB_PASS=contraseña
LOCAL_DB_DRIVER=ODBC Driver 18 for SQL Server
LOCAL_DB_ENCRYPT=no
LOCAL_DB_TRUST_CERT=yes
```

### ERP Softland

```env
DB_SERVER=servidor\SOFTLAND
DB_NAME=base_erp
DB_USER=usuario_erp
DB_PASS=contraseña_erp
DB_DRIVER=ODBC Driver 18 for SQL Server
SOFTLAND_ENCRYPT=no
SOFTLAND_TRUST_CERT=yes
```

### Flask

```env
DEBUG=False
SECRET_KEY=clave-secreta-segura
API_SECRET=api-secret-segura
```

---

## 🆘 Errores Comunes

| Error | Solución |
|-------|----------|
| `SSL Provider: certificate verify failed` | `LOCAL_DB_TRUST_CERT=yes` |
| `Login timeout expired` | Verificar usuario/contraseña/firewall |
| `ODBC Driver 18 not found` | `sudo apt-get install msodbcsql18` |
| `Encrypt parameter must be...` | Usar solo: yes, no, optional, mandatory |

**Más troubleshooting**: Ver [DEPLOYMENT_ODBC_DRIVER18.md](DEPLOYMENT_ODBC_DRIVER18.md#troubleshooting)

---

## 📊 Archivos Modificados

```
config.py          ✏️ Modificado
  - Nueva función obfuscate_password_in_uri()
  - Mejoras en get_connection_string()
  - Mejoras en build_sqlalchemy_uri()
  - Mejoras en get_pyodbc_connection_string()

app.py             ✏️ Modificado
  - Import de obfuscate_password_in_uri
  - Log de URI SQLAlchemy (ofuscada)
  - Log de cadena pyodbc (ofuscada)
```

---

## 📁 Archivos Nuevos

```
IMPLEMENTATION_REPORT.md       📋 Reporte de implementación
DEPLOYMENT_ODBC_DRIVER18.md    📚 Guía detallada de despliegue
QUICKSTART_LINUX_DEPLOY.md     🚀 Guía rápida paso a paso
CHANGES_SUMMARY.md             🔧 Resumen técnico de cambios
validate_db_config.py          ✅ Script de validación
README_ODBC_SETUP.md          📖 Este archivo (índice)
```

---

## ⏱️ Tiempo Estimado

| Tarea | Tiempo |
|-------|--------|
| Instalar ODBC Driver 18 | 10 min |
| Configurar variables de entorno | 5 min |
| Validar con script | 2 min |
| Desplegar con Gunicorn | 10 min |
| Verificación post-despliegue | 10 min |
| **Total** | **~40 min** |

---

## ✅ Checklist de Despliegue

- [ ] ODBC Driver 18 instalado en servidor Linux
- [ ] Virtualenv Python creado y activado
- [ ] Dependencias instaladas (`pip install -r requirements.txt`)
- [ ] Variables de entorno configuradas en `.env`
- [ ] Validación pasada: `python validate_db_config.py`
- [ ] Conexión SQL verificada (sqlcmd test)
- [ ] Endpoint `/health` respondiendo
- [ ] Logs sin errores de conexión
- [ ] Systemd service configurado (opcional pero recomendado)
- [ ] Nginx reverse proxy configurado (opcional)
- [ ] SSL/TLS implementado (recomendado para producción)

---

## 🔗 Links Útiles

### Documentación Oficial
- [ODBC Driver 18 Download](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)
- [SQLAlchemy MSSQL Dialects](https://docs.sqlalchemy.org/en/20/dialects/mssql.html)
- [pyodbc GitHub](https://github.com/mkleehammer/pyodbc/wiki/Connection-strings)

### En Este Proyecto
- Lógica de configuración: [config.py](config.py)
- Punto de entrada: [app.py](app.py)
- Validador: [validate_db_config.py](validate_db_config.py)

---

## 📞 Soporte

### Si la aplicación no arranca
1. Ejecutar: `python validate_db_config.py`
2. Revisar errores críticos (❌)
3. Consultar: [Troubleshooting en DEPLOYMENT_ODBC_DRIVER18.md](DEPLOYMENT_ODBC_DRIVER18.md#troubleshooting)

### Si hay errores de conexión
1. Revisar logs: `sudo journalctl -u flask-tracking -f`
2. Probar conexión SQL: `sqlcmd -S servidor -U usuario -P contraseña`
3. Verificar firewall: `sudo ufw allow 1433/tcp`

### Si hay duda sobre configuración
1. Revisar [QUICKSTART_LINUX_DEPLOY.md](QUICKSTART_LINUX_DEPLOY.md)
2. Consultar [DEPLOYMENT_ODBC_DRIVER18.md](DEPLOYMENT_ODBC_DRIVER18.md)
3. Ver ejemplos en archivos de documentación

---

## 🎓 Recomendación de Lectura

**Para empezar**:
```
1. IMPLEMENTATION_REPORT.md (2 min) - Entender qué se hizo
2. QUICKSTART_LINUX_DEPLOY.md (15 min) - Seguir paso a paso
3. validate_db_config.py (1 min) - Ejecutar validador
4. Desplegar 🚀
```

**Para referencia**:
- DEPLOYMENT_ODBC_DRIVER18.md - Consultar según necesidad
- CHANGES_SUMMARY.md - Para detalles técnicos
- config.py - Para lógica de configuración

---

## 📜 Versionado

| Versión | Fecha | Cambios |
|---------|-------|---------|
| 1.0 | 2026-04-16 | Release inicial |

---

**Última actualización**: 2026-04-16  
**Aplicación**: Flask Tracking Logístico  
**Entorno**: Linux (Ubuntu) + SQL Server + ODBC Driver 18  
**Status**: ✅ Listo para producción
