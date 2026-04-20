# 🚀 GUÍA DE DEPLOYMENT: LUNES 21 DE ABRIL
## Debian 12 + Apache + MariaDB (4-6 horas)

---

## ⏰ TIMELINE

| Hora | Tarea | Duración |
|------|-------|----------|
| 08:00 | Fase 1: Setup sistema | 30 min |
| 08:30 | Fase 2: Instalar app | 20 min |
| 09:00 | Fase 3: Configurar BD | 15 min |
| 09:15 | Fase 4: Variables .env | 15 min |
| 09:30 | Fase 5: Probar local | 20 min |
| 09:50 | Fase 6: Apache + SSL | 40 min |
| 10:30 | Fase 7: Systemd | 15 min |
| 10:45 | Fase 8: Validar | 15 min |
| **11:00** | **🎉 LIVE** | |

---

## 📋 FASE 1: SETUP DEL SISTEMA (30 min)

**En servidor Debian 12 como root:**

```bash
# 1.1 Actualizar e instalar dependencias
apt update
apt install -y python3-pip python3-venv libmysqlclient-dev \
    mariadb-client mariadb-server apache2 apache2-utils git curl

# 1.2 Habilitar módulos Apache
a2enmod proxy proxy_http rewrite headers ssl
systemctl restart apache2

# 1.3 Crear directorios
mkdir -p /opt/tracking-app/storage/evidencias
mkdir -p /var/log/tracking-app
chown -R www-data:www-data /opt/tracking-app
chown -R www-data:www-data /var/log/tracking-app
chmod 755 /opt/tracking-app

# 1.4 Verificar MariaDB activo
systemctl start mariadb
systemctl enable mariadb
```

✅ **Checkpoint:** `mysql --version` debe mostrar MariaDB

---

## 📋 FASE 2: INSTALAR APLICACIÓN (20 min)

```bash
# 2.1 Copiar código a /opt/tracking-app
# (O usar git clone si está en repositorio)
cd /opt/tracking-app

# 2.2 Crear virtual environment
python3 -m venv venv
source venv/bin/activate

# 2.3 Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn PyMySQL

# 2.4 Verificar que app.py funciona
python3 -c "from app import create_app; print('✅ OK')"
```

✅ **Checkpoint:** `ls -la venv/bin/gunicorn`

---

## 📋 FASE 3: CONFIGURAR MARIADB (15 min)

**En servidor Debian:**

```bash
# 3.1 Conectarse a MariaDB
mysql -u root

# 3.2 Ejecutar en MySQL:
CREATE DATABASE tracking_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'tracking_user'@'localhost' IDENTIFIED BY 'CONTRASEÑA_FUERTE_AQUI';
GRANT ALL PRIVILEGES ON tracking_db.* TO 'tracking_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 3.3 Probar conexión
mysql -u tracking_user -p tracking_db -e "SELECT 1;"
```

✅ **Checkpoint:** Conexión exitosa a tracking_db

---

## 📋 FASE 4: CONFIGURAR .ENV (15 min)

**En /opt/tracking-app:**

```bash
# 4.1 Copiar template
cp .env.example .env

# 4.2 Generar secretos (ejecutar en local, no en servidor)
# EN TU COMPUTADORA:
python3 -c "import os; print('SECRET_KEY=' + os.urandom(32).hex())"
python3 -c "import os; print('API_SECRET=' + os.urandom(32).hex())"

# 4.3 Editar .env con:
nano /opt/tracking-app/.env
```

**Valores críticos a cambiar:**

