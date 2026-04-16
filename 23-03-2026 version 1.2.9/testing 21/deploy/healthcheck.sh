#!/bin/bash
# Healthcheck automatico - ejecutar via cron cada 5 minutos
# Reinicia gunicorn si /health no responde 200

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://localhost:5000/health)
if [ "$RESPONSE" != "200" ]; then
    echo "$(date) - ALERTA: Health check fallo (HTTP $RESPONSE) - reiniciando tracking-app" >> /var/log/tracking-healthcheck.log
    systemctl restart tracking-app
fi
