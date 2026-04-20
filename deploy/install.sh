#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# install.sh — Instalación nativa en Debian 12 + Apache + MariaDB
# -----------------------------------------------------------------------------
# Uso (como root):
#   sudo bash deploy/install.sh
#
# Qué hace (sin tocar secretos ni contraseñas):
#   - instala paquetes del SO (apache2, mariadb-client, redis-server,
#     unixodbc, msodbcsql18, Python 3.11+)
#   - copia el proyecto a /opt/tracking-app (excluye archivos de análisis
#     internos, .env, __pycache__, instance/, storage/, etc.)
#   - crea venv e instala requirements.txt
#   - crea /var/data/tracking/evidencias y /var/log/tracking con owner www-data
#   - copia deploy/env.example a /etc/tracking-app/env (si no existe)
#   - registra tracking-app.service en systemd
#   - configura Apache VirtualHost (deja apache-tracking.conf disponible)
#
# Qué NO hace (manual):
#   - crear la base de datos MariaDB (ver sección final)
#   - rellenar /etc/tracking-app/env con secretos reales
#   - emitir certificados TLS (usar certbot)
#   - iniciar tracking-app.service (arrancar sólo tras rellenar env)
# -----------------------------------------------------------------------------
set -euo pipefail

APP_USER="www-data"
APP_GROUP="www-data"
APP_DIR="/opt/tracking-app"
DATA_DIR="/var/data/tracking"
EVIDENCE_DIR="$DATA_DIR/evidencias"
LOG_DIR="/var/log/tracking"
ENV_DIR="/etc/tracking-app"
ENV_FILE="$ENV_DIR/env"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: ejecutar como root (sudo bash $0)" >&2
    exit 1
fi

echo "[1/8] Instalando paquetes base del SO ..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-dev \
    build-essential pkg-config \
    apache2 \
    mariadb-client \
    redis-server \
    unixodbc unixodbc-dev \
    curl ca-certificates gnupg \
    rsync dos2unix

# ODBC Driver 18 para SQL Server (Softland)
if ! dpkg -s msodbcsql18 >/dev/null 2>&1; then
    echo "    -> Instalando Microsoft ODBC Driver 18 para SQL Server ..."
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg
    DEB_CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
    curl -fsSL "https://packages.microsoft.com/config/debian/${DEB_CODENAME}/prod.list" \
        -o /etc/apt/sources.list.d/mssql-release.list
    # pin de firma al keyring descargado
    sed -i 's|deb \[|deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg |' \
        /etc/apt/sources.list.d/mssql-release.list || true
    apt-get update -qq
    ACCEPT_EULA=Y apt-get install -y msodbcsql18
fi

echo "[2/8] Habilitando módulos y sitios de Apache ..."
a2enmod proxy proxy_http ssl headers rewrite expires deflate
a2dissite 000-default.conf >/dev/null 2>&1 || true

echo "[3/8] Preparando $APP_DIR ..."
mkdir -p "$APP_DIR"
rsync -a --delete \
    --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.pytest_cache' --exclude='.coverage' --exclude='htmlcov' \
    --exclude='*.log' --exclude='*.bak' --exclude='*.bak.*' \
    --exclude='tracking.db*' --exclude='instance' --exclude='storage' \
    --exclude='.env' --exclude='.env.*' \
    --exclude='.git' --exclude='.github' --exclude='.vscode' --exclude='.idea' \
    --exclude='.claude' --exclude='.cursor' --exclude='.cursorignore' \
    --exclude='ANALISIS_*' --exclude='RESUMEN_*' --exclude='INFORME_*' \
    --exclude='CHECKLIST_*' --exclude='DEPLOYMENT_*' --exclude='DEPLOY_*' \
    --exclude='PLAN_*' --exclude='VERIFICACION_*' --exclude='QUICK_START*' \
    --exclude='TROUBLESHOOTING_*' --exclude='ESCANEO_*' --exclude='COMMANDS_*' \
    --exclude='PRE-DEPLOYMENT*' --exclude='CREDENCIALES_*' \
    --exclude='tests' --exclude='run_tests.py' \
    "$SRC_DIR"/ "$APP_DIR"/

