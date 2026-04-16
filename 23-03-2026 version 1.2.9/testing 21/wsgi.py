"""
Punto de entrada WSGI para producción (gunicorn / mod_wsgi / Apache).

Uso con gunicorn:
    gunicorn -c gunicorn_config.py wsgi:app

Uso con mod_wsgi (Apache):
    WSGIScriptAlias / /opt/tracking-app/wsgi.py
"""
from app import create_app

app = create_app()
