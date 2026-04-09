# Tracking logístico (Flask)

- Arranque: `python app.py` o Gunicorn con `app:create_app()`.
- Configuración: variables de entorno y [`config.py`](config.py); plantilla sin secretos en [`.env.example`](.env.example) (`ENABLE_SWAGGER`, `SESSION_COOKIE_SECURE`, etc.).
- Documentación: carpeta [`docs/`](docs/) (despliegue Linux/Apache, reporte de limpieza).
- Manual de uso operativo: [`docs/MANUAL_USO_COMPLETO.md`](docs/MANUAL_USO_COMPLETO.md).
- Notas antiguas: [`docs/historico/`](docs/historico/) (fuera del índice del agente por `.cursorignore`).
