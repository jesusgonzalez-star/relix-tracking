from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
ma = Marshmallow()
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri='memory://',
    default_limits=[],
    headers_enabled=True,
)
