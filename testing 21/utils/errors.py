import logging
from datetime import datetime

from flask import jsonify, render_template, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Excepción base para devolver errores JSON estructurados al cliente."""
    def __init__(self, message, status_code=400, payload=None):
        super().__init__()
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['status'] = 'error'
        rv['mensaje'] = self.message
        return rv

def register_error_handlers(app):
    """Registra los manejadores de errores en la app Flask"""
    @app.errorhandler(APIError)
    def handle_api_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error.get_response(request.environ)

        logger.exception("Error no controlado: %s", error)

        payload = {
            "status": "error",
            "mensaje": "Error interno del servidor",
        }
        if app.config.get("DEBUG", False):
            payload["detalles"] = str(error)

        path = request.path or ""
        accept = (request.headers.get("Accept") or "").lower()
        wants_json = path.startswith("/api/") or "application/json" in accept

        if wants_json:
            return jsonify(payload), 500

        try:
            return (
                render_template(
                    "error.html",
                    mensaje="Ha ocurrido un error inesperado. Intente más tarde o contacte al administrador.",
                    error_code=500,
                    timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
                500,
            )
        except Exception:
            return jsonify(payload), 500
