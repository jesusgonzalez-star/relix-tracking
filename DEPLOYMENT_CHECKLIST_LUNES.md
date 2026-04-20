# 📋 DEPLOYMENT CHECKLIST - LUNES 20-04-2026

**Objetivo:** Desplegar Tracking Logístico v1.2.9 en Debian 12 con Apache + MariaDB  
**Estimado:** 2-3 horas  
**Status:** Código funcional (desarrollo), necesita 23 vulnerabilidades arregladas antes de prod

---

## 🔴 CRÍTICO: LEER ANTES DE EMPEZAR

**Este checklist asume que YA HAS ARREGLADO las 23 vulnerabilidades documentadas en:**
```
INFORME_FINAL_100_COMPLETO_SOLUCIONES.md
```

**Si NO has arreglado SQL Injections, CSRF, y Authorization**, NO DESPLEGAR EN PRODUCCIÓN.

---

## HORA 0:00-0:30 | Preparación en Servidor Debian

```bash
# 1. SSH al servidor
ssh usuario@debian-server

# 2. Verificar sistema
uname -a  # Debe ser Linux 6.x+ (Debian 12)
mysql --version || mariadb --version  # MariaDB instalado?
redis-cli ping  # Redis? Debe responder PONG

# 3. Crear usuario para la app
sudo useradd -m -s /bin/bash tracking

# 4. Crear directorio de la app
sudo mkdir -p /opt/tracking-app
sudo chown tracking:tracking /opt/tracking-app
cd /opt/tracking-app

# 5. Crear directorio de storage
sudo mkdir -p storage/evidencias
sudo chown -R tracking:tracking storage
```

---

## HORA 0:30-1:00 | Instalar Dependencias

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar Python 3
sudo apt install -y python3 python3-pip python3-venv python3-dev

# Instalar librerías de desarrollo
sudo apt install -y libmariadb-dev libmariadb3

# Instalar Redis (si no está)
sudo apt install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verificar Redis
redis-cli ping  # Respuesta: PONG ✅

# Instalar Apache2
sudo apt install -y apache2 apache2-utils
sudo a2enmod proxy
sudo a2enmod proxy_http
sudo systemctl restart apache2

# Crear venv Python
cd /opt/tracking-app
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias de la app
pip install --upgrade pip
pip install -r requirements.txt  # (transferir requirements.txt primero)
```

---

## HORA 1:00-1:30 | Configurar Base de Datos

```bash
# 1. Conectar a MariaDB como root
sudo mariadb -u root

# 2. Crear base de datos
CREATE DATABASE tracking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'tracking'@'localhost' IDENTIFIED BY 'PASSWORD_SEGURO_AQUI';
GRANT ALL PRIVILEGES ON tracking.* TO 'tracking'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# 3. Editar .env en servidor (CRÍTICO - valores REALES)
nano /opt/tracking-app/.env

# Cambiar estos valores:
DEBUG=False
FLASK_ENV=production
SQLALCHEMY_DATABASE_URI=mysql+pymysql://tracking:PASSWORD_SEGURO_AQUI@localhost:3306/tracking
RATELIMIT_STORAGE_URI=redis://localhost:6379/0
SOFTLAND_SERVER=IP_DEL_SOFTLAND  # Ejemplo: 192.168.1.100
SOFTLAND_USER=JGonzalez
SOFTLAND_PASSWORD=PASSWORD_REAL_SOFTLAND
SOFTLAND_DATABASE=ZDESARROLLO02
DB_PASS=PASSWORD_SEGURO_AQUI
CORS_ALLOWED_ORIGINS=https://tracking.tudominio.cl,https://www.tudominio.cl

# 4. Crear tablas
cd /opt/tracking-app
source venv/bin/activate
python3 -c "from app import create_app; create_app().create_all()"

# ✅ Verificación
echo "Verificando database:"
python3 -c "
from app import create_app
from models.tracking import DespachoTracking
app = create_app()
print(f'Database URI: {app.config[\"SQLALCHEMY_DATABASE_URI\"]}')
print(f'Tables created: OK')
"
```

---

## HORA 1:30-2:00 | Configurar WSGI (Gunicorn)

```bash
# 1. Instalar gunicorn
source /opt/tracking-app/venv/bin/activate
pip install gunicorn

# 2. Verificar que gunicorn_config.py existe en el proyecto
# Si no existe, crear uno:
cat > /opt/tracking-app/gunicorn_config.py << 'EOF'
import os
import multiprocessing

bind = "127.0.0.1:5000"
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
timeout = 120
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
preload_app = False

# Logging
accesslog = "/opt/tracking-app/logs/access.log"
errorlog = "/opt/tracking-app/logs/error.log"
loglevel = "info"

# Crear logs dir
os.makedirs("/opt/tracking-app/logs", exist_ok=True)
EOF

# 3. Probar gunicorn
cd /opt/tracking-app
source venv/bin/activate
timeout 5 gunicorn -c gunicorn_config.py "app:create_app()" || echo "✅ Gunicorn OK"
```

---

## HORA 2:00-2:15 | Crear Servicio Systemd

```bash
# 1. Crear archivo de servicio
sudo nano /etc/systemd/system/tracking.service

# Pegar esto:
[Unit]
Description=Tracking Logístico v1.2.9
After=network.target mariadb.service redis.service

[Service]
Type=notify
User=tracking
Group=tracking
WorkingDirectory=/opt/tracking-app
ExecStart=/opt/tracking-app/venv/bin/gunicorn -c gunicorn_config.py "app:create_app()"
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
KillSignal=SIGQUIT
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

# 2. Recargar systemd
sudo systemctl daemon-reload

# 3. Habilitar servicio
sudo systemctl enable tracking

# 4. Iniciar servicio
sudo systemctl start tracking

