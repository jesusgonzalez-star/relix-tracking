import os
import logging
import warnings
from flask import Flask, jsonify
from flasgger import Swagger
from werkzeug.middleware.proxy_fix import ProxyFix

from config import LocalDbConfig, validate_production_secrets
from extensions import db, ma, limiter
from utils.errors import register_error_handlers
from routes import softland_routes, tracking_routes
from routes.frontend import bp as frontend_bp

# Suprimir el aviso de SQLAlchemy sobre la versión de SQL Server Express
# (el driver funciona correctamente; el warning es cosmético de compatibilidad)
warnings.filterwarnings(
    'ignore',
    message=r'.*Unrecognized server version info.*',
    category=Warning,
)

# Configurar Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def create_app(config_class=LocalDbConfig):
    """Factory method para crear e inicializar la aplicación Flask bajo Arquitectura Limpia"""
    app = Flask(__name__)

    # Soporte reverse proxy (Apache/Nginx): confía en X-Forwarded-For/Proto.
    # Solo aplica si hay proxy delante; en Windows dev no afecta.
    if os.environ.get('BEHIND_PROXY', 'False').lower() == 'true':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # Cargar configuraciones
    app.config.from_object(config_class)
    validate_production_secrets(app)

    default_secret = 'default-secret-key-123'
    if (not app.config.get('DEBUG')) and app.config.get('SECRET_KEY') == default_secret:
        app.logger.warning(
            'SECRET_KEY sigue siendo el valor por defecto; defina SECRET_KEY en el entorno para producción.'
        )

    if app.config.get('DEBUG') and not (app.config.get('API_SECRET') or '').strip():
        app.logger.warning(
            'API_SECRET no definido: /api/softland y /api/tracking aceptan peticiones sin clave '
            'solo en DEBUG. Para Linux/producción use DEBUG=False y defina API_SECRET.'
        )

    # Configuraciones de Sesión (necesarias para el Frontend)
    # En producción (no DEBUG) activar Secure por defecto; en dev mantener False.
    _cookie_secure_default = 'False' if app.config.get('DEBUG') else 'True'
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', _cookie_secure_default) == 'True'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Configuración de Flasgger (Swagger)
    app.config['SWAGGER'] = {
        'title': 'API de Tracking Logístico (Clean Architecture)',
        'uiversion': 3,
        'description': 'API automatizada que interactúa con el ERP Softland (Sólo Lectura) y un gestor de estados de despacho local.'
    }
    
    # Log de diagnóstico: URI de conexión local (SQLite)
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri:
        app.logger.info(f'Base de datos local (SQLite): {db_uri}')

    # Inicializar Extensiones

    db.init_app(app)
    ma.init_app(app)
    limiter.init_app(app)
    if os.environ.get('ENABLE_SWAGGER', 'True').lower() == 'true':
        Swagger(app)
    
    # Manejo de Errores Global
    register_error_handlers(app)
    
    # Registrar Blueprints
    app.register_blueprint(softland_routes.bp)
    app.register_blueprint(tracking_routes.bp)
    app.register_blueprint(frontend_bp)  # Monta la GUI en /

    if app.config.get('RATELIMIT_ENABLED', True):
        rl = app.config.get('RATELIMIT_API', '60 per minute')
        limiter.limit(rl)(softland_routes.bp)
        limiter.limit(rl)(tracking_routes.bp)

    # Rate limit específico para login/registro (protección contra fuerza bruta)
    if app.config.get('LOGIN_RATE_LIMIT_ENABLED', True):
        login_rl = app.config.get('RATELIMIT_LOGIN', '10 per minute')
        limiter.limit(login_rl)(frontend_bp)

    @app.after_request
    def _security_and_cache_headers(response):
        """Headers de seguridad estándar + no-cache para HTML del panel."""
        # ── Security headers ──
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'

        if not app.config.get('DEBUG'):
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data:; "
                "font-src 'self' https://cdn.jsdelivr.net"
            )

        # ── No-cache para HTML del panel ──
        ct = (response.headers.get('Content-Type') or '').lower()
        if 'text/html' in ct:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
        return response

    @app.route('/health')
    def health():
        """Comprobación ligera para balanceadores y arranque (sin consultar Softland)."""
        return jsonify({'status': 'ok'}), 200

    # Crear tablas locales si no existen según SQLAlchemy
    with app.app_context():
        app.logger.info(f'Base de datos local SQLite: {LocalDbConfig.LOCAL_DB_PATH}')

        # Tablas locales según modelos SQLAlchemy (p. ej. DespachosTracking para API + panel).
        db.create_all()

    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    app = create_app()
    app.run(debug=debug_mode, port=port, host='0.0.0.0') 
    