# Normalizar line endings de scripts shell (por si vinieron de Windows)
find "$APP_DIR/deploy" -name '*.sh' -exec dos2unix -q {} \; 2>/dev/null || true

echo "[4/8] Creando venv e instalando dependencias Python ..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel setuptools
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "[5/8] Preparando directorios de datos y logs ..."
mkdir -p "$DATA_DIR" "$EVIDENCE_DIR" "$LOG_DIR" "$ENV_DIR" "$APP_DIR/instance"
chown -R "$APP_USER:$APP_GROUP" "$APP_DIR" "$DATA_DIR" "$LOG_DIR"
chmod 750 "$DATA_DIR" "$LOG_DIR" "$APP_DIR/instance"
chmod 750 "$EVIDENCE_DIR"

echo "[6/8] Plantilla de variables de entorno en $ENV_FILE ..."
if [ ! -f "$ENV_FILE" ]; then
    install -m 600 -o root -g root "$APP_DIR/deploy/env.example" "$ENV_FILE"
    echo "    -> $ENV_FILE creado desde deploy/env.example. RELLENAR SECRETOS."
else
    echo "    -> $ENV_FILE ya existe, no se sobrescribe."
fi

echo "[7/8] Registrando servicio systemd ..."
install -m 644 "$APP_DIR/deploy/tracking-app.service" /etc/systemd/system/tracking-app.service
systemctl daemon-reload
systemctl enable tracking-app.service

echo "[8/8] Instalando VirtualHost de Apache (sin activar) ..."
install -m 644 "$APP_DIR/deploy/apache-tracking.conf" /etc/apache2/sites-available/tracking.conf

# Redis para rate limiting multi-worker
systemctl enable --now redis-server || true

cat <<EOF

============================================================
Instalación base completa en Debian. PASOS MANUALES RESTANTES:

  1. Crear base de datos MariaDB (una sola vez):
       sudo mariadb -e "
         CREATE DATABASE tracking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
         CREATE USER 'tracking_app'@'localhost' IDENTIFIED BY 'CAMBIAR_PASSWORD';
         GRANT ALL PRIVILEGES ON tracking.* TO 'tracking_app'@'localhost';
         FLUSH PRIVILEGES;"

  2. Rellenar /etc/tracking-app/env con valores reales:
       - SECRET_KEY y API_SECRET (generar cada uno con:
           python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
       - SQLALCHEMY_DATABASE_URI=mysql+pymysql://tracking_app:PASS@127.0.0.1:3306/tracking?charset=utf8mb4
       - DB_SERVER / DB_USER / DB_PASS de Softland
       - ALLOWED_HOSTS=tudominio.empresa.cl
       - CORS_ALLOWED_ORIGINS=https://tudominio.empresa.cl
       - RATELIMIT_STORAGE_URI=redis://127.0.0.1:6379

  3. Verificar conexión a Softland:
       sudo -u $APP_USER $APP_DIR/.venv/bin/python \\
         $APP_DIR/verify_zdesarrollo02.py

  4. Activar Apache VirtualHost y emitir TLS con Let's Encrypt:
       sudo a2ensite tracking.conf
       sudo systemctl reload apache2
       sudo apt install certbot python3-certbot-apache
       sudo certbot --apache -d tudominio.empresa.cl

  5. Arrancar servicio:
       sudo systemctl start tracking-app
       sudo systemctl status tracking-app
       curl http://127.0.0.1:5000/health

  6. Programar backup diario (tras tener credenciales de BD en env):
       sudo cp $APP_DIR/deploy/backup.sh /etc/cron.daily/tracking-backup
       sudo chmod +x /etc/cron.daily/tracking-backup

  7. Healthcheck automático cada 5 min (opcional):
       sudo cp $APP_DIR/deploy/healthcheck.sh /usr/local/sbin/tracking-healthcheck
       sudo chmod +x /usr/local/sbin/tracking-healthcheck
       echo '*/5 * * * * root /usr/local/sbin/tracking-healthcheck' \\
         | sudo tee /etc/cron.d/tracking-healthcheck
============================================================
EOF