```bash
DEBUG=False
FLASK_ENV=production
SECRET_KEY=<GENERAR_NUEVO>
API_SECRET=<GENERAR_NUEVO>

# Base de datos LOCAL (MariaDB)
SQLALCHEMY_DATABASE_URI=mysql+pymysql://tracking_user:CONTRASEÑA_DEL_PASO_3@localhost/tracking_db

# Base de datos REMOTA (Softland ERP)
DB_PASS=<PASSWORD_DE_JGONZALEZ_EN_SOFTLAND>
DB_SERVER=RELIX-SQL01\SOFTLAND

# Dominio
CORS_ALLOWED_ORIGINS=https://tudominio.com,https://www.tudominio.com

# Apache
BEHIND_PROXY=True

# Cookies (HTTPS)
SESSION_COOKIE_SECURE=True
```

✅ **Checkpoint:** `grep -v "^#" .env | grep "=" | wc -l` >= 20

---

## 📋 FASE 5: PROBAR LOCALMENTE (20 min)

**En /opt/tracking-app:**

```bash
source venv/bin/activate

# 5.1 Verificar config
python3 verify_production_config.py
# Debe mostrar ✅ en todos

# 5.2 Inicializar BD (crear tablas)
python3 << 'EOFIX'
from app import create_app
app = create_app()
print('✅ App inicializada')
EOFIX

# 5.3 Prueba rápida de gunicorn (30 segundos)
timeout 30 gunicorn -w 1 -b 127.0.0.1:5000 wsgi:app 2>&1 | head -20 &
sleep 5

# 5.4 Probar endpoint
curl -s http://127.0.0.1:5000/health | python3 -m json.tool
# Respuesta esperada: {"status": "ok", "database": "connected"}
```

✅ **Checkpoint:** `/health` retorna 200 con status ok

---

## 📋 FASE 6: CONFIGURAR APACHE (40 min)

### 6.1 Crear VirtualHost

**Crear archivo:** `/etc/apache2/sites-available/tracking.conf`

```apache
# HTTP → HTTPS redirect
<VirtualHost *:80>
    ServerName tracking.tudominio.com
    ServerAlias www.tracking.tudominio.com
    Redirect permanent / https://tracking.tudominio.com/
</VirtualHost>

# HTTPS proxy a Gunicorn
<VirtualHost *:443>
    ServerName tracking.tudominio.com
    ServerAlias www.tracking.tudominio.com
    
    # SSL (obtener con Certbot abajo)
    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/tracking.tudominio.com/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/tracking.tudominio.com/privkey.pem
    SSLCertificateChainFile /etc/letsencrypt/live/tracking.tudominio.com/chain.pem
    
    # Logging
    ErrorLog /var/log/tracking-app/error.log
    CustomLog /var/log/tracking-app/access.log combined
    
    # PROXY a Gunicorn
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:5000/ timeout=180
    ProxyPassReverse / http://127.0.0.1:5000/
    
    # Headers (para que Flask vea IP real)
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
    RequestHeader set X-Forwarded-Proto "%{REQUEST_SCHEME}s"
    RequestHeader set X-Forwarded-Host "%{HTTP_HOST}s"
    
    # Timeouts
    ProxyTimeout 180
    ProxyConnectTimeout 30
    
    # Seguridad
    Header set X-Content-Type-Options "nosniff"
    Header set X-Frame-Options "DENY"
    Header set Referrer-Policy "strict-origin-when-cross-origin"
</VirtualHost>
```

### 6.2 Habilitar sitio

```bash
a2dissite 000-default 2>/dev/null || true
a2ensite tracking
a2enmod proxy_http
apache2ctl configtest  # Debe mostrar "Syntax OK"
systemctl reload apache2
```

### 6.3 Obtener certificado SSL

```bash
# Instalar Certbot
apt install -y certbot python3-certbot-apache

# Generar certificado (REEMPLAZAR tracking.tudominio.com)
certbot certonly --apache -d tracking.tudominio.com -d www.tracking.tudominio.com

# Esto crea:
# /etc/letsencrypt/live/tracking.tudominio.com/
```

✅ **Checkpoint:** `apache2ctl configtest` = "Syntax OK"

---

## 📋 FASE 7: CREAR SYSTEMD SERVICE (15 min)

