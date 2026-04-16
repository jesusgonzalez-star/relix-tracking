import os
import re
import urllib.parse
from dotenv import load_dotenv

load_dotenv()


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


def validate_production_secrets(app):
    """
    En producción (DEBUG=False y no modo TESTING), exige SECRET_KEY, API_SECRET y DB_PASS
    definidas en el entorno. Si falta alguna, no arranca.
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
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))
    EVIDENCE_UPLOAD_DIR = os.environ.get(
        'EVIDENCE_UPLOAD_DIR',
        os.path.join(BASE_DIR, 'storage', 'evidencias')
    )
    # Límite por IP en blueprints /api/softland y /api/tracking (memoria; con varios workers use Redis).
    RATELIMIT_ENABLED = os.environ.get('RATELIMIT_ENABLED', 'True').lower() == 'true'
    RATELIMIT_API = os.environ.get('RATELIMIT_API', '60 per minute')
    # Endurecimientos graduales (compatibles, apagados por defecto).
    LOGIN_RATE_LIMIT_ENABLED = os.environ.get('LOGIN_RATE_LIMIT_ENABLED', 'True').lower() == 'true'
    RATELIMIT_LOGIN = os.environ.get('RATELIMIT_LOGIN', '10 per minute')
    CSRF_ENABLED = os.environ.get('CSRF_ENABLED', 'True').lower() == 'true'
    HIDE_DEMO_CREDENTIALS = os.environ.get('HIDE_DEMO_CREDENTIALS', 'True').lower() == 'true'
    # Si True, POST /api/tracking exige que la OC exista en Softland.
    TRACKING_VALIDATE_OC_IN_SOFTLAND = (
        os.environ.get('TRACKING_VALIDATE_OC_IN_SOFTLAND', 'False').lower() == 'true'
    )

class SoftlandConfig(Config):
    """
    ERP Softland (solo lectura en aplicación).
    Credenciales solo por entorno; DB_PASS sin default (obligatoria si DEBUG=False al arrancar).
    Para ODBC Driver 18 (Linux/Ubuntu): configura Encrypt y TrustServerCertificate via entorno.
    """
    DB_SERVER = os.environ.get('DB_SERVER', r'RELIX-SQL01\SOFTLAND')
    DB_NAME = os.environ.get('DB_NAME', 'ZDESARROLLO')
    DB_USER = os.environ.get('DB_USER', 'JGonzalez')
    DB_PASS = (os.environ.get('DB_PASS') or '').strip()
    DB_DRIVER = os.environ.get('DB_DRIVER', 'ODBC Driver 17 for SQL Server')
    DB_TIMEOUT = int(os.environ.get('SOFTLAND_TIMEOUT', 15))
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
    """Base local (tracking / usuarios): SQLite en Linux para independencia total del SQL Server.
    El archivo .db se crea automáticamente al iniciar la app.
    """

    LOCAL_DB_PATH = os.environ.get(
        'LOCAL_DB_PATH', '/opt/tracking-app/tracking.db'
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    @classmethod
    def build_sqlalchemy_uri(cls) -> str:
        """URI para Flask-SQLAlchemy usando SQLite local."""
        return f'sqlite:///{cls.LOCAL_DB_PATH}'


LocalDbConfig.SQLALCHEMY_DATABASE_URI = os.environ.get(
    'SQLALCHEMY_DATABASE_URI'
) or LocalDbConfig.build_sqlalchemy_uri()


class TestingConfig(LocalDbConfig):
    """Configuración para pruebas automáticas (SQLite en memoria, sin ERP)."""
    TESTING = True
    SECRET_KEY = 'pytest-secret-key'
    DEBUG = False
    API_SECRET = 'pytest-api-secret'
    RATELIMIT_ENABLED = False
    LOGIN_RATE_LIMIT_ENABLED = False
    CSRF_ENABLED = False
    HIDE_DEMO_CREDENTIALS = True
    TRACKING_VALIDATE_OC_IN_SOFTLAND = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
