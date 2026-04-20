import os
import re
import urllib.parse
from dotenv import load_dotenv

# Cargar .env desde el directorio actual (testing 21/)
_env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(_env_path)


def _validate_driver_18_params(encrypt: str, trust_cert: str) -> tuple:
    """Valida y normaliza parámetros de seguridad para ODBC Driver 18+.

    Returns:
        (encrypt_val, trust_cert_val) normalizados y validados.
    """
    encrypt_val = (encrypt or 'no').lower()
    trust_cert_val = (trust_cert or 'yes').lower()

    if encrypt_val not in ('yes', 'no', 'optional', 'mandatory'):
        encrypt_val = 'no'
    if trust_cert_val not in ('yes', 'no', 'true', 'false'):
        trust_cert_val = 'yes'

    return encrypt_val, trust_cert_val


def obfuscate_password_in_uri(uri: str) -> str:
    """
    Ofusca la contraseña en una URI SQLAlchemy para logging seguro.
    Soporta formatos:
    - mssql+pyodbc://user:password@host/db?...
    - mssql+pyodbc://@host/db?... (Trusted Connection)
    """
    if not uri:
        return uri
    # Reemplaza la contraseña (entre : y @) con ***
    return re.sub(
        r'(mssql\+pyodbc://[^:]*:)[^@]*(@)',
        r'\1***\2',
        uri,
        flags=re.IGNORECASE
    )


_MIN_SECRET_LEN = 32
_WEAK_SECRET_TOKENS = (
    'default-secret-key-123', 'change-me', 'changeme', 'cambiar',
    'secret', 'password', 'admin', 'test',
)


def _is_weak_secret(value: str) -> bool:
    """True si el secreto es demasiado corto o contiene marcadores de placeholder."""
    v = (value or '').strip()
    if len(v) < _MIN_SECRET_LEN:
        return True
    low = v.lower()
    return any(token in low for token in _WEAK_SECRET_TOKENS)