**Crear archivo:** `/etc/systemd/system/tracking-app.service`

```ini
[Unit]
Description=Tracking Logístico App
After=network.target mariadb.service

[Service]
Type=notify
User=www-data
WorkingDirectory=/opt/tracking-app
Environment="PATH=/opt/tracking-app/venv/bin"
EnvironmentFile=/opt/tracking-app/.env
ExecStart=/opt/tracking-app/venv/bin/gunicorn \
    --config gunicorn_config.py \
    --bind 127.0.0.1:5000 \
    --log-file /var/log/tracking-app/gunicorn.log \
    wsgi:app

Restart=on-failure
RestartSec=10s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Activar:**

```bash
systemctl daemon-reload
systemctl enable tracking-app
systemctl start tracking-app
sleep 3
systemctl status tracking-app
```

✅ **Checkpoint:** `systemctl status tracking-app` = "active (running)"

---

## 📋 FASE 8: VALIDAR (15 min)

### 8.1 Probar endpoints

```bash
# Health check
curl https://tracking.tudominio.com/health

# Status
curl https://tracking.tudominio.com/status

# Página principal
curl -I https://tracking.tudominio.com/

# Debe retornar 200 en todos
```

### 8.2 Ver logs en tiempo real

```bash
# Logs de systemd
sudo journalctl -u tracking-app -f

# Logs de Apache
sudo tail -f /var/log/tracking-app/access.log

# Logs de MariaDB
sudo tail -f /var/log/mysql/error.log
```

### 8.3 Performance quick check

```bash
# Instalar Apache Bench
apt install -y apache2-utils

# Test: 100 requests, 5 concurrent
ab -n 100 -c 5 https://tracking.tudominio.com/health

# Debes ver:
# - Time per request: <500ms
# - Failed requests: 0
# - Successful requests: 100
```

✅ **Checkpoint:** Todos los tests pasan sin errores

---

## 🎯 VERIFICATION CHECKLIST

Antes de dar por "LIVE":

- [ ] `systemctl status tracking-app` = active (running)
- [ ] `curl https://tudominio.com/health` = 200 ok
- [ ] `curl https://tudominio.com/status` = 200 ok
- [ ] Apache access.log sin 500 errors
- [ ] `mysql -u tracking_user -p tracking_db -e "SELECT 1;"`  = exitoso
- [ ] Certificado SSL válido (no warning en navegador)
- [ ] Pods workers activos: `ps aux | grep gunicorn | grep -v grep | wc -l` = 4+

---

## 🚨 TROUBLESHOOTING RÁPIDO

### Error: "Cannot connect to Softland"
```bash
# Probar conexión ODBC
isql -v -k "Driver={ODBC Driver 17 for SQL Server};Server=RELIX-SQL01\SOFTLAND;..."
```

### Error: "MySQL server has gone away"
```bash
# Reiniciar MariaDB
sudo systemctl restart mariadb
sudo systemctl restart tracking-app
```

### Error: 502 Bad Gateway en Apache
```bash
# Verificar que Gunicorn está corriendo
ps aux | grep gunicorn

# Ver logs de app
journalctl -u tracking-app -n 50

# Reiniciar
systemctl restart tracking-app
```

### Port 5000 ya está en uso
```bash
lsof -i :5000
kill -9 <PID>
```

---

## 📞 CONTACTOS IMPORTANTES

- **Softland DB Admin:** (contacto)
- **Proveedor de dominio:** (contacto)
- **Soporte MariaDB:** docs.mariadb.com
- **Soporte Apache:** httpd.apache.org

---

## 📊 COMANDO FINAL: "GO LIVE"

```bash
# Todo está listo cuando:
curl -s https://tracking.tudominio.com/status | grep -q '"status": "ok"' && echo "✅ LIVE" || echo "❌ Falla"
```

---

**¿Preguntas? Revisar DEPLOY_CHECKLIST.md**
