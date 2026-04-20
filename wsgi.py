"""
Punto de entrada WSGI para producción (gunicorn / mod_wsgi / Apache).

Uso con gunicorn:
    gunicorn -c gunicorn_config.py wsgi:app

Uso con mod_wsgi (Apache):
    WSGIScriptAlias / /opt/tracking-app/wsgi.py

Guardas de producción:
- Bloquea DEBUG=True al cargar el módulo WSGI.
- Exige que el worker corra bajo un servidor WSGI real (no Flask dev server).
"""
import os

# Fail-fast: WSGI jamás debe servir con DEBUG=True.
# Si alguien copia un .env de desarrollo al servidor, mejor no arrancar.
if (os.environ.get('DEBUG', 'False') or '').strip().lower() == 'true':
    raise RuntimeError(
        'wsgi.py: DEBUG=True está activo en producción. Revise /etc/tracking-app/env o '
        'la variable de entorno DEBUG antes de arrancar gunicorn.'
    )

# Fail-fast: FLASK_ENV=development también es señal de copia accidental del .env de dev.
if (os.environ.get('FLASK_ENV', '') or '').strip().lower() == 'development':
    raise RuntimeError(
        'wsgi.py: FLASK_ENV=development en producción. Defina FLASK_ENV=production '
        '(o quite la variable) antes de arrancar gunicorn.'
    )

from app import create_app  # noqa: E402

app = create_app()