def validate_production_secrets(app):
    """
    En producción (DEBUG=False y no modo TESTING) exige:
    - SECRET_KEY, API_SECRET, DB_PASS definidas en el entorno.
    - SECRET_KEY y API_SECRET con longitud mínima de 32 caracteres y sin placeholders.
    Si algo falla, la app no arranca.
    """
    if app.config.get('DEBUG') or app.config.get('TESTING'):
        return
    missing = []
    for key in ('SECRET_KEY', 'API_SECRET', 'DB_PASS'):
        if not (os.environ.get(key) or '').strip():
            missing.append(key)
    if missing:
        raise RuntimeError(
            'Configuración de producción incompleta: defina en el entorno las variables '
            f"{', '.join(missing)}. Con DEBUG=False la aplicación no arranca sin ellas."
        )
    weak = [key for key in ('SECRET_KEY', 'API_SECRET')
            if _is_weak_secret(os.environ.get(key, ''))]
    if weak:
        raise RuntimeError(
            f"Secretos débiles detectados en {', '.join(weak)}: longitud mínima "
            f"{_MIN_SECRET_LEN} caracteres y sin placeholders ('changeme', 'cambiar', etc.). "
            "Genere valores fuertes con: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )


def validate_local_db_sql_auth(app):
    """
    Si LOCAL_DB_REQUIRE_SQL_AUTH=true en producción, exige LOCAL_DB_USER y LOCAL_DB_PASS
    (recomendado en Linux sin Integrated Security).
    """
    if app.config.get('DEBUG') or app.config.get('TESTING'):
        return
    if os.environ.get('LOCAL_DB_REQUIRE_SQL_AUTH', '').lower() != 'true':
        return
    user = (os.environ.get('LOCAL_DB_USER') or '').strip()
    pwd = (os.environ.get('LOCAL_DB_PASS') or '').strip()
    if not user or not pwd:
        raise RuntimeError(
            'LOCAL_DB_REQUIRE_SQL_AUTH=True exige LOCAL_DB_USER y LOCAL_DB_PASS en el entorno '
            '(autenticación SQL para la base local en Linux/Docker).'
        )


class Config:
    """Configuraciones base compartidas"""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # Sin valor por defecto: en producción debe venir del entorno (ver validate_production_secrets).
    SECRET_KEY = (os.environ.get('SECRET_KEY') or '').strip()
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    # /api/softland y /api/tracking: Bearer o X-API-Key; en prod obligatorio vía entorno.
    API_SECRET = (os.environ.get('API_SECRET') or '').strip()
    # Secreto anterior aceptado temporalmente durante rotación (vacío = desactivado).
    API_SECRET_OLD = (os.environ.get('API_SECRET_OLD') or '').strip()
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
    EVIDENCE_UPLOAD_DIR = os.environ.get(
        'EVIDENCE_UPLOAD_DIR',
        os.path.join(BASE_DIR, 'storage', 'evidencias')
    )
    # Límite por IP en blueprints /api/softland y /api/tracking (memoria; con varios workers use Redis).
    RATELIMIT_ENABLED = os.environ.get('RATELIMIT_ENABLED', 'True').lower() == 'true'
    RATELIMIT_API = os.environ.get('RATELIMIT_API', '60 per minute')
    # Endurecimientos de seguridad (CSRF habilitado por defecto, rate limiting)
    LOGIN_RATE_LIMIT_ENABLED = os.environ.get('LOGIN_RATE_LIMIT_ENABLED', 'True').lower() == 'true'
    RATELIMIT_LOGIN = os.environ.get('RATELIMIT_LOGIN', '10 per minute')
    CSRF_ENABLED = os.environ.get('CSRF_ENABLED', 'True').lower() == 'true'  # CRÍTICO: Habilitado por defecto
    HIDE_DEMO_CREDENTIALS = os.environ.get('HIDE_DEMO_CREDENTIALS', 'True').lower() == 'true'
    # Si True, POST /api/tracking exige que la OC exista en Softland.
    TRACKING_VALIDATE_OC_IN_SOFTLAND = (
        os.environ.get('TRACKING_VALIDATE_OC_IN_SOFTLAND', 'True').lower() == 'true'
    )
    # Session timeout: 30 minutos en producción para evitar session hijacking
    PERMANENT_SESSION_LIFETIME = int(os.environ.get('PERMANENT_SESSION_LIFETIME', '1800'))
    SESSION_REFRESH_EACH_REQUEST = os.environ.get('SESSION_REFRESH_EACH_REQUEST', 'True').lower() == 'true'
    # Dominio de email permitido para login/registro. Default mantiene compatibilidad
    # con la implementación previa; en despliegues multi-tenant usar env.
    ALLOWED_EMAIL_DOMAIN = (os.environ.get('ALLOWED_EMAIL_DOMAIN') or '@relixwater.cl').strip().lower()

class SoftlandConfig(Config):
    """
    ERP Softland (solo lectura en aplicación).
    Credenciales solo por entorno; DB_PASS sin default (obligatoria si DEBUG=False al arrancar).
    Para ODBC Driver 18 (Linux/Ubuntu): configura Encrypt y TrustServerCertificate via entorno.
    """
    # Credenciales Softland: defaults vacíos para evitar filtrar identificadores
    # corporativos en el repositorio. Todas vienen del entorno (.env / systemd).
    DB_SERVER = (os.environ.get('DB_SERVER') or '').strip()
    DB_NAME = (os.environ.get('DB_NAME') or '').strip()
    DB_USER = (os.environ.get('DB_USER') or '').strip()
    DB_PASS = (os.environ.get('DB_PASS') or '').strip()
    DB_DRIVER = os.environ.get('DB_DRIVER', 'ODBC Driver 17 for SQL Server')
    DB_TIMEOUT = int(os.environ.get('SOFTLAND_TIMEOUT', 15))
    OC_CACHE_TTL = int(os.environ.get('SOFTLAND_OC_CACHE_TTL', 300))
    DB_ENCRYPT = os.environ.get('SOFTLAND_ENCRYPT', 'no').lower()
    DB_TRUST_CERT = os.environ.get('SOFTLAND_TRUST_CERT', 'yes').lower()

    @classmethod
    def get_connection_string(cls):
        """
        Cadena de conexión para pyodbc a ERP Softland (solo lectura).
        Para ODBC Driver 18+: incluye automáticamente Encrypt y TrustServerCertificate.

        Robustez:
        - Soporta servidores con instancia SQL nombrada
        - Valida parámetros de seguridad para Driver 18
        - Usa ApplicationIntent=ReadOnly para optimización
        """
        if not (cls.DB_SERVER and cls.DB_NAME):
            raise ValueError(
                'Softland no configurado: defina DB_SERVER y DB_NAME en el entorno o .env.'
            )
        conn_str = (
            f"Driver={{{cls.DB_DRIVER}}};"
            f"Server={cls.DB_SERVER};"
            f"Database={cls.DB_NAME};"
            f"UID={cls.DB_USER};"
            f"PWD={cls.DB_PASS};"
            f"ApplicationIntent=ReadOnly;"
        )
        # Para ODBC Driver 18+: agregar Encrypt y TrustServerCertificate
        if 'Driver 18' in cls.DB_DRIVER:
            enc, tsc = _validate_driver_18_params(cls.DB_ENCRYPT, cls.DB_TRUST_CERT)
            conn_str += f"Encrypt={enc};TrustServerCertificate={tsc};"
        return conn_str

class LocalDbConfig(Config):
    """Base local (tracking / usuarios) sobre MariaDB/MySQL."""

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # SESSION_COOKIE_SECURE controlable vía .env para pruebas por IP local.
    # Nota: app.py aplica el default final según DEBUG (Secure=True en prod).
    SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'false').strip().lower() == 'true'


