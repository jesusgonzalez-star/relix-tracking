#!/bin/bash
#
# COMANDOS COPY-PASTE PARA DEPLOYMENT LUNES
# Ejecutar en orden: bash COMMANDS_LUNES.sh
#
# Nota: Reemplazar "tudominio.com" por tu dominio real
#

echo "=========================================="
echo "DEPLOYMENT: LUNES 21 DE ABRIL"
echo "=========================================="
echo ""

# ──────────────────────────────────────────
# PARTE 1: SETUP (ejecutar como root)
# ──────────────────────────────────────────

echo "PASO 1: Actualizar sistema..."
apt update && apt install -y python3-pip python3-venv libmysqlclient-dev \
    mariadb-client mariadb-server apache2 apache2-utils git curl certbot \
    python3-certbot-apache

echo "✅ Dependencias instaladas"
echo ""

echo "PASO 2: Habilitar módulos Apache..."
a2enmod proxy proxy_http rewrite headers ssl
systemctl restart apache2
echo "✅ Apache configurado"
echo ""

echo "PASO 3: Crear directorios..."
mkdir -p /opt/tracking-app/storage/evidencias
mkdir -p /var/log/tracking-app
chown -R www-data:www-data /opt/tracking-app
chown -R www-data:www-data /var/log/tracking-app
chmod 755 /opt/tracking-app
echo "✅ Directorios creados"
echo ""

echo "PASO 4: Iniciar MariaDB..."
systemctl start mariadb
systemctl enable mariadb
echo "✅ MariaDB iniciado"
echo ""

# ──────────────────────────────────────────
# PARTE 2: BASE DE DATOS
# ──────────────────────────────────────────

echo "PASO 5: Crear BD y usuario..."
echo ""
echo "===== IMPORTANTE ====="
echo "Vas a ingresar contraseña de root de MariaDB"
echo "Luego la contraseña del usuario 'tracking_user'"
echo "====================="
echo ""

read -sp "Contraseña de root MariaDB: " MYSQL_ROOT_PASS
echo ""
read -sp "Nueva contraseña para tracking_user: " TRACKING_PASS
echo ""

mysql -u root -p"$MYSQL_ROOT_PASS" << EOF
CREATE DATABASE tracking_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'tracking_user'@'localhost' IDENTIFIED BY '$TRACKING_PASS';
GRANT ALL PRIVILEGES ON tracking_db.* TO 'tracking_user'@'localhost';
FLUSH PRIVILEGES;
EOF

echo "✅ BD y usuario creados"
echo ""

# ──────────────────────────────────────────
# PARTE 3: INSTALAR APP
# ──────────────────────────────────────────

echo "PASO 6: Instalar app..."
cd /opt/tracking-app

# Aquí iría: git clone o copiar código
# Por ahora asumimos que está en /opt/tracking-app

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn PyMySQL

echo "✅ App instalada"
echo ""

# ──────────────────────────────────────────
# PARTE 4: CONFIGURAR .env
# ──────────────────────────────────────────

echo "PASO 7: Configurar .env..."
cp /opt/tracking-app/.env.example /opt/tracking-app/.env

# Generar secretos
SECRET_KEY=$(python3 -c "import os; print(os.urandom(32).hex())")
API_SECRET=$(python3 -c "import os; print(os.urandom(32).hex())")

# Actualizar valores
sed -i "s|^DEBUG=.*|DEBUG=False|" /opt/tracking-app/.env
sed -i "s|^FLASK_ENV=.*|FLASK_ENV=production|" /opt/tracking-app/.env
sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$SECRET_KEY|" /opt/tracking-app/.env
sed -i "s|^API_SECRET=.*|API_SECRET=$API_SECRET|" /opt/tracking-app/.env
sed -i "s|^BEHIND_PROXY=.*|BEHIND_PROXY=True|" /opt/tracking-app/.env
sed -i "s|^SESSION_COOKIE_SECURE=.*|SESSION_COOKIE_SECURE=True|" /opt/tracking-app/.env
sed -i "s|^SQLALCHEMY_DATABASE_URI=.*|SQLALCHEMY_DATABASE_URI=mysql+pymysql://tracking_user:$TRACKING_PASS@localhost/tracking_db|" /opt/tracking-app/.env

