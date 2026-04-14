"""Token de un solo uso por sesión para formulario despacho bodega (anti reenvío / doble clic)."""
from __future__ import annotations

import hmac
import secrets


def _session_key(num_oc: int) -> str:
    return f'desp_form_{int(num_oc)}'


def _touch_session(session) -> None:
    if hasattr(session, 'modified'):
        session.modified = True


def mint_despacho_form_token(session, num_oc: int) -> str:
    token = secrets.token_urlsafe(32)
    session[_session_key(num_oc)] = token
    _touch_session(session)
    return token


def verify_despacho_form_token(session, num_oc: int, submitted: str | None) -> bool:
    expected = session.get(_session_key(num_oc))
    got = (submitted or '').strip()
    if not expected or not got:
        return False
    return hmac.compare_digest(expected.encode('utf-8'), got.encode('utf-8'))


def consume_despacho_form_token(session, num_oc: int) -> None:
    session.pop(_session_key(num_oc), None)
    _touch_session(session)
