# Instructivo de despliegue en Linux con Apache

Este documento describe cómo publicar la aplicación Flask de tracking en un servidor **Linux**, usando **Apache** como proxy inverso frente a **Gunicorn**. No sustituye las políticas de seguridad o red de su organización.

## Arquitectura recomendada

- **Apache** escucha en el puerto **443** (HTTPS) y opcionalmente **80** (redirección a HTTPS).
- **Gunicorn** escucha solo en **127.0.0.1** (o en un socket Unix) y ejecuta la aplicación Flask.
- La aplicación se conecta a **Microsoft SQL Server** mediante **pyodbc** (Softland en solo lectura y base local de tracking).

```
Cliente → Apache (TLS) → Gunicorn → Flask → SQL Server
```

---

## 1. Requisitos previos

- Servidor Linux actualizado (ejemplos: Ubuntu Server 22.04/24.04, Debian 12, RHEL 8/9, AlmaLinux).
- Python **3.10 o superior** recomendado.
- Acceso de red desde el servidor hacia:
  - Instancia de **SQL Server** donde está la base **local** (tracking, usuarios).
  - Instancia de **SQL Server** de **Softland** (solo lectura, según su configuración).
- Nombre DNS o certificado TLS para el sitio (producción).

---

## 2. Instalar Apache y módulos de proxy

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install -y apache2
sudo a2enmod proxy proxy_http headers ssl rewrite
sudo systemctl restart apache2
```

### RHEL / AlmaLinux / Rocky (httpd)

```bash
sudo dnf install -y httpd mod_ssl
# proxy y proxy_http suelen estar ya disponibles; habilítelos en conf si aplica
sudo systemctl enable --now httpd
```

---

## 3. Driver ODBC para SQL Server en Linux

La aplicación usa **pyodbc**; en el servidor Linux debe existir el **Microsoft ODBC Driver for SQL Server** (17 o 18).

### Ubuntu (ejemplo con driver 18; Microsoft publica instrucciones actualizadas)

Siga la guía oficial de Microsoft para su distribución: busque *"Install the Microsoft ODBC driver for SQL Server on Linux"*.

Comprobación típica:

```bash
odbcinst -q -d
```

Debe listar algo como `ODBC Driver 18 for SQL Server` o `ODBC Driver 17 for SQL Server`.

### Dependencias para compilar pyodbc (si `pip install pyodbc` falla)

Debian/Ubuntu:

```bash
sudo apt install -y build-essential unixodbc-dev python3-dev
```

RHEL:

```bash
sudo dnf install -y gcc unixODBC-devel python3-devel
```

---

## 4. Usuario del sistema y directorio de la aplicación

Cree un usuario sin privilegios para ejecutar el servicio (ejemplo: `relix`):

```bash
sudo useradd --system --create-home --home-dir /opt/relix --shell /usr/sbin/nologin relix
```

Copie el proyecto (por ejemplo con `git clone`, `rsync` o despliegue de artefacto) bajo `/opt/relix/app` o la ruta que defina. Ajuste propietario:

```bash
sudo chown -R relix:relix /opt/relix/app
```

---

## 5. Entorno virtual Python e instalación de dependencias

```bash
sudo -u relix bash
cd /opt/relix/app
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Nota:** Si al ejecutar la aplicación faltan paquetes (por ejemplo extensiones Flask usadas en el proyecto pero no listadas en `requirements.txt`), instálelos con `pip install <paquete>` y documente la versión en su control interno de dependencias.

---

## 6. Variables de entorno (producción)

Defina al menos:

