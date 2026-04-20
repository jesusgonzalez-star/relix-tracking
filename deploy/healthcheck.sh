#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# healthcheck.sh — Monitoreo pasivo de tracking-app con backoff
# -----------------------------------------------------------------------------
# Uso (cron cada 5 min):
#   */5 * * * * root /usr/local/sbin/tracking-healthcheck
#
# Reinicia el servicio solo tras N fallos CONSECUTIVOS para evitar loops de
# restart cuando el endpoint falla puntualmente (p.ej. reload de Apache,
# refresh de conexiones, etc.).
# -----------------------------------------------------------------------------
set -eu

HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5000/health}"
STATE_FILE="${STATE_FILE:-/var/lib/tracking/health-failures}"
LOG_FILE="${LOG_FILE:-/var/log/tracking/healthcheck.log}"
FAIL_THRESHOLD="${FAIL_THRESHOLD:-3}"
SERVICE="${SERVICE:-tracking-app}"
TIMEOUT="${TIMEOUT:-10}"

mkdir -p "$(dirname "$STATE_FILE")" "$(dirname "$LOG_FILE")"

RESPONSE="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" "$HEALTH_URL" || echo 000)"
NOW="$(date '+%Y-%m-%d %H:%M:%S')"

if [ "$RESPONSE" = "200" ]; then
    # Éxito: resetear contador de fallos
    if [ -s "$STATE_FILE" ]; then
        echo "$NOW - OK (HTTP 200) tras $(cat "$STATE_FILE") fallo(s) previo(s)" >> "$LOG_FILE"
    fi
    echo 0 > "$STATE_FILE"
    exit 0
fi

# Fallo: incrementar contador
FAILS=0
[ -s "$STATE_FILE" ] && FAILS="$(cat "$STATE_FILE")"
FAILS=$((FAILS + 1))
echo "$FAILS" > "$STATE_FILE"

echo "$NOW - FAIL (HTTP $RESPONSE) - fallo $FAILS/$FAIL_THRESHOLD" >> "$LOG_FILE"

if [ "$FAILS" -ge "$FAIL_THRESHOLD" ]; then
    echo "$NOW - ALERTA: $FAILS fallos consecutivos, reiniciando $SERVICE" >> "$LOG_FILE"
    systemctl restart "$SERVICE"
    echo 0 > "$STATE_FILE"
fi
