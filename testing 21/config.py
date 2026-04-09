import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    """Configuraciones base compartidas"""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-secret-key-123')
    DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
    # /api/softland y /api/tracking: Bearer o X-API-Key; en prod definir siempre.
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
    Las variables de entorno tienen prioridad. Los valores por defecto son solo
    para desarrollo local como el tuyo; en Linux/producción defina todo en .env
    y rote cualquier clave que haya estado en código compartido.
    """
    DB_SERVER = os.environ.get('DB_SERVER', r'RELIX-SQL01\SOFTLAND')
    DB_NAME = os.environ.get('DB_NAME', 'ZDESARROLLO')
    DB_USER = os.environ.get('DB_USER', 'JGonzalez')
    DB_PASS = os.environ.get('DB_PASS', 'Rex.Dev.852*')
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
