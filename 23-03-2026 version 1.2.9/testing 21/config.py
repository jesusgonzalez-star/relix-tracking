import os
import urllib.parse
from dotenv import load_dotenv

load_dotenv()


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
        # Para ODBC Driver 18: agregar Encrypt y TrustServerCertificate
        if 'Driver 18' in cls.DB_DRIVER:
            conn_str += f"Encrypt={cls.DB_ENCRYPT};"
            conn_str += f"TrustServerCertificate={cls.DB_TRUST_CERT};"
        return conn_str

class LocalDbConfig(Config):
    """Base local (tracking / usuarios): SQLAlchemy + pyodbc deben usar la misma cadena lógica.
    Para ODBC Driver 18 (Linux/Ubuntu): configura Encrypt y TrustServerCertificate via entorno.
    """

    LOCAL_DB_NAME = os.environ.get('LOCAL_DB_NAME', 'Softland_Mock')
    LOCAL_SERVER = os.environ.get('LOCAL_SERVER', r'5CD5173D14\SQLEXPRESS')
    DB_DRIVER = os.environ.get('LOCAL_DB_DRIVER', 'ODBC Driver 17 for SQL Server')
    # En Linux / Docker use autenticación SQL (obligatorio si no hay Kerberos):
    LOCAL_DB_USER = (os.environ.get('LOCAL_DB_USER') or '').strip()
    LOCAL_DB_PASS = (os.environ.get('LOCAL_DB_PASS') or '').strip()
    LOCAL_DB_ENCRYPT = os.environ.get('LOCAL_DB_ENCRYPT', 'no').lower()
    LOCAL_DB_TRUST_CERT = os.environ.get('LOCAL_DB_TRUST_CERT', 'yes').lower()

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    @classmethod
    def build_sqlalchemy_uri(cls) -> str:
        """URI única para Flask-SQLAlchemy (mssql+pyodbc).
        Para ODBC Driver 18, incluye Encrypt y TrustServerCertificate.
        """
        odbc_driver = urllib.parse.quote_plus(cls.DB_DRIVER)
        server = cls.LOCAL_SERVER.replace(' ', '%20')
        dbn = urllib.parse.quote_plus(cls.LOCAL_DB_NAME)

        # Parámetros base
        params = [f'driver={odbc_driver}']

        # Para ODBC Driver 18: agregar Encrypt y TrustServerCertificate
        if 'Driver 18' in cls.DB_DRIVER:
            params.append(f'Encrypt={cls.LOCAL_DB_ENCRYPT}')
            params.append(f'TrustServerCertificate={cls.LOCAL_DB_TRUST_CERT}')

        query_string = '&'.join(params)

        if cls.LOCAL_DB_USER and cls.LOCAL_DB_PASS:
            user = urllib.parse.quote_plus(cls.LOCAL_DB_USER)
            pwd = urllib.parse.quote_plus(cls.LOCAL_DB_PASS)
            return f'mssql+pyodbc://{user}:{pwd}@{server}/{dbn}?{query_string}'

        # Agregar Trusted_Connection=yes solo si no hay usuario/contraseña
        params.append('Trusted_Connection=yes')
        query_string = '&'.join(params)
        return f'mssql+pyodbc://@{server}/{dbn}?{query_string}'

    @classmethod
    def get_pyodbc_connection_string(cls) -> str:
        """
        Cadena ODBC para DatabaseConnection (panel) y herramientas que no pasan por SQLAlchemy.
        En producción Linux: defina LOCAL_DB_USER y LOCAL_DB_PASS (no use Trusted_Connection).
        Para ODBC Driver 18: incluye Encrypt y TrustServerCertificate.
        """
        base_str = (
            f'Driver={{{cls.DB_DRIVER}}};'
            f'Server={cls.LOCAL_SERVER};'
            f'Database={cls.LOCAL_DB_NAME};'
        )

        if cls.LOCAL_DB_USER and cls.LOCAL_DB_PASS:
            base_str += f'UID={cls.LOCAL_DB_USER};PWD={cls.LOCAL_DB_PASS};'
        else:
            base_str += 'Trusted_Connection=yes;'

        # Para ODBC Driver 18: agregar Encrypt y TrustServerCertificate
        if 'Driver 18' in cls.DB_DRIVER:
            base_str += f'Encrypt={cls.LOCAL_DB_ENCRYPT};'
            base_str += f'TrustServerCertificate={cls.LOCAL_DB_TRUST_CERT};'

        return base_str


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
