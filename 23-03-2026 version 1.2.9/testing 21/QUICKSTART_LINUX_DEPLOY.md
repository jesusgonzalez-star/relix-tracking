# Quick Start: Despliegue en Linux con ODBC Driver 18

Guía rápida para desplegar la aplicación Flask en un servidor Linux (Ubuntu) con SQL Server y ODBC Driver 18.

---

## 1️⃣ Preparar el Servidor Linux

### Instalar ODBC Driver 18

```bash
# Ubuntu 20.04 / 22.04
curl https://packages.microsoft.com/keys/microsoft.asc | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc
sudo add-apt-repository "$(wget -qO- https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/mssql-server.list)"
sudo apt-get update
sudo apt-get install msodbcsql18 unixodbc-dev python3-dev

# Verificar instalación
odbcinst -q -d -n "ODBC Driver 18 for SQL Server"
# Output esperado: ODBC Driver 18 for SQL Server
```

### Instalar Python y Dependencias

```bash
sudo apt-get install python3.10 python3.10-venv python3.10-dev

# Crear virtualenv
python3.10 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

---

## 2️⃣ Configurar Variables de Entorno

### Opción A: Archivo `.env` (Recomendado)

```bash
# Crear archivo .env en la raíz del proyecto
cat > .env << 'EOF'
# Flask
DEBUG=False
SECRET_KEY=tu-clave-super-segura-aqui
API_SECRET=tu-api-secret-aqui
PORT=5000

# Base de Datos Local (Tracking/Usuarios)
LOCAL_SERVER=tu-servidor-db\SQLEXPRESS
LOCAL_DB_NAME=Softland_Mock
LOCAL_DB_USER=app_user
LOCAL_DB_PASS=tu_password_aqui
LOCAL_DB_DRIVER=ODBC Driver 18 for SQL Server
LOCAL_DB_ENCRYPT=no
LOCAL_DB_TRUST_CERT=yes
LOCAL_DB_REQUIRE_SQL_AUTH=true

# ERP Softland (Solo Lectura)
DB_SERVER=tu-servidor-erp\SOFTLAND
DB_NAME=ZDESARROLLO
DB_USER=usuario_softland
DB_PASS=password_softland
DB_DRIVER=ODBC Driver 18 for SQL Server
SOFTLAND_ENCRYPT=no
SOFTLAND_TRUST_CERT=yes

# Opcionales
BEHIND_PROXY=true
SESSION_COOKIE_SECURE=True
ENABLE_SWAGGER=False
RATELIMIT_ENABLED=True
EOF

# Establecer permisos restrictivos
chmod 600 .env
```

### Opción B: Variables de Sistema

```bash
# En ~/.bashrc o ~/.bash_profile
export DEBUG=False
export SECRET_KEY=tu-clave-aqui
export API_SECRET=tu-api-secret-aqui
export LOCAL_DB_USER=app_user
export LOCAL_DB_PASS=tu_password
# ... resto de variables
```

---

## 3️⃣ Validar Configuración

```bash
# Activar virtualenv (si no lo está)
source venv/bin/activate

# Ejecutar validador
python validate_db_config.py

# Salida esperada:
# ✓ LOCAL_SERVER: ...
# ✓ LOCAL_DB_NAME: ...
# ✓ LOCAL_DB_USER: ...
# ✓ LOCAL_DB_ENCRYPT: no
# ✓ LOCAL_DB_TRUST_CERT: yes
# ✓ pyodbc disponible
# ✓ ODBC Driver 18 for SQL Server encontrado
```

Si hay **errores críticos (❌)**: Corrígelos antes de continuar.  
Si hay **advertencias (⚠)**: Revisar, pero podrían no ser bloqueantes.

---

## 4️⃣ Test de Conectividad SQL

### Verificar driver ODBC

```bash
# Listar todos los drivers disponibles
odbcinst -q -d

# Esperado:
# ODBC Driver 18 for SQL Server
# ODBC Driver 17 for SQL Server
```

### Test de conexión con sqlcmd (si disponible)

```bash
# Para BD Local
sqlcmd -S "tu-servidor\SQLEXPRESS" \
       -U "app_user" \
       -P "tu_password" \
       -d "Softland_Mock" \
       -Q "SELECT 1 AS TEST" \
       -l 5

