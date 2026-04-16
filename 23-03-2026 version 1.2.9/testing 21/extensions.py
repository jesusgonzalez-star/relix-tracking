import os

from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
ma = Marshmallow()

# memory:// funciona con 1 worker; para multi-worker use redis://localhost:6379
_limiter_storage = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_limiter_storage,
    default_limits=[],
    headers_enabled=True,
)