| Variable | Descripción |
|----------|-------------|
| `SECRET_KEY` | Clave larga y aleatoria para sesiones Flask (obligatorio en producción). |
| `DEBUG` | `False` |
| `SESSION_COOKIE_SECURE` | `True` cuando todo el tráfico al usuario final vaya por **HTTPS** detrás de Apache. |
| `EVIDENCE_UPLOAD_DIR` | Ruta absoluta donde guardar evidencias (ej. `/opt/relix/app/storage/evidencias`). |
| `MAX_CONTENT_LENGTH` | Opcional; límite de subida en bytes (la app tiene un valor por defecto en configuración). |
| `DB_SERVER`, `DB_NAME`, `DB_USER`, `DB_PASS`, `DB_DRIVER` | Conexión **Softland** (solo lectura en la cadena de la aplicación). |
| `LOCAL_SERVER`, `LOCAL_DB_NAME` | Servidor e instancia/base **local** de tracking (según su entorno). |
| `PORT` | Puerto interno de Gunicorn (ej. `5000`). |
| `WORKERS` | Número de workers de Gunicorn (entero; si no está definido, use el valor por defecto del archivo de configuración de Gunicorn). |
| `RATELIMIT_ENABLED` | `True`/`False`: limita peticiones por IP en `/api/softland` y `/api/tracking` (memoria; con varios workers configure almacenamiento Redis para Flask-Limiter si lo necesita). |
| `RATELIMIT_API` | Cadena tipo `60 per minute` (syntax de limits). |
| `TRACKING_VALIDATE_OC_IN_SOFTLAND` | Si `True`, `POST /api/tracking` exige que la OC exista en Softland (más carga al ERP). |

Ejemplo de archivo **no versionado** en el servidor: `/etc/relix/relix.env`

```bash
SECRET_KEY=cambie_por_un_valor_largo_y_aleatorio
DEBUG=False
SESSION_COOKIE_SECURE=True
EVIDENCE_UPLOAD_DIR=/opt/relix/app/storage/evidencias
LOCAL_SERVER=su_servidor_sql
LOCAL_DB_NAME=Softland_Mock
DB_SERVER=su_servidor_softland
DB_NAME=ZDESARROLLO
DB_USER=usuario_lectura
DB_PASS=contraseña
DB_DRIVER=ODBC Driver 18 for SQL Server
PORT=5000
WORKERS=3
```

Permisos restrictivos:

```bash
sudo chmod 640 /etc/relix/relix.env
sudo chown root:relix /etc/relix/relix.env
```

### Base de datos local en Linux (importante)

En el código del proyecto, la conexión local mediante SQLAlchemy y la conexión usada por el frontend heredado suelen apuntar a **autenticación integrada de Windows** (`Trusted_Connection=yes`). En un servidor **Linux** eso **no equivale** al mismo mecanismo que en Windows.

Opciones habituales:

1. **Autenticación SQL** (usuario y contraseña de SQL Server) para la base local: deberá configurar su entorno para que las cadenas de conexión usadas por la aplicación sean válidas en Linux (esto puede implicar ajustes en la configuración del proyecto en su copia de despliegue; consulte con quien mantenga el código).
2. **Kerberos / Active Directory** con ODBC (configuración avanzada de dominio).

Sin una de estas, la aplicación puede fallar al conectar a la base local aunque Apache y Gunicorn estén bien configurados.

---

## 7. Directorio de evidencias y permisos

```bash
sudo mkdir -p /opt/relix/app/storage/evidencias
sudo chown -R relix:relix /opt/relix/app/storage
```

Si usa **SELinux** (RHEL, etc.), puede necesitar contextos adicionales para que Apache o el proceso de Gunicorn puedan escribir; consulte la documentación de su distribución.

---

## 8. Gunicorn

El proyecto incluye `gunicorn_config.py` (bind, timeouts, logs). Desde el directorio de la aplicación, con el venv activado:

```bash
cd /opt/relix/app
source venv/bin/activate
export $(grep -v '^#' /etc/relix/relix.env | xargs -d '\n')
gunicorn -c gunicorn_config.py "app:create_app()"
```

Compruebe que Gunicorn usa el **mismo** `create_app` definido en `app.py`. Si su versión de Gunicorn requiere explícitamente fábrica de aplicación, puede usar:

```bash
gunicorn --factory -c gunicorn_config.py "app:create_app"
```

(Consulte `gunicorn --help` en su entorno.)

Para pruebas locales en el servidor:

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/
```

---

## 9. systemd (servicio en segundo plano)

Cree `/etc/systemd/system/relix-tracking.service`:

```ini
[Unit]
Description=ReliX tracking Flask (Gunicorn)
After=network.target