# Para Softland
sqlcmd -S "tu-servidor-erp\SOFTLAND" \
       -U "usuario_softland" \
       -P "password_softland" \
       -d "ZDESARROLLO" \
       -Q "SELECT 1 AS TEST" \
       -l 5
```

---

## 5️⃣ Iniciar la Aplicación Localmente

### Modo Desarrollo

```bash
# Activar virtualenv
source venv/bin/activate

# Ejecutar con Flask (puerto 5000)
python app.py

# Esperado en logs:
# INFO - Base de datos local (SQLAlchemy): mssql+pyodbc://app_user:***@...
# INFO - Base de datos local (pyodbc legacy): Driver={ODBC Driver 18...};...;PWD=***
# WARNING - Werkzeug serving on http://0.0.0.0:5000
```

### Probar endpoint

```bash
# En otra terminal
curl http://localhost:5000/health
# Expected: {"status":"ok"}
```

---

## 6️⃣ Desplegar con Gunicorn

### Instalar Gunicorn

```bash
pip install gunicorn
```

### Crear archivo de configuración

```bash
cat > gunicorn_config.py << 'EOF'
import multiprocessing

workers = multiprocessing.cpu_count() * 2 + 1
worker_class = 'sync'
worker_connections = 1000
timeout = 30
keepalive = 2
max_requests = 1000
max_requests_jitter = 50
bind = '0.0.0.0:5000'
accesslog = '-'
errorlog = '-'
loglevel = 'info'
EOF
```

### Iniciar servicio

```bash
# Opción 1: Directo
source venv/bin/activate
gunicorn -c gunicorn_config.py app:app

# Opción 2: Con systemd (recomendado)
# Ver sección Systemd Service más abajo
```

---

## 7️⃣ Configurar Systemd Service (Recomendado)

### Crear archivo de servicio

```bash
sudo tee /etc/systemd/system/flask-tracking.service > /dev/null << 'EOF'
[Unit]
Description=Flask Tracking Logístico
After=network.target

[Service]
Type=notify
User=www-data
WorkingDirectory=/home/deploy/tracking-app
Environment="PATH=/home/deploy/tracking-app/venv/bin"
ExecStart=/home/deploy/tracking-app/venv/bin/gunicorn \
    -c gunicorn_config.py \
    --timeout 30 \
    --access-logfile /var/log/tracking-app/access.log \
    --error-logfile /var/log/tracking-app/error.log \
    app:app
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

# Crear directorio de logs
sudo mkdir -p /var/log/tracking-app
sudo chown www-data:www-data /var/log/tracking-app

# Habilitar servicio
sudo systemctl daemon-reload
sudo systemctl enable flask-tracking
sudo systemctl start flask-tracking

# Ver status
sudo systemctl status flask-tracking

# Ver logs en vivo
sudo journalctl -u flask-tracking -f
```

---

## 8️⃣ Configurar Nginx como Reverse Proxy

```bash
sudo tee /etc/nginx/sites-available/tracking-api << 'EOF'
server {
    listen 80;
    server_name tu-dominio.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    location /health {
        access_log off;
        proxy_pass http://127.0.0.1:5000;
    }
}
EOF

# Habilitar sitio
sudo ln -s /etc/nginx/sites-available/tracking-api /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 🔍 Verificación Post-Despliegue

### Checklist

- [ ] ✓ Virtualenv creado y activado
- [ ] ✓ Dependencies instaladas (`pip list`)
- [ ] ✓ ODBC Driver 18 disponible (`odbcinst -q -d`)
- [ ] ✓ .env creado con permisos restrictivos
- [ ] ✓ Validación pasada sin errores críticos
- [ ] ✓ Conexión a BD Local verificada
- [ ] ✓ Conexión a Softland verificada
- [ ] ✓ Endpoint `/health` respondiendo
- [ ] ✓ Logs sin errores de conexión
- [ ] ✓ Systemd service corriendo (si aplica)
- [ ] ✓ Nginx respondiendo (si aplica)

