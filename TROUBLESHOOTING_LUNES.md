# 🚨 TROUBLESHOOTING RÁPIDO

## Problema 1: "502 Bad Gateway"

### Síntoma:
```
Error 502 Bad Gateway en navegador
```

### Causas posibles:
1. Gunicorn no está corriendo
2. Gunicorn crashed
3. MariaDB no está disponible

### Solución:

```bash
# 1. Verificar estado
systemctl status tracking-app

# 2. Ver logs
journalctl -u tracking-app -n 50 -e

# 3. Verificar MariaDB
mysql -u tracking_user -p tracking_db -e "SELECT 1;"

# 4. Reiniciar app
systemctl restart tracking-app
sleep 3
systemctl status tracking-app

# 5. Probar localmente
curl http://127.0.0.1:5000/health
```

---

## Problema 2: "Cannot connect to Softland"

### Síntoma:
```
Error: ODBC Driver 17 for SQL Server not found
O: Connection timeout to RELIX-SQL01\SOFTLAND
```

### Solución:

```bash
# 1. Instalar driver ODBC
apt install -y unixodbc unixodbc-dev freetds-bin

# 2. Verificar instalación
odbcinst -j

# 3. Probar conexión ODBC
isql -v -k "Driver={ODBC Driver 17 for SQL Server};Server=RELIX-SQL01\SOFTLAND;Database=ZDESARROLLO02;UID=JGonzalez;PWD=PASSWORD"

# 4. Si no funciona, revisar:
# - DB_SERVER en .env
# - DB_PASS correcto
# - Firewall permite puerto 1433
```

---

## Problema 3: "MySQL server has gone away"

### Síntoma:
```
Error: (pymysql.err.OperationalError) (2006, 'MySQL server has gone away')
```

### Solución:

```bash
# 1. Verificar MariaDB
systemctl status mariadb

# 2. Reiniciar MariaDB
systemctl restart mariadb

# 3. Reiniciar app
systemctl restart tracking-app

# 4. Aumentar pool_recycle en .env
DB_POOL_RECYCLE=1800  # en lugar de 3600
```

---

## Problema 4: "Port 5000 already in use"

### Síntoma:
```
Error: Address already in use (127.0.0.1:5000)
```

### Solución:

```bash
# 1. Ver qué está usando el puerto
lsof -i :5000

# 2. Matar el proceso (si es un gunicorn viejo)
kill -9 <PID>

# 3. Reiniciar systemd service
systemctl restart tracking-app
```

---

## Problema 5: "SSL Certificate not found"

### Síntoma:
```
Error: SSLCertificateFile /etc/letsencrypt/live/tudominio.com/fullchain.pem not found
Apache fails to start
```

### Solución:

```bash
# 1. Generar certificado
certbot certonly --apache -d tudominio.com -d www.tudominio.com

# 2. Verificar que existe
ls -la /etc/letsencrypt/live/tudominio.com/

# 3. Recargar Apache
systemctl reload apache2
```

---

## Problema 6: "DB_PASS not configured"

### Síntoma:
```
RuntimeError: Configuración de producción incompleta: defina en el entorno 
las variables SECRET_KEY, API_SECRET, DB_PASS.
```

### Solución:

```bash
# 1. Verificar .env
cat /opt/tracking-app/.env | grep -E "SECRET_KEY|API_SECRET|DB_PASS"

# 2. Si faltan, completar
nano /opt/tracking-app/.env

# 3. Reiniciar app
systemctl restart tracking-app
```

---

## Problema 7: "Permission denied" en logs

### Síntoma:
```
PermissionError: [Errno 13] Permission denied: '/opt/tracking-app/...'
```

### Solución:

```bash
# 1. Verificar permisos
ls -la /opt/tracking-app/

# 2. Reparar permisos
chown -R www-data:www-data /opt/tracking-app
chown -R www-data:www-data /var/log/tracking-app
chmod 755 /opt/tracking-app
chmod 755 /opt/tracking-app/storage
chmod 755 /opt/tracking-app/storage/evidencias

# 3. Reiniciar
systemctl restart tracking-app
```

---

## Problema 8: "Health check returns 503"

### Síntoma:
```
curl http://127.0.0.1:5000/health
{"status": "error", "database": "disconnected"}
```

### Solución:

```bash
# 1. Probar BD directamente
mysql -u tracking_user -p tracking_db -e "SELECT 1;"

# 2. Revisar logs
journalctl -u tracking-app -f

# 3. Ver si hay errores de conexión
tail -f /var/log/mysql/error.log

# 4. Reiniciar todo
systemctl restart mariadb
systemctl restart tracking-app
sleep 5
curl http://127.0.0.1:5000/health
```

---

## Problema 9: "Apache takes too long / timeout"

### Síntoma:
```
gateway timeout después de 180 segundos
```

### Solución:

```bash
# 1. Aumentar timeouts en Apache
# Editar: /etc/apache2/sites-available/tracking.conf
ProxyTimeout 300
ProxyConnectTimeout 60

# 2. Aumentar timeout en gunicorn
# Editar: /opt/tracking-app/.env
TIMEOUT=300

# 3. Recargar todo
systemctl reload apache2
systemctl restart tracking-app
```

---

## Problema 10: "Rate limiter not working"

### Síntoma:
```
Puedo hacer 1000 requests sin limite
```

### Solución:

```bash
# 1. Verificar que esté habilitado
grep RATELIMIT_ENABLED /opt/tracking-app/.env

# 2. Si está disabled, habilitar
sed -i 's/RATELIMIT_ENABLED=False/RATELIMIT_ENABLED=True/' /opt/tracking-app/.env

# 3. Reiniciar
systemctl restart tracking-app

# 4. Para multi-worker: usar Redis
apt install -y redis-server
systemctl start redis-server
systemctl enable redis-server

# 5. Editar .env
RATELIMIT_STORAGE_URI=redis://localhost:6379

systemctl restart tracking-app
```

---

## COMANDOS DE EMERGENCIA

### Rollback rápido:
```bash
# Si todo falla, volver a versión anterior
cd /opt/tracking-app
git revert HEAD --no-edit
systemctl restart tracking-app
```

### Reset total:
```bash
# PELIGROSO: borra todo y recomienzo
systemctl stop tracking-app
rm -rf /opt/tracking-app
mysql -u root -p -e "DROP DATABASE tracking_db;"
# Luego ejecutar COMMANDS_LUNES.sh de nuevo
```

### Ver todo en tiempo real:
```bash
# Terminal 1: App logs
journalctl -u tracking-app -f

# Terminal 2: Apache logs
tail -f /var/log/tracking-app/access.log

# Terminal 3: Estadísticas
watch -n 1 'ps aux | grep gunicorn | grep -v grep | wc -l'
```

---

**Más problemas? Revisar:**
- `/var/log/tracking-app/error.log`
- `/var/log/tracking-app/access.log`
- `journalctl -u tracking-app -n 100`
- `journalctl -u apache2 -n 100`
