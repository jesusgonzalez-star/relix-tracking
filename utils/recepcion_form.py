"""Token de un solo uso por sesión para formularios de recepción faena (anti reenvío / doble clic)."""
from __future__ import annotations

import hmac
import secrets


def _session_key(envio_id: int) -> str:
    return f'rec_form_{int(envio_id)}'


def _touch_session(session) -> None:
    if hasattr(session, 'modified'):
        session.modified = True


def mint_recepcion_form_token(session, envio_id: int) -> str:
    token = secrets.token_urlsafe(32)
    session[_session_key(envio_id)] = token
    _touch_session(session)
    return token


def verify_recepcion_form_token(session, envio_id: int, submitted: str | None) -> bool:
    expected = session.get(_session_key(envio_id))
    got = (submitted or '').strip()
    if not expected or not got:
        return False
    return hmac.compare_digest(expected.encode('utf-8'), got.encode('utf-8'))


def consume_recepcion_form_token(session, envio_id: int) -> None:
    session.pop(_session_key(envio_id), None)
    _touch_session(session)
