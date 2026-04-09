# 🚀 Guía de Primeros Pasos

## 1️⃣ Pre-requisitos

- [x] Python 3.8 o superior
- [x] SQL Server con ODBC Driver 17
- [x] Git (opcional)

### Verificar instalaciones

```bash
# Python
python --version

# ODBC Driver
# Windows: Ir a Panel de Control > Programas > ODBC Data Sources
# O instalar desde: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
```

---

## 2️⃣ Configuración Inicial (5 minutos)

### Paso 1: Crear entorno virtual

```bash
cd "testing 2"
python -m venv venv

# Activar
venv\Scripts\activate  # Windows
# o
source venv/bin/activate  # Linux/Mac
```

### Paso 2: Instalar dependencias

```bash
pip install -r requirements.txt
```

### Paso 3: Configurar variables de entorno

```bash
# Copiar archivo de ejemplo
copy .env.example .env

# Editar .env con tus valores (abrir en VS Code o editor)
# Campos importantes:
# - DB_SERVER: Tu servidor SQL Server
# - DB_NAME: Nombre de la base de datos
# - SECRET_KEY: Generar una clave segura
```

**Generar SECRET_KEY seguro:**
```bash
python -c "import os; print(os.urandom(32).hex())"
```

Copiar el resultado y pegar en `.env`:
```
SECRET_KEY=<el resultado anterior>
```

### Paso 4: Preparar base de datos

```bash
# Crear tablas necesarias
python db_setup.py

# Output esperado:
# ✓ TrackingOrdenes
# ✓ CodigosQR
# ... et.c
```

### Paso 5: Crear usuarios de prueba

```bash
python create_demo_user.py

# Output esperado:
# ✓ Usuario 'admin' creado
# ✓ Usuario 'bodega' creado
# ✓ Usuario 'cliente' creado
```

**Credenciales for testing:**
```
Admin:  admin / Admin123!
Bodega: bodega / Bodega123!
Cliente: cliente / Cliente123!
```

---

## 3️⃣ Ejecutar la Aplicación

### Opción A: Desarrollo (con debug)

```bash
# En terminal con venv activado
python app.py

# Acceder en: http://localhost:5000
```

### Opción B: Producción (recomendado)

```bash
pip install gunicorn

gunicorn -w 4 -b 0.0.0.0:5000 --timeout 120 app:app
```

---

## ✅ Verificar que funciona

1. **Abrir navegador:** http://localhost:5000

2. **Login:** Usar credenciales de prueba

3. **Ver dashboard:** Debe mostrar órdenes (si existen en Softland)

4. **Revisar logs:** 
   ```bash
   tail -f app.log  # Ver logs en tiempo real
   ```

---

## 🧪 Ejecutar tests

```bash
pip install pytest

pytest test_app.py -v
```

---

## 📁 Estructura de archivos

```
testing 2/
├── app.py                 # Aplicación principal (MEJORADA)
├── requirements.txt       # Dependencias
├── .env.example          # Plantilla de configuración
├── db_setup.py           # Script para crear base de datos
├── create_demo_user.py   # Script para usuarios de prueba
├── test_app.py           # Tests unitarios
├── MEJORAS.md            # Documentación de mejoras
├── PRIMEROS_PASOS.md     # Este archivo
├── app.log               # Logs (se genera automáticamente)
├── venv/                 # Entorno virtual
├── templates/            # HTML
│   ├── login.html
│   ├── index.html
│   ├── recepcion_bodega.html
│   ├── despacho_bodega.html
│   ├── mis_entregas.html
│   ├── recibir_producto.html
│   ├── admin_tracking.html
│   ├── admin_reportes.html
│   └── error.html        # Nuevo
└── static/               # Archivos estáticos
    ├── css/
    ├── js/
    └── uploads/          # Fotos de entregas
```

---

## 🔧 Troubleshooting

### Error: "No module named 'pyodbc'"
```bash
pip install pyodbc
```

### Error: "ODBC Driver 17 not found"
- Descargar desde: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
- Reiniciar computadora después de instalar

### Error: "Connection timeout"
- Verificar que SQL Server está ejecutándose
- Verificar nombre de servidor en `.env`
- Probar conexión con SQL Server Management Studio

### Aplicación lenta
- Revisar `app.log`
- Agregar índices en base de datos (ver MEJORAS.md)
- Aumentar `WORKERS` en gunicorn: `-w 8`

### "File too large"
- Máximo: 16MB
- Cambiar `MAX_CONTENT_LENGTH` en `app.py` línea 37

---

## 📊 Flujo de uso típico

### Para Bodega:
1. Login como `bodega`
2. Ver órdenes pendientes
3. Recibir productos
4. Registrar despacho

### Para Cliente:
1. Login como `cliente`
2. Ver entregas pendientes
3. Confirmar recepción con QR/foto
4. Sistema genera comprobante

### Para Admin:
1. Login como `admin`
2. Ver tracking completo
3. Generar reportes
4. Revisar estadísticas

---

## 📝 Próximos pasos recomendados

1. **Revisar MEJORAS.md** - Entiende todas las mejoras
2. **Adaptar templates** - Personalizar HTML según marca
3. **Configurar HTTPS** - Cambiar `SESSION_COOKIE_SECURE=True` en prod
4. **Setup CI/CD** - Automatizar deployment
5. **Monitoreo** - Revisar `app.log` regularmente

---

## ❓ Dudas frecuentes

**P: ¿Cómo cambio el logo?**
R: Editar en `templates/` (base.html o donde esté)

**P: ¿Cómo agrego más usuarios?**
R: Con SQL Manager:
```sql
-- Insertar usuario
INSERT INTO UsuariosSistema 
(Usuario, PasswordHash, NombreCompleto, Email, RolId, Activo)
VALUES (
  'nuevo_usuario',
  'hash_aqui', -- Usar bcrypt hash
  'Nombre Completo',
  'email@example.com',
  3, -- ID del rol
  1
)
```

**P: ¿Cómo backup la base de datos?**
R: SQL Server > Management Studio > Right-click BD > Tasks > Backup

---

## 📞 Soporte

En caso de errores:
1. Revisar `app.log`
2. Buscar error en Google
3. Revisar MEJORAS.md sección "Troubleshooting"

---

**¡Listo! 🎉 La aplicación está funcionando. ¡A usar!**
