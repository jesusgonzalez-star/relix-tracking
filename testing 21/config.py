import os
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
    LOGIN_RATE_LIMIT_ENABLED = os.environ.get('LOGIN_RATE_LIMIT_ENABLED', 'False').lower() == 'true'
    RATELIMIT_LOGIN = os.environ.get('RATELIMIT_LOGIN', '10 per minute')
    CSRF_ENABLED = os.environ.get('CSRF_ENABLED', 'False').lower() == 'true'
    HIDE_DEMO_CREDENTIALS = os.environ.get('HIDE_DEMO_CREDENTIALS', 'True').lower() == 'true'
    # Si True, POST /api/tracking exige que la OC exista en Softland.
    TRACKING_VALIDATE_OC_IN_SOFTLAND = (
        os.environ.get('TRACKING_VALIDATE_OC_IN_SOFTLAND', 'False').lower() == 'true'
    )

class SoftlandConfig(Config):
    """
    ERP Softland (solo lectura en aplicación).
    Credenciales solo por entorno; DB_PASS sin default (obligatoria si DEBUG=False al arrancar).
    """
    DB_SERVER = os.environ.get('DB_SERVER', r'RELIX-SQL01\SOFTLAND')
    DB_NAME = os.environ.get('DB_NAME', 'ZDESARROLLO')
    DB_USER = os.environ.get('DB_USER', 'JGonzalez')
    DB_PASS = (os.environ.get('DB_PASS') or '').strip()
    DB_DRIVER = os.environ.get('DB_DRIVER', 'ODBC Driver 17 for SQL Server')

    @classmethod
    def get_connection_string(cls):
        if not (cls.DB_SERVER and cls.DB_NAME):
            raise ValueError(
                'Softland no configurado: defina DB_SERVER y DB_NAME en el entorno o .env.'
            )
        return (
            f"Driver={{{cls.DB_DRIVER}}};"
            f"Server={cls.DB_SERVER};"
            f"Database={cls.DB_NAME};"
            f"UID={cls.DB_USER};"
            f"PWD={cls.DB_PASS};"
            f"ApplicationIntent=ReadOnly;"
        )

class LocalDbConfig(Config):
    """Configuración para la base de datos local (Tracking/Usuarios) mediante SQLAlchemy"""
    LOCAL_DB_NAME = os.environ.get('LOCAL_DB_NAME', 'Softland_Mock')
    # Ajuste LOCAL_SERVER en .env si su PC usa otra instancia (ej. nombre de equipo\SQLEXPRESS).
    LOCAL_SERVER = os.environ.get('LOCAL_SERVER', r'5CD5173D14\SQLEXPRESS')
    
    # URL compatible con flask-sqlalchemy y PyODBC
    SQLALCHEMY_DATABASE_URI = (
        f"mssql+pyodbc://@{LOCAL_SERVER}/{LOCAL_DB_NAME}?"
        f"driver=ODBC+Driver+17+for+SQL+Server&Trusted_Connection=yes"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False


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
