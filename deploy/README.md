# Deploy — Tracking Logístico v1.2.9

Guía breve para desplegar en Debian 12 (Apache + Gunicorn + systemd + MariaDB + Redis).

## Orden de ejecución

```bash
# 1. Clonar repo en el servidor
sudo git clone https://github.com/jesusgonzalez-star/relix-tracking.git /opt/tracking-app
cd /opt/tracking-app

# 2. Ejecutar install.sh (instala paquetes, venv, systemd, cron backup, etc.)
sudo bash deploy/install.sh

# 3. Inicializar BD (se indica en el mensaje final de install.sh)
sudo mariadb -e "CREATE DATABASE tracking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
                 CREATE USER 'tracking_app'@'localhost' IDENTIFIED BY 'CAMBIAR_PASSWORD';
                 GRANT ALL PRIVILEGES ON tracking.* TO 'tracking_app'@'localhost';
                 FLUSH PRIVILEGES;"
sudo mariadb tracking < deploy/init_db.sql

# 4. Rellenar /etc/tracking-app/env (ver variables abajo)
sudo nano /etc/tracking-app/env

# 5. Validar pre-deploy
sudo bash deploy/preflight.sh

# 6. Si todo OK, arrancar
sudo systemctl start tracking-app
sudo systemctl status tracking-app
```

## Variables obligatorias en `/etc/tracking-app/env`

| Variable | Valor | Notas |
|----------|-------|-------|
| `SECRET_KEY` | 48+ chars aleatorios | Generar: `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` |
| `API_SECRET` | 48+ chars aleatorios | Distinto al SECRET_KEY |
| `SQLALCHEMY_DATABASE_URI` | `mysql+pymysql://tracking_app:PASS@127.0.0.1:3306/tracking?charset=utf8mb4` | Password real de MariaDB |
| `DB_SERVER` | `RELIX-SQL01\SOFTLAND` | SQL Server origen Softland |
| `DB_NAME` | nombre BD Softland prod | No usar `ZDESARROLLO02` en prod |
| `DB_USER` / `DB_PASS` | cuenta Softland | Rotar antes de deploy |
| `DB_DRIVER` | `ODBC Driver 18 for SQL Server` | install.sh instala el 18 |
| `DEBUG` | `False` | **CRÍTICO** — wsgi.py bloquea si es True |
| `BEHIND_PROXY` | `True` | Activa ProxyFix para IPs reales |
| `CSRF_ENABLED` | `True` | No sobrescribir a False |
| `SESSION_COOKIE_SECURE` | `True` | Cookies solo por HTTPS |

## `ALLOWED_HOSTS` — importante

**Qué hace:** Flask rechaza peticiones cuyo header `Host` no esté en la lista. Defensa contra Host header injection y cache poisoning.

**Formato:** lista separada por comas, SIN protocolo ni puertos.

```
ALLOWED_HOSTS=tracking.relixwater.cl
```

Múltiples hostnames (si usas alias):

```
ALLOWED_HOSTS=tracking.relixwater.cl,tracking-prod.relixwater.cl
```

**Comportamiento actual:** si `ALLOWED_HOSTS` está vacío, la app arranca igual pero loguea un WARNING (ver `app.py:141-155`). **Esto es intencional para no bloquear el primer arranque**, pero debes rellenarlo inmediatamente después.

**CORS relacionado:** `CORS_ALLOWED_ORIGINS` sí incluye protocolo:
```
CORS_ALLOWED_ORIGINS=https://tracking.relixwater.cl
```

## Apache — dominio y TLS

**Antes de activar el VirtualHost:**

```bash
sudo nano /etc/apache2/sites-available/tracking.conf
# Reemplazar TODAS las ocurrencias de "tracking.ejemplo.cl" con tu FQDN real
# (hay 2+: una en <VirtualHost> port 80, otra en port 443)
```

**Activar y emitir certificado Let's Encrypt:**

```bash
sudo a2ensite tracking.conf
sudo apt install certbot python3-certbot-apache
sudo certbot --apache -d tracking.relixwater.cl
sudo systemctl reload apache2
```

## Verificación post-deploy

```bash
# 1. Servicio arriba
curl http://127.0.0.1:5000/health     # debe devolver {"status":"ok","database":"mariadb-ok"}

# 2. Apache reverse-proxy
curl -I https://tracking.relixwater.cl/health

# 3. Rate limiter con Redis (no memory://)
redis-cli KEYS "LIMITER*" | head

# 4. Logs
sudo journalctl -u tracking-app -f        # systemd
sudo tail -f /var/log/tracking/app.log    # archivo rotado (10 MB x 10)

# 5. Backup manual
sudo /etc/cron.daily/tracking-backup
ls -la /var/backups/tracking/             # debe haber .sql.gz de hoy
```

## Troubleshooting

| Síntoma | Causa probable | Acción |
|---------|----------------|--------|
| `systemctl start` falla con `ENVIRONMENT error` | `/etc/tracking-app/env` mal formado o sin permiso 600 | `sudo chmod 600 /etc/tracking-app/env` y revisar sintaxis |
| `RuntimeError: DEBUG=True en producción` | `DEBUG=True` en env file | Cambiar a `DEBUG=False` |
| Apache devuelve 502 | Gunicorn caído | `systemctl status tracking-app` y `journalctl -u tracking-app -n 50` |
| Login funciona pero inmediatamente cierra sesión | `SESSION_COOKIE_SECURE=True` sin HTTPS | Finalizar certbot primero, o desactivar temporalmente |
| Rate limiter cuenta mal | `RATELIMIT_STORAGE_URI=memory://` con >1 worker | Cambiar a `redis://127.0.0.1:6379` |
| Subir foto falla con 413 | Archivo > `MAX_CONTENT_LENGTH` (16 MB) | Ajustar en env o reducir tamaño |
| Subir foto falla con "Formato no soportado" | Archivo no es JPEG/PNG/GIF/WebP/HEIC real (ej. .exe renombrado) | Rechazo intencional (magic bytes) |

## Mantenimiento periódico

**Limpieza de fotos huérfanas (recomendado mensual):**  
Si el proceso de la app muere abruptamente entre `foto.save()` y commit BD (OOM, kill -9, reboot), quedan archivos en `$EVIDENCE_DIR` sin referencia en BD. El código captura excepciones normales y borra, pero no cubre muerte del proceso. Cron sugerido: borrar archivos > 30 días no referenciados en `DespachosEnvio.UrlFotoEvidencia` ni `DespachosTracking.UrlFotoEvidencia`.

## Referencias

- `install.sh` — instalación inicial (9 pasos automatizados)
- `preflight.sh` — validación pre-arranque
- `init_db.sql` — esquema idempotente
- `backup.sh` — dump diario de MariaDB
- `healthcheck.sh` — cron opcional cada 5 min
- `env.example` — plantilla de variables
- `tracking-app.service` — unidad systemd con hardening
- `apache-tracking.conf` — VirtualHost con TLS y security headers
