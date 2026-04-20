import os

from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
ma = Marshmallow()

# memory:// funciona con 1 worker; para multi-worker use redis://localhost:6379
_limiter_storage = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

# En producción: usar IP real. En desarrollo detrás de proxy: confía en X-Forwarded-For
# (ProxyFix en app.py lo maneja). En debug local sin proxy: fallback a 'global'.
def _get_rate_limit_key():
    """Retorna IP real si está disponible, sino 'global' (dev)."""
    ip = get_remote_address()
    # Si no hay IP válida (dev), usar clave global para evitar fragmentación
    return ip if ip and ip != '127.0.0.1' else 'global'

limiter = Limiter(
    key_func=_get_rate_limit_key,
    storage_uri=_limiter_storage,
    default_limits=[],
    headers_enabled=True,
)
