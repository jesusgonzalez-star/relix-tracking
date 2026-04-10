import os
import logging
from flask import Flask, jsonify
from flasgger import Swagger

from config import LocalDbConfig, validate_production_secrets
from extensions import db, ma, limiter
from utils.errors import register_error_handlers
from routes import softland_routes, tracking_routes, frontend_routes

# Configurar Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def create_app(config_class=LocalDbConfig):
    """Factory method para crear e inicializar la aplicación Flask bajo Arquitectura Limpia"""
    app = Flask(__name__)
    
    # Cargar configuraciones
    app.config.from_object(config_class)
    validate_production_secrets(app)

    if app.config.get('DEBUG') and not (app.config.get('API_SECRET') or '').strip():
        app.logger.warning(
            'API_SECRET no definido: /api/softland y /api/tracking aceptan peticiones sin clave '
            'solo en DEBUG. Para Linux/producción use DEBUG=False y defina API_SECRET.'
        )

    # Configuraciones de Sesión (necesarias para el Frontend)
    app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', 'False') == 'True'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    
    # Configuración de Flasgger (Swagger)
    app.config['SWAGGER'] = {
        'title': 'API de Tracking Logístico (Clean Architecture)',
        'uiversion': 3,
        'description': 'API automatizada que interactúa con el ERP Softland (Sólo Lectura) y un gestor de estados de despacho local.'
    }
    
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
    app.register_blueprint(frontend_routes.bp) # Monta la GUI en /

    if app.config.get('RATELIMIT_ENABLED', True):
        rl = app.config.get('RATELIMIT_API', '60 per minute')
        limiter.limit(rl)(softland_routes.bp)
        limiter.limit(rl)(tracking_routes.bp)

    @app.after_request
    def _no_cache_html_responses(response):
        """Evita que el navegador o un proxy sirvan HTML del panel desactualizado."""
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
        # Crea la nueva tabla independiente de Softland (DespachoTracking_v2)
        db.create_all()

    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug_mode = os.environ.get('DEBUG', 'False').lower() == 'true'
    
    app = create_app()
    app.run(debug=debug_mode, port=port, host='0.0.0.0') 
    