### Pruebas de Conectividad

```bash
# Endpoint de salud
curl -i http://localhost:5000/health

# Con proxy nginx
curl -i http://tu-dominio.com/health

# Revisar logs de aplicación
sudo journalctl -u flask-tracking -n 50
```

---

## 📊 Monitoreo

### Ver logs en vivo

```bash
# Si usas systemd
sudo journalctl -u flask-tracking -f

# Si usas logs de archivo
tail -f /var/log/tracking-app/error.log
tail -f /var/log/tracking-app/access.log
```

### Reiniciar servicio

```bash
sudo systemctl restart flask-tracking

# Forzar reload (sin downtime)
sudo systemctl reload flask-tracking
```

### Monitorar uso de recursos

```bash
# Ver PID del proceso
pgrep -f gunicorn

# Monitorear con top
top -p $(pgrep -f gunicorn | head -1)

# Ver conexiones de BD abiertas
netstat -tupn | grep -E ':(1433|5000)'
```

---

## 🆘 Troubleshooting

### Error: "ODBC Driver 18 not found"

```bash
# Instalar driver
sudo apt-get install msodbcsql18

# Verificar
odbcinst -q -d -n "ODBC Driver 18 for SQL Server"
```

### Error: "Login timeout expired"

```bash
# 1. Revisar credenciales en .env
cat .env | grep -E "DB_USER|DB_PASS|LOCAL_DB_USER"

# 2. Probar conexión con sqlcmd
sqlcmd -S tu-servidor -U usuario -P contraseña -d base -Q "SELECT 1"

# 3. Revisar firewall
sudo ufw allow 1433/tcp
```

### Error: "SSL Provider: certificate verify failed"

```bash
# Solución: Actualizar .env
LOCAL_DB_TRUST_CERT=yes
SOFTLAND_TRUST_CERT=yes

# Reiniciar servicio
sudo systemctl restart flask-tracking
```

### Error: "pyodbc connection timeout"

```bash
# Aumentar timeout en .env o config.py
SOFTLAND_TIMEOUT=30  # aumentar de 15

# Reiniciar
sudo systemctl restart flask-tracking
```

### Ver logs detallados

```bash
# Aumentar nivel de log
# En app.py: logging.basicConfig(level=logging.DEBUG)
# O en .env: FLASK_DEBUG=True (solo dev)

# Ver logs
sudo journalctl -u flask-tracking -n 200 -p debug
```

---

## 📚 Archivos Importantes

| Archivo | Propósito |
|---------|-----------|
| `.env` | Variables de entorno (NO versionear) |
| `config.py` | Configuraciones de aplicación |
| `app.py` | Punto de entrada Flask |
| `validate_db_config.py` | Script de validación |
| `DEPLOYMENT_ODBC_DRIVER18.md` | Guía detallada de despliegue |
| `CHANGES_SUMMARY.md` | Resumen de cambios técnicos |

---

## 🎯 Próximos Pasos

1. **SSL/TLS**: Usar Let's Encrypt con Nginx
   ```bash
   sudo apt-get install certbot python3-certbot-nginx
   sudo certbot certonly --nginx -d tu-dominio.com
   ```

2. **Monitoreo**: Configurar alertas (Prometheus, Datadog, etc.)

3. **CI/CD**: Usar GitHub Actions para despliegues automáticos

4. **Backups**: Automatizar backups de BD
   ```bash
   # Agregar a crontab
   0 2 * * * sqlcmd -S servidor -U user -P pass -Q "BACKUP DATABASE..."
   ```

---

## 📞 Soporte

- **Errores de configuración**: Revisar `DEPLOYMENT_ODBC_DRIVER18.md`
- **Errores técnicos**: Ver logs con `journalctl -u flask-tracking -f`
- **Problemas de driver**: Ver `validate_db_config.py`

---

**Última actualización**: 2026-04-16  
**Versión**: 1.0  
**Entorno**: Ubuntu 20.04 LTS / 22.04 LTS
