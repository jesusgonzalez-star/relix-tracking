import os
import logging
import warnings
from datetime import datetime, date
from flask import Flask, jsonify, request, abort
from flask_cors import CORS
from flasgger import Swagger
from werkzeug.middleware.proxy_fix import ProxyFix

from config import LocalDbConfig, validate_production_secrets
from extensions import db, ma, limiter
from models.tracking import DespachoTracking, User, Role  # noqa: F401 - ensure tables are registered
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
# Estrategia: siempre stdout (capturado por systemd/journald en prod, visible en dev).
# Si LOG_DIR existe y es escribible, añadir también RotatingFileHandler para archivo
# rotado en disco (10 MB x 10 archivos = 100 MB techo). Aditivo, no bloquea si falla.
_log_handlers = [logging.StreamHandler()]
_log_dir = os.environ.get('LOG_DIR', '/var/log/tracking')
try:
    if os.path.isdir(_log_dir) and os.access(_log_dir, os.W_OK):
        from logging.handlers import RotatingFileHandler
        _file_handler = RotatingFileHandler(
            os.path.join(_log_dir, 'app.log'),
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=10,              # 10 archivos rotados = 100 MB techo
            encoding='utf-8',
        )
        _log_handlers.append(_file_handler)
except Exception:
    # No bloquear arranque si el handler de archivo falla (permisos, disco, etc.)
    pass

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=_log_handlers,
)

