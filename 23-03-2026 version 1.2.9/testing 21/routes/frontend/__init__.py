"""
Blueprint *frontend* – paquete modular.

Antes vivía en un solo archivo de ~7 300 líneas (``frontend_routes.py``).
Ahora cada dominio tiene su propio módulo; todos registran rutas sobre
el mismo Blueprint ``bp`` para que los ``url_for('frontend.xxx')``
existentes en templates y código sigan funcionando sin cambios.
"""

from flask import Blueprint

bp = Blueprint('frontend', __name__)

# ── Filtros Jinja y context-processor (declarados antes de las rutas) ─
from routes.frontend._helpers import (          # noqa: E402
    _get_csrf_token,
    _filter_dash_date,
    _filter_dash_date_key,
)


@bp.app_context_processor
def _inject_csrf_token():
    return {'csrf_token': _get_csrf_token}


bp.add_app_template_filter(_filter_dash_date, 'dash_date')
bp.add_app_template_filter(_filter_dash_date_key, 'dash_date_key')

# ── Importar sub-módulos (registra las rutas sobre ``bp``) ────────────
from routes.frontend import auth_routes          # noqa: E402, F401
from routes.frontend import dashboard_routes     # noqa: E402, F401
from routes.frontend import bodega_routes        # noqa: E402, F401
from routes.frontend import faena_routes         # noqa: E402, F401
from routes.frontend import requisiciones_routes # noqa: E402, F401
from routes.frontend import admin_routes         # noqa: E402, F401
from routes.frontend import api_routes           # noqa: E402, F401

# ── Error handlers (app-wide, registrados vía blueprint) ──────────────
from routes.frontend._helpers import logger      # noqa: E402
from flask import render_template, request, session  # noqa: E402


@bp.app_errorhandler(404)
def not_found(error):
    logger.warning("404 Error: %s", request.path)
    return render_template('error.html', mensaje='Página no encontrada'), 404


@bp.app_errorhandler(403)
def forbidden(error):
    logger.warning("403 Forbidden: %s - Usuario: %s", request.path, session.get('user_id'))
    return render_template('error.html', mensaje='Acceso prohibido'), 403


@bp.app_errorhandler(500)
def server_error(error):
    logger.error("500 Error: %s", error, exc_info=True)
    return render_template('error.html', mensaje='Error interno del servidor'), 500