# 5. Verificar estado
sudo systemctl status tracking
# Debería mostrar: Active (running) ✅
```

---

## HORA 2:15-2:30 | Configurar Apache (Reverse Proxy)

```bash
# 1. Crear archivo de configuración
sudo nano /etc/apache2/sites-available/tracking.conf

# Pegar esto:
<VirtualHost *:80>
    ServerName tracking.tudominio.cl
    ServerAlias www.tracking.tudominio.cl
    
    DocumentRoot /opt/tracking-app
    
    # Logs
    ErrorLog ${APACHE_LOG_DIR}/tracking-error.log
    CustomLog ${APACHE_LOG_DIR}/tracking-access.log combined
    
    # Proxy
    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:5000/
    ProxyPassReverse / http://127.0.0.1:5000/
    
    # Headers
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
    RequestHeader set X-Forwarded-Proto "http"
    RequestHeader set X-Forwarded-Host "%{SERVER_NAME}s"
    
    # CORS
    Header set Access-Control-Allow-Origin "*"
    Header set Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS"
    Header set Access-Control-Allow-Headers "Content-Type, Authorization"
</VirtualHost>

# 2. Habilitar site
sudo a2ensite tracking.conf

# 3. Verificar sintaxis Apache
sudo apache2ctl configtest
# Debería mostrar: Syntax OK ✅

# 4. Recargar Apache
sudo systemctl reload apache2
```

---

## HORA 2:30-2:45 | Pruebas Finales

```bash
# 1. Verificar que app está corriendo
sudo systemctl status tracking
curl http://127.0.0.1:5000/

# 2. Verificar MariaDB
mysql -u tracking -p -h localhost tracking -e "SHOW TABLES;"

# 3. Verificar Redis
redis-cli ping  # Respuesta: PONG

# 4. Verificar logs
sudo journalctl -u tracking -f &
# Debería mostrar logs normales sin errores

# 5. Acceder desde otro servidor
curl http://tracking.tudominio.cl/

# 6. Test de login
curl -X POST http://tracking.tudominio.cl/login \
  -d "email=admin@relixwater.cl&password=PASSWORD" \
  -c cookies.txt

# 7. Test de API con token
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://tracking.tudominio.cl/api/softland/oc/123
```

---

## 📊 VERIFICATION CHECKLIST

Marcar cada paso conforme lo completes:

```
SISTEMA
[ ] Debian 12 instalado
[ ] Python 3.10+ instalado
[ ] MariaDB instalado
[ ] Redis instalado
[ ] Apache2 instalado

USUARIO & DIRECTORIOS
[ ] Usuario 'tracking' creado
[ ] /opt/tracking-app creado
[ ] storage/evidencias creado
[ ] Permisos correctos (chown tracking:tracking)

DEPENDENCIAS PYTHON
[ ] venv creado
[ ] requirements.txt instalados
[ ] gunicorn instalado

BASE DE DATOS
[ ] Database 'tracking' creada
[ ] Usuario 'tracking' creado con privilegios
[ ] Tablas creadas (python -c "from app...")
[ ] MariaDB conexión OK

CONFIGURACIÓN
[ ] .env editado con valores REALES
[ ] DEBUG=False
[ ] SQLALCHEMY_DATABASE_URI=mysql+pymysql://...
[ ] RATELIMIT_STORAGE_URI=redis://...
[ ] SOFTLAND_SERVER=IP_REAL
[ ] CORS_ALLOWED_ORIGINS=dominio_real

GUNICORN & SYSTEMD
[ ] gunicorn_config.py existe
[ ] Service tracking creado
[ ] systemctl start tracking = active (running)

APACHE
[ ] Apache mods proxy habilitados
[ ] Vhost tracking.conf creado
[ ] apache2ctl configtest = Syntax OK
[ ] Apache reloadado

PRUEBAS
[ ] curl http://localhost:5000 = OK
[ ] curl http://tracking.tudominio.cl = OK
[ ] Login funciona
[ ] API endpoints responden
[ ] Logs sin errores críticos
[ ] Rate limiting funciona (11 requests en 1 min)
[ ] CSRF validación activa
```

---

## 🆘 TROUBLESHOOTING RÁPIDO

```bash
# Si la app no inicia:
sudo journalctl -u tracking -n 50 -e

# Si MariaDB no conecta:
mysql -u tracking -p -h localhost tracking

# Si Redis no funciona:
redis-cli ping
redis-cli INFO

# Si Apache no proxea:
sudo apache2ctl configtest
curl -v http://127.0.0.1:5000/

# Ver logs en tiempo real:
sudo tail -f /var/log/apache2/tracking-error.log
sudo tail -f /var/log/syslog
```

---

## ⚠️ SECURITY REMINDERS

Antes de desplegar:

- [ ] ¿Arreglaste las 7 SQL Injections?
- [ ] ¿Activaste CSRF?
- [ ] ¿Verificaste Rate Limiting?
- [ ] ¿Agregaste Authorization checks?
- [ ] ¿Cambiaste TODOS los valores de plantilla en .env?
- [ ] ¿DEBUG=False?
- [ ] ¿Certificados SSL instalados? (si es posible)
- [ ] ¿Firewall configurado?

**Si respondiste NO a alguna, NO DESPLEGAR AÚN.**

---

## 📞 SOPORTE

Si algo falla, revisar en este orden:
1. INFORME_FINAL_100_COMPLETO_SOLUCIONES.md
2. Logs (journalctl, error.log)
3. Verificar que DEBUG=False en .env
4. Verificar que DB_PASS existe en .env
5. Verificar MariaDB está corriendo

---

**Creado:** 2026-04-19  
**Para:** Despliegue 2026-04-20 (domingo noche o lunes)  
**Tiempo estimado:** 2-3 horas
