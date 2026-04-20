import secrets

from flask import current_app, jsonify, request


def _token_from_request():
    auth = request.headers.get('Authorization') or ''
    lowered = auth.lower()
    if lowered.startswith('bearer '):
        return auth[7:].strip()
    return (request.headers.get('X-API-Key') or '').strip()


def enforce_api_secret_before_request():
    """
    Protege /api/softland y /api/tracking.

    - API_SECRET definido: exige Bearer o X-API-Key (compare_digest).
    - Sin API_SECRET: SIEMPRE 401 (incluso en DEBUG mode por seguridad).
    - TESTING: genera SECRET_KEY dinámico en TestingConfig.
    """
    expected = (current_app.config.get('API_SECRET') or '').strip()
    testing = current_app.config.get('TESTING', False)

    if not expected:
        if testing:
            return (
                jsonify(
                    {
                        'status': 'error',
                        'mensaje': 'API_SECRET no configurado: corrija TestingConfig.',
                    }
                ),
                500,
            )
        # NUNCA permitir API sin autenticación, incluso en DEBUG mode
        return (
            jsonify(
                {
                    'status': 'error',
                    'mensaje': (
                        'API_SECRET no configurado. Defina la variable en el entorno '
                        '(Apache SetEnv, systemd Environment=, .env, etc.).'
                    ),
                }
            ),
            401,
        )

    got = _token_from_request()
    # Soporta rotación: API_SECRET_OLD acepta el secreto anterior durante transición.
    old_secret = (current_app.config.get('API_SECRET_OLD') or '').strip()
    valid = bool(got) and (
        secrets.compare_digest(got, expected)
        or (old_secret and secrets.compare_digest(got, old_secret))
    )
    if not valid:
        return (
            jsonify(
                {
                    'status': 'error',
                    'mensaje': (
                        'No autorizado: use Authorization: Bearer <token> o cabecera X-API-Key.'
                    ),
                }
            ),
            401,
        )
    return None