echo "✅ .env actualizado"
echo ""
echo "IMPORTANTE: Editar .env manualmente:"
echo "  nano /opt/tracking-app/.env"
echo ""
echo "Cambiar:"
echo "  - DB_PASS=<contraseña de JGonzalez>"
echo "  - CORS_ALLOWED_ORIGINS=https://tudominio.com"
echo "  - DB_SERVER=RELIX-SQL01\SOFTLAND (si es diferente)"
echo ""
read -p "Presiona ENTER cuando hayas editado .env..."
echo ""

# ──────────────────────────────────────────
# PARTE 5: PROBAR LOCALMENTE
# ──────────────────────────────────────────

echo "PASO 8: Prueba local..."
cd /opt/tracking-app
source venv/bin/activate

# Verificar config
python3 verify_production_config.py

# Inicializar BD
python3 << 'PYEOF'
from app import create_app
app = create_app()
print('✅ App inicializada')
PYEOF

echo "✅ Prueba local completada"
echo ""

# ──────────────────────────────────────────
# PARTE 6: APACHE VHOST
# ──────────────────────────────────────────

echo "PASO 9: Configurar Apache VirtualHost..."

read -p "Ingresa tu dominio (ej: tracking.tudominio.com): " DOMAIN

cat > /etc/apache2/sites-available/tracking.conf << APACHEEOF
<VirtualHost *:80>
    ServerName $DOMAIN
    ServerAlias www.$DOMAIN
    Redirect permanent / https://$DOMAIN/
</VirtualHost>

<VirtualHost *:443>
    ServerName $DOMAIN
    ServerAlias www.$DOMAIN

    SSLEngine on
    SSLCertificateFile /etc/letsencrypt/live/$DOMAIN/fullchain.pem
    SSLCertificateKeyFile /etc/letsencrypt/live/$DOMAIN/privkey.pem

    ErrorLog /var/log/tracking-app/error.log
    CustomLog /var/log/tracking-app/access.log combined

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:5000/ timeout=180
    ProxyPassReverse / http://127.0.0.1:5000/

    RequestHeader set X-Forwarded-For "%{REMOTE_ADDR}s"
    RequestHeader set X-Forwarded-Proto "%{REQUEST_SCHEME}s"
    RequestHeader set X-Forwarded-Host "%{HTTP_HOST}s"

    ProxyTimeout 180
    ProxyConnectTimeout 30

    Header set X-Content-Type-Options "nosniff"
    Header set X-Frame-Options "DENY"
</VirtualHost>
APACHEEOF

a2dissite 000-default 2>/dev/null || true
a2ensite tracking
apache2ctl configtest

echo "✅ VirtualHost configurado"
echo ""

# ──────────────────────────────────────────
# PARTE 7: CERTIFICADO SSL
# ──────────────────────────────────────────

echo "PASO 10: Obtener certificado SSL..."
certbot certonly --apache -d "$DOMAIN" -d "www.$DOMAIN"

systemctl reload apache2
echo "✅ SSL instalado"
echo ""

# ──────────────────────────────────────────
# PARTE 8: SYSTEMD SERVICE
# ──────────────────────────────────────────

echo "PASO 11: Crear systemd service..."

cat > /etc/systemd/system/tracking-app.service << SERVICEEOF
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
SERVICEEOF

systemctl daemon-reload
systemctl enable tracking-app
systemctl start tracking-app
sleep 3

echo "✅ Systemd service creado"
echo ""

# ──────────────────────────────────────────
# PARTE 9: VALIDAR
# ──────────────────────────────────────────

echo "PASO 12: Validar deployment..."

echo ""
echo "Verificaciones:"
systemctl status tracking-app
echo ""
echo "Health check:"
curl -s https://$DOMAIN/health | python3 -m json.tool
echo ""
echo "Status check:"
curl -s https://$DOMAIN/status | python3 -m json.tool
echo ""

echo "=========================================="
echo "✅ DEPLOYMENT COMPLETADO"
echo "=========================================="
echo ""
echo "App disponible en: https://$DOMAIN"
echo ""
echo "Monitoreo:"
echo "  Logs app: sudo journalctl -u tracking-app -f"
echo "  Logs Apache: sudo tail -f /var/log/tracking-app/access.log"
echo "  Estado: sudo systemctl status tracking-app"
echo ""