[Service]
Type=notify
User=relix
Group=relix
WorkingDirectory=/opt/relix/app
EnvironmentFile=/etc/relix/relix.env
ExecStart=/opt/relix/app/venv/bin/gunicorn -c /opt/relix/app/gunicorn_config.py "app:create_app()"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Si `Type=notify` no es compatible con su combinación Gunicorn/systemd, cambie a `Type=simple`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable relix-tracking
sudo systemctl start relix-tracking
sudo systemctl status relix-tracking
```

Logs:

```bash
journalctl -u relix-tracking -f
```

También revise `access.log` y `error.log` en el directorio de trabajo si así lo define `gunicorn_config.py`.

---

## 10. Apache: VirtualHost con proxy inverso

Ejemplo **Debian/Ubuntu** (`/etc/apache2/sites-available/relix.conf`). Ajuste `ServerName` y rutas de certificados.

```apache
<VirtualHost *:443>
    ServerName tracking.ejemplo.com

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/su_certificado.crt
    SSLCertificateKeyFile /etc/ssl/private/su_clave.key
    # SSLCertificateChainFile /etc/ssl/certs/cadena.crt   # si aplica

    ProxyPreserveHost On
    RequestHeader set X-Forwarded-Proto "https"
    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"

    ProxyPass / http://127.0.0.1:5000/
    ProxyPassReverse / http://127.0.0.1:5000/

    # Opcional: limitar tamaño de cuerpo (coherente con MAX_CONTENT_LENGTH)
    LimitRequestBody 16777216

    ErrorLog ${APACHE_LOG_DIR}/relix-error.log
    CustomLog ${APACHE_LOG_DIR}/relix-access.log combined
</VirtualHost>
```

Habilitar sitio y recargar Apache:

```bash
sudo a2ensite relix.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

Redirección HTTP → HTTPS (ejemplo en puerto 80):

```apache
<VirtualHost *:80>
    ServerName tracking.ejemplo.com
    Redirect permanent / https://tracking.ejemplo.com/
</VirtualHost>
```

### Archivos estáticos (opcional)

Para aligerar Gunicorn, puede servir `static/` desde Apache:

```apache
    Alias /static /opt/relix/app/static
    <Directory /opt/relix/app/static>
        Require all granted
    </Directory>
```

Deje el `ProxyPass` para el resto de rutas.

---

## 11. Certificados TLS

- **Let’s Encrypt:** use `certbot` con el plugin de Apache según la guía oficial de su distribución.
- **Certificado corporativo:** instale cadena completa y actualice las directivas `SSLCertificateFile` / `SSLCertificateChainFile`.

---

## 12. Comprobaciones finales

1. `systemctl is-active relix-tracking` → `active`
2. `curl -k -I https://tracking.ejemplo.com/` → respuesta HTTP 200 o 302 según la raíz de la app
3. Inicio de sesión en la interfaz web y una operación que use subida de archivo (evidencias).
4. Conexión a SQL Server: si hay errores pyodbc en logs, verifique driver ODBC, firewall, credenciales y el tema de **Trusted_Connection** en Linux (sección 6).

---

## 13. Mantenimiento breve

- **Actualizar código:** detener servicio, desplegar nueva versión, `pip install -r requirements.txt` si cambió, arrancar servicio.
- **Backups:** base de datos local y carpeta `storage/evidencias`.
- **Seguridad:** mantener el SO parcheado, rotar `SECRET_KEY` solo con plan de cierre de sesiones, no exponer el puerto de Gunicorn a Internet (solo localhost).

---

## 14. Referencia de archivos del proyecto (sin modificarlos aquí)

| Archivo | Uso en despliegio |
|---------|-------------------|
| `app.py` | Fábrica `create_app` para Gunicorn |
| `config.py` | Variables de entorno y rutas |
| `gunicorn_config.py` | Bind, workers, timeouts, logs |
| `utils/db_legacy.py` | Conexión pyodbc usada por gran parte del frontend |
| `requirements.txt` | Dependencias pip base |

---

*Documento generado como guía de despliegue. Ajuste rutas, nombres de servicio y políticas internas a su organización.*
