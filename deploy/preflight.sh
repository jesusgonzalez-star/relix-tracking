#!/usr/bin/env bash
# =============================================================================
# preflight.sh — Validación pre-deploy de Tracking Logistico v1.2.9
#
# Ejecutar ANTES de arrancar el servicio en un servidor recién provisionado.
# Verifica que todo lo crítico está en su lugar. NO modifica nada.
#
# Uso:
#   sudo bash deploy/preflight.sh
# =============================================================================
set -u

ENV_FILE="${ENV_FILE:-/etc/tracking-app/env}"
APP_DIR="${APP_DIR:-/opt/tracking-app}"
APP_USER="${APP_USER:-www-data}"

PASS=0
FAIL=0
WARN=0

ok()   { echo "  [OK]   $1"; PASS=$((PASS+1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
warn() { echo "  [WARN] $1"; WARN=$((WARN+1)); }

echo "============================================================"
echo "Pre-flight check Tracking App"
echo "APP_DIR=$APP_DIR  ENV_FILE=$ENV_FILE"
echo "============================================================"

# ---- 1. Archivos críticos ----
echo ""
echo "[1] Archivos y directorios"
[ -f "$APP_DIR/app.py" ] && ok "app.py presente" || fail "app.py no encontrado en $APP_DIR"
[ -f "$APP_DIR/wsgi.py" ] && ok "wsgi.py presente" || fail "wsgi.py no encontrado"
[ -f "$APP_DIR/gunicorn_config.py" ] && ok "gunicorn_config.py presente" || fail "gunicorn_config.py no encontrado"
[ -f "$APP_DIR/requirements.txt" ] && ok "requirements.txt presente" || fail "requirements.txt no encontrado"
[ -d "$APP_DIR/.venv" ] && ok ".venv presente" || fail ".venv no encontrado (ejecutar install.sh)"
[ -f "$APP_DIR/deploy/init_db.sql" ] && ok "init_db.sql presente" || warn "init_db.sql no encontrado (esquema manual?)"

# ---- 2. Variables de entorno críticas ----
echo ""
echo "[2] Variables en $ENV_FILE"
if [ ! -r "$ENV_FILE" ]; then
    fail "$ENV_FILE no legible — ¿ejecutaste install.sh?"
else
    ok "$ENV_FILE existe y es legible"
    # Cargar solo vars, sin ejecutar
    set -a; source "$ENV_FILE" 2>/dev/null || true; set +a

    req_vars=(SECRET_KEY API_SECRET SQLALCHEMY_DATABASE_URI DB_SERVER DB_USER DB_PASS ALLOWED_HOSTS)
    for v in "${req_vars[@]}"; do
        val="${!v:-}"
        if [ -z "$val" ]; then
            fail "$v vacía o no definida"
        elif [[ "$val" == *"CHANGE_ME"* ]]; then
            fail "$v contiene placeholder 'CHANGE_ME' — rellenar con valor real"
        else
            ok "$v definida"
        fi
    done

    # DEBUG obligatorio False
    if [ "${DEBUG:-True}" = "True" ] || [ "${DEBUG:-true}" = "true" ]; then
        fail "DEBUG=True en producción — debe ser False"
    else
        ok "DEBUG=False"
    fi

    # SECRET_KEY longitud
    if [ "${#SECRET_KEY}" -lt 32 ]; then
        fail "SECRET_KEY tiene ${#SECRET_KEY} chars — mínimo 32"
    fi

    # BEHIND_PROXY
    if [ "${BEHIND_PROXY:-False}" = "True" ] || [ "${BEHIND_PROXY:-false}" = "true" ]; then
        ok "BEHIND_PROXY=True (ProxyFix activo)"
    else
        warn "BEHIND_PROXY no activo — IPs reales en logs no se capturan"
    fi
fi

# ---- 3. Permisos ----
echo ""
echo "[3] Permisos"
if [ -f "$ENV_FILE" ]; then
    perm=$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo "???")
    if [ "$perm" = "600" ]; then
        ok "$ENV_FILE permisos 600"
    else
        fail "$ENV_FILE permisos $perm (debe ser 600)"
    fi
    owner=$(stat -c '%U' "$ENV_FILE" 2>/dev/null || echo "???")
    [ "$owner" = "root" ] && ok "$ENV_FILE dueño=root" || warn "$ENV_FILE dueño=$owner (esperado: root)"
fi

# ---- 4. Servicios ----
echo ""
echo "[4] Servicios del sistema"
systemctl is-enabled mariadb >/dev/null 2>&1 && ok "mariadb habilitado" || warn "mariadb no habilitado"
systemctl is-active  mariadb >/dev/null 2>&1 && ok "mariadb activo" || fail "mariadb no activo"
systemctl is-enabled apache2 >/dev/null 2>&1 && ok "apache2 habilitado" || warn "apache2 no habilitado"
systemctl is-enabled redis-server >/dev/null 2>&1 && ok "redis habilitado" || warn "redis no habilitado (rate-limiter necesita redis con >1 worker)"

# ---- 5. Apache config ----
echo ""
echo "[5] Apache"
if [ -f /etc/apache2/sites-available/tracking.conf ]; then
    ok "tracking.conf instalado"
    if grep -q "tracking.ejemplo.cl" /etc/apache2/sites-available/tracking.conf; then
        fail "ServerName 'tracking.ejemplo.cl' (placeholder) — editar con FQDN real"
    else
        ok "ServerName parece personalizado"
    fi
else
    fail "/etc/apache2/sites-available/tracking.conf no encontrado"
fi

# ---- 6. Backup ----
echo ""
echo "[6] Backup"
[ -x /etc/cron.daily/tracking-backup ] && ok "cron.daily backup instalado" || warn "backup diario no instalado"

# ---- Resumen ----
echo ""
echo "============================================================"
echo "Resumen: $PASS OK, $WARN WARN, $FAIL FAIL"
echo "============================================================"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "DEPLOY BLOQUEADO: hay $FAIL fallos críticos. Corregir antes de systemctl start."
    exit 1
fi
if [ "$WARN" -gt 0 ]; then
    echo ""
    echo "Deploy posible pero con $WARN avisos. Revisar."
    exit 0
fi
echo ""
echo "Todo listo. Puedes arrancar: sudo systemctl start tracking-app"
exit 0
