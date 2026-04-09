"""Tests unitarios estrictos de helpers puros en frontend_routes (sin BD)."""
from datetime import date
from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from routes.frontend_routes import (
    _canonical_session_role,
    _canonical_tracking_state,
    _erp_scopes_softland_by_aux,
    _extract_folio_from_evidence_filename,
    _normalize_cc_assignments,
    _normalize_state_value,
    _parse_iso_date,
    _sanitize_next_url,
    _state_in,
    allowed_file,
)


@pytest.mark.parametrize(
    'raw,expected',
    [
        ('', None),
        ('   ', None),
        ('2024-01-15', date(2024, 1, 15)),
        ('2024-13-01', None),
        ('nope', None),
        ('2024-1-05', None),
    ],
)
def test_parse_iso_date(raw, expected):
    assert _parse_iso_date(raw) == expected


@pytest.mark.parametrize(
    'val,expected',
    [
        ('', ''),
        ('  a  b  ', 'A B'),
        ('EN___BODEGA', 'EN BODEGA'),
        ('en bodega', 'EN BODEGA'),
    ],
)
def test_normalize_state_value(val, expected):
    assert _normalize_state_value(val) == expected


@pytest.mark.parametrize(
    'state,normalized_key',
    [
        ('INGRESADO', 'INGRESADO'),
        ('en bodega', 'EN_BODEGA'),
        ('EN RUTA', 'En Ruta'),
        ('desconocido', 'desconocido'),
    ],
)
def test_canonical_tracking_state(state, normalized_key):
    assert _canonical_tracking_state(state) == normalized_key


@pytest.mark.parametrize(
    'state,accepted,ok',
    [
        ('EN RUTA', ['En Ruta'], True),
        ('en_ruta', ['En Ruta'], True),
        ('Entregado', ['En Ruta'], False),
        ('', ['X'], False),
    ],
)
def test_state_in(state, accepted, ok):
    assert _state_in(state, accepted) is ok


@pytest.mark.parametrize(
    'role_name,expected',
    [
        ('ADMIN', 'SUPERADMIN'),
        ('SUPERADMIN', 'SUPERADMIN'),
        ('BODEGA', 'BODEGA'),
        ('TRANSPORTISTA', 'FAENA'),
        ('CLIENTE', 'VISUALIZADOR'),
        ('  custom  ', 'CUSTOM'),
    ],
)
def test_canonical_session_role(role_name, expected):
    assert _canonical_session_role(role_name) == expected


@pytest.mark.parametrize(
    'raw,expected',
    [
        ('', []),
        ('a,b', ['A', 'B']),
        ('a;A;;b', ['A', 'B']),
        ('  x  , x ', ['X']),
    ],
)
def test_normalize_cc_assignments(raw, expected):
    assert _normalize_cc_assignments(raw) == expected


@pytest.mark.parametrize(
    'role,scoped',
    [
        ('SUPERADMIN', False),
        ('ADMIN', False),
        ('VISUALIZADOR', True),
        ('BODEGA', False),
    ],
)
def test_erp_scopes_softland_by_aux(role, scoped):
    assert _erp_scopes_softland_by_aux(role) is scoped


@pytest.mark.parametrize(
    'next_url,expected',
    [
        ('', ''),
        ('/panel', '/panel'),
        ('/path?a=1&next=/x', '/path?a=1'),
        ('http://evil.com/x', ''),
        ('//evil.com', ''),
        ('javascript:alert(1)', ''),
    ],
)
def test_sanitize_next_url(next_url, expected):
    out = _sanitize_next_url(next_url)
    assert out == expected
    if out:
        assert 'next=' not in out.lower()


@pytest.mark.parametrize(
    'name,folio',
    [
        ('despacho_12345_foo.jpg', 12345),
        ('ENTREGA_9_x.png', 9),
        ('bad.jpg', None),
        ('', None),
    ],
)
def test_extract_folio_from_evidence_filename(name, folio):
    assert _extract_folio_from_evidence_filename(name) == folio


@pytest.mark.parametrize(
    'filename,mimetype,ok',
    [
        ('f.png', 'image/png', True),
        ('x.JPEG', '', True),
        ('noext', 'image/jpeg', True),
        ('x.exe', 'application/octet-stream', False),
        ('', 'text/plain', False),
    ],
)
def test_allowed_file(filename, mimetype, ok):
    stream = BytesIO(b'\x89PNG\r\n\x1a\n' if 'png' in (filename or '').lower() else b' ')
    fs = FileStorage(stream=stream, filename=filename or '', content_type=mimetype)
    assert allowed_file(fs) is ok
