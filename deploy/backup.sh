#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# backup.sh — Backup diario consistente de la base MariaDB
# -----------------------------------------------------------------------------
# Uso:
#   - Manual:  sudo bash /opt/tracking-app/deploy/backup.sh
#   - Cron:    copiar a /etc/cron.daily/tracking-backup (sin extensión)
#
# Usa mysqldump con --single-transaction para backup consistente SIN bloquear
# tablas (InnoDB). Funciona con la app en ejecución.
#
# Requisitos:
#   - mariadb-client instalado (apt install mariadb-client)
#   - /etc/tracking-app/env con SQLALCHEMY_DATABASE_URI definida
#     o variables MYSQL_HOST/MYSQL_USER/MYSQL_PASSWORD/MYSQL_DB
#
# Recomendado: usar archivo ~/.my.cnf del usuario root con:
#   [client]
#   user=backup_user
#   password=xxx
# Y luego ejecutar el script como ese usuario.
# -----------------------------------------------------------------------------
set -euo pipefail

# Cargar env de la app si existe (SQLALCHEMY_DATABASE_URI)
ENV_FILE="${ENV_FILE:-/etc/tracking-app/env}"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a && . "$ENV_FILE" && set +a
fi

# Parsear SQLALCHEMY_DATABASE_URI si está definida
# Formato esperado: mysql+pymysql://user:pass@host:port/db?charset=utf8mb4
if [ -n "${SQLALCHEMY_DATABASE_URI:-}" ]; then
    _uri="${SQLALCHEMY_DATABASE_URI#*://}"                      # strip scheme
    _cred="${_uri%%@*}"                                          # user:pass
    _hostdb="${_uri#*@}"                                         # host:port/db?...
    MYSQL_USER="${MYSQL_USER:-${_cred%%:*}}"
    MYSQL_PASSWORD="${MYSQL_PASSWORD:-${_cred#*:}}"
    _hostport="${_hostdb%%/*}"
    MYSQL_HOST="${MYSQL_HOST:-${_hostport%%:*}}"
    _port="${_hostport#*:}"
    if [ "$_port" = "$_hostport" ]; then _port=3306; fi
    MYSQL_PORT="${MYSQL_PORT:-$_port}"
    _db_and_qs="${_hostdb#*/}"
    MYSQL_DB="${MYSQL_DB:-${_db_and_qs%%\?*}}"
fi

: "${MYSQL_HOST:=127.0.0.1}"
: "${MYSQL_PORT:=3306}"
: "${MYSQL_USER:?MYSQL_USER no definido (ni SQLALCHEMY_DATABASE_URI parseable)}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD no definido}"
: "${MYSQL_DB:?MYSQL_DB no definido}"

BACKUP_DIR="${BACKUP_DIR:-/var/backups/tracking}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

TS="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/tracking-$TS.sql"

mkdir -p "$BACKUP_DIR"
chmod 750 "$BACKUP_DIR"

# Dump consistente: --single-transaction (no bloquea InnoDB)
# --quick        : stream fila a fila (evita OOM en tablas grandes)
# --routines     : incluye stored procs y funciones
# --events       : incluye scheduled events
# --triggers     : incluye triggers (default en dump, explícito por claridad)
# --set-gtid-purged=OFF : evita warnings cuando MariaDB no usa GTID
MYSQL_PWD="$MYSQL_PASSWORD" mysqldump \
    --host="$MYSQL_HOST" \
    --port="$MYSQL_PORT" \
    --user="$MYSQL_USER" \
    --single-transaction \
    --quick \
    --routines \
    --events \
    --triggers \
    --default-character-set=utf8mb4 \
    "$MYSQL_DB" > "$OUT"

# Comprimir
gzip -9 "$OUT"
chmod 640 "${OUT}.gz"

# Retención
find "$BACKUP_DIR" -name 'tracking-*.sql.gz' -mtime +"$RETENTION_DAYS" -delete

echo "Backup OK: ${OUT}.gz"