LocalDbConfig.SQLALCHEMY_DATABASE_URI = (
    os.environ.get('SQLALCHEMY_DATABASE_URI') or ''
).strip()

if not LocalDbConfig.SQLALCHEMY_DATABASE_URI:
    raise RuntimeError(
        'SQLALCHEMY_DATABASE_URI no está definida. Configure la URI de MariaDB en '
        '.env o en el entorno, p.ej. '
        'SQLALCHEMY_DATABASE_URI=mysql+pymysql://user:pass@host:3306/tracking'
    )

_db_uri_lower = str(LocalDbConfig.SQLALCHEMY_DATABASE_URI).lower()
if not any(dialect in _db_uri_lower for dialect in ['mysql', 'mariadb']):
    raise RuntimeError(
        f'SQLALCHEMY_DATABASE_URI no soportada: {LocalDbConfig.SQLALCHEMY_DATABASE_URI!r}. '
        'Solo se acepta MariaDB/MySQL (mysql+pymysql://...).'
    )

# Opciones del engine SQLAlchemy para MariaDB/MySQL:
# - pool_pre_ping: evita "MySQL server has gone away"
# - pool_recycle: renueva conexiones antes del wait_timeout del server (28800s=8h por defecto)
workers = int(os.environ.get('WORKERS', 1))
pool_size = int(os.environ.get('DB_POOL_SIZE', '10')) if workers <= 1 else int(os.environ.get('DB_POOL_SIZE', '5'))

LocalDbConfig.SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_pre_ping': True,
    'pool_recycle': int(os.environ.get('DB_POOL_RECYCLE', '3600')),
    'pool_size': pool_size,
    'max_overflow': int(os.environ.get('DB_MAX_OVERFLOW', '20')),
    'connect_args': {
        'charset': 'utf8mb4',
        'connect_timeout': int(os.environ.get('DB_CONNECT_TIMEOUT', '10')),
    },
    'echo': os.environ.get('SQLALCHEMY_ECHO', 'False').lower() == 'true',
}


class TestingConfig(LocalDbConfig):
    """Configuración para pruebas automáticas (MariaDB de test, sin ERP).

    Requiere ``TEST_DATABASE_URI`` en el entorno apuntando a una BD MariaDB
    separada (p.ej. ``tracking_test``) para no contaminar datos productivos.
    """
    import secrets
    TESTING = True
    SECRET_KEY = secrets.token_urlsafe(32)
    DEBUG = False
    API_SECRET = secrets.token_urlsafe(32)
    RATELIMIT_ENABLED = False
    LOGIN_RATE_LIMIT_ENABLED = False
    CSRF_ENABLED = False
    HIDE_DEMO_CREDENTIALS = True
    TRACKING_VALIDATE_OC_IN_SOFTLAND = False
    SQLALCHEMY_DATABASE_URI = (
        os.environ.get('TEST_DATABASE_URI')
        or os.environ.get('SQLALCHEMY_DATABASE_URI')
        or ''
    ).strip()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