def create_app(config_class=LocalDbConfig):
    """Factory method para crear e inicializar la aplicación Flask bajo Arquitectura Limpia"""
    app = Flask(__name__)

    # Cargar configuraciones
    app.config.from_object(config_class)

    # Middleware dev-only: fuerza SERVER_NAME=localhost para que Werkzeug no
    # valide HTTP_HOST al acceder vía IP de red (p.ej. 192.168.x.x). No debe
    # aplicarse en producción: Apache es quien valida el Host header.
    if app.config.get('DEBUG'):
        class _ForceLocalhostWSGI:
            def __init__(self, wsgi_app):
                self.wsgi_app = wsgi_app

            def __call__(self, environ, start_response):
                environ['SERVER_NAME'] = 'localhost'
                environ['SERVER_PORT'] = str(environ.get('SERVER_PORT', 5000))
                return self.wsgi_app(environ, start_response)

        app.wsgi_app = _ForceLocalhostWSGI(app.wsgi_app)

    # Soporte reverse proxy (Apache/Nginx): confía en X-Forwarded-For/Proto.
    # En desarrollo, nunca usar ProxyFix para evitar problemas con IPs locales.
    if os.environ.get('BEHIND_PROXY', 'False').lower() == 'true':
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    validate_production_secrets(app)

    default_secret = 'default-secret-key-123'
    if (not app.config.get('DEBUG')) and app.config.get('SECRET_KEY') == default_secret:
        raise RuntimeError(
            '🔴 CRÍTICO: SECRET_KEY sigue siendo el valor por defecto. '
            'Debes definir SECRET_KEY en variables de entorno ANTES de desplegar en producción. '
            'Ejemplo: export SECRET_KEY="$(python3 -c \'import secrets; print(secrets.token_hex(32))\')"\n'
            'O usar: openssl rand -hex 32'
        )

    if app.config.get('DEBUG') and not (app.config.get('API_SECRET') or '').strip():
        app.logger.warning(
            'API_SECRET no definido: /api/softland y /api/tracking aceptan peticiones sin clave '
            'solo en DEBUG. Para Linux/producción use DEBUG=False y defina API_SECRET.'
        )

    # Configuraciones de Sesión (necesarias para el Frontend)
    # En producción (no DEBUG) activar Secure por defecto; en dev mantener False.
    _cookie_secure_default = 'false' if app.config.get('DEBUG') else 'true'
    app.config['SESSION_COOKIE_SECURE'] = (
        os.environ.get('SESSION_COOKIE_SECURE', _cookie_secure_default).strip().lower() == 'true'
    )
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Configuración de Flasgger (Swagger)
    app.config['SWAGGER'] = {
        'title': 'API de Tracking Logístico (Clean Architecture)',
        'uiversion': 3,
        'description': 'API automatizada que interactúa con el ERP Softland (Sólo Lectura) y un gestor de estados de despacho local.'
    }
    
    # Log de diagnóstico: URI de conexión a la base local (oculta password)
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri:
        import re as _re
        safe_uri = _re.sub(r'(://[^:/@]+:)[^@]*(@)', r'\1***\2', db_uri)
        app.logger.info('Base de datos local: %s', safe_uri)

    # Inicializar Extensiones
    db.init_app(app)
    ma.init_app(app)
    limiter.init_app(app)

    # CORS: proteger API endpoints
    allowed_origins = os.environ.get('CORS_ALLOWED_ORIGINS', 'http://localhost:5000').split(',')

    # Validación de seguridad: no permitir wildcard con credentials
    if '*' in allowed_origins or any(origin.strip() == '*' for origin in allowed_origins):
        app.logger.warning('⚠️ CORS: Wildcard origin detectado. NUNCA usar * con credentials=True')
        if not app.config.get('TESTING'):
            raise ValueError('CORS wildcard origin no permitido en aplicación: use dominios específicos')

    CORS(app,
         resources={r"/api/*": {"origins": allowed_origins, "supports_credentials": True}},
         allow_headers=['Content-Type', 'Authorization', 'X-API-Key']
    )

    # Swagger deshabilitado por defecto en producción (information disclosure)
    if os.environ.get('ENABLE_SWAGGER', 'False').lower() == 'true':
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

    # Rate limit para login/registro: aplicado por decorador directamente en
    # auth_routes.py (login ya tiene @limiter.limit).  NO se aplica al
    # blueprint frontend completo para evitar bloquear navegación normal.

    # Validación ALLOWED_HOSTS (Host Header attack protection).
    # Opt-in: se activa si ALLOWED_HOSTS está definido. En producción sin
    # ALLOWED_HOSTS se emite un WARN pero NO se bloquea el arranque (para no
    # romper despliegues que ya dependen de la protección de Apache).
    _allowed_hosts_raw = os.environ.get('ALLOWED_HOSTS', '').strip()
    _allowed_hosts = {h.strip().lower() for h in _allowed_hosts_raw.split(',') if h.strip()}
    if _allowed_hosts and not app.config.get('DEBUG'):
        @app.before_request
        def _validate_host_header():
            host = (request.host or '').split(':')[0].lower()
            if host and host not in _allowed_hosts:
                app.logger.warning('Host header rechazado: %s', host)
                abort(400)
    elif not app.config.get('DEBUG') and not app.config.get('TESTING'):
        app.logger.warning(
            'ALLOWED_HOSTS no definido en producción: sin protección a nivel app '
            'contra Host header injection. Configure ALLOWED_HOSTS en /etc/tracking-app/env '
            '(ej: "tracking.empresa.cl") o asegúrese de que Apache valide ServerName.'
        )

    # Aviso: rate limiter en memoria con múltiples workers no coordina contadores.
    _rl_storage = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    _workers = int(os.environ.get('WORKERS', '1') or '1')
    if _rl_storage.startswith('memory://') and _workers > 1 and not app.config.get('DEBUG'):
        app.logger.warning(
            'RATELIMIT_STORAGE_URI=memory:// con WORKERS=%s: los contadores de rate limit '
            'no se coordinan entre workers. Use redis:// para producción multi-worker.',
            _workers,
        )

    # Validación global de Content-Type para endpoints API
    @app.before_request
    def _validate_api_content_type():
        """Valida Content-Type para todas las peticiones POST/PUT/PATCH a /api/*"""
        if request.method in ('POST', 'PUT', 'PATCH'):
            if request.path.startswith('/api/'):
                if not request.is_json:
                    app.logger.warning('Invalid Content-Type for %s %s: %s',
                                     request.method, request.path, request.content_type)
                    abort(415)  # Unsupported Media Type

    @app.after_request
    def _security_and_cache_headers(response):
        """Headers específicos de la aplicación.

        Los headers HTTP genéricos (X-Frame-Options, X-Content-Type-Options,
        Referrer-Policy, HSTS, Permissions-Policy) los gestiona Apache en
        deploy/apache-tracking.conf para evitar duplicados. Aquí sólo quedan
        los que varían por endpoint/MIME: CSP y Cache-Control.

        En desarrollo (sin Apache delante) los headers HTTP no se emiten: es
        responsabilidad del dev no exponer el server local a internet.
        """
        if not app.config.get('DEBUG'):
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data:; "
                "font-src 'self' https://cdn.jsdelivr.net; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'; "
                "form-action 'self'"
            )

        # ── Cache inteligente por Content-Type ──
        ct = (response.headers.get('Content-Type') or '').lower()
        if 'text/html' in ct or 'application/json' in ct:
            # HTML + JSON: sin cache (panel + API)
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
        elif any(static in ct for static in ['image/', 'font/', 'application/javascript', 'text/css']):
            # Assets estáticos: cache agresivo (30 días)
            response.headers['Cache-Control'] = 'public, max-age=2592000, immutable'
        return response

    @app.route('/health')
    def health():
        """Comprobación para balanceadores: SOLO verifica MariaDB local.

        Softland se consulta bajo demanda y puede estar caído sin tumbar el panel,
        por eso NO se incluye aquí: si Softland falla, el health debe seguir 200
        (Apache no debe dar 502 por un ERP externo).
        """
        from sqlalchemy import text
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify({'status': 'ok', 'database': 'mariadb-ok'}), 200
        except Exception as e:
            app.logger.warning('Health check: MariaDB error: %s', e)
            return jsonify({'status': 'error', 'database': 'mariadb-down'}), 503

    @app.route('/status')
    def status():
        """Status endpoint para monitoreo: estado de BD local y Softland.

        A diferencia de /health, este sí reporta el estado del ERP, pero nunca
        devuelve 5xx solo porque Softland esté caído.
        """
        from sqlalchemy import text
        mariadb_status = 'ok'
        try:
            db.session.execute(text('SELECT 1'))
        except Exception:
            mariadb_status = 'error'

        softland_status = 'unknown'
        try:
            from services.softland_service import SoftlandService
            conn_sl = SoftlandService.get_connection()
            try:
                cur = conn_sl.cursor()
                cur.execute('SELECT 1')
                cur.close()
                softland_status = 'ok'
            finally:
                conn_sl.close()
        except Exception:
            softland_status = 'error'

        return jsonify({
            'status': 'ok' if mariadb_status == 'ok' else 'error',
            'mariadb': mariadb_status,
            'softland': softland_status,
            'debug_mode': app.config.get('DEBUG'),
            'timestamp': datetime.now().isoformat(),
        }), 200 if mariadb_status == 'ok' else 503

    @app.route('/test-direct')
    def test_direct():
        """Ruta de diagnóstico. Solo disponible con DEBUG=True (404 en producción)."""
        if not app.config.get('DEBUG'):
            abort(404)
        return jsonify({
            'message': 'Test OK',
            'host': request.host,
            'remote_addr': request.remote_addr,
            'http_host': request.headers.get('Host')
        }), 200

    # ── Filtro Jinja2 para fechas ──
    @app.template_filter('datefmt')
    def _datefmt_filter(value, fmt='%d-%m-%Y %H:%M'):
        """Formatea fecha: acepta datetime, date, str ISO o None."""
        if value is None:
            return ''
        if isinstance(value, datetime):
            return value.strftime(fmt)
        if isinstance(value, date):
            return value.strftime(fmt)
        s = str(value).strip()
        if not s:
            return ''
        for pattern in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return datetime.strptime(s, pattern).strftime(fmt)
            except ValueError:
                continue
        return s  # Devolver el string tal cual si no se puede parsear

    # Crear tablas locales si no existen según SQLAlchemy
    with app.app_context():
        app.logger.info('Inicializando tablas locales desde modelos SQLAlchemy')

        # Tablas locales según modelos SQLAlchemy (p. ej. DespachosTracking para API + panel).
        db.create_all()

    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'

    app = create_app()

    # Usar app.run SIN debugger para evitar bug de Werkzeug 3.1.x con IPs de red
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,  # DESACTIVAR debugger de Werkzeug
        use_reloader=debug_mode,
        threaded=True
    ) 
    