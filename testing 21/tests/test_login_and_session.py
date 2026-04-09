"""Flujo de sesión y login con BD local mockeada."""
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from utils.auth import hash_password


def _login_user_row(usuario='tuser', rol_nombre='BODEGA', password_plain='secret123'):
    h = hash_password(password_plain)
    return (99, usuario, 'Nombre Prueba', rol_nombre, 'n@test.local', h, 1)


@patch('routes.frontend_routes.DatabaseConnection.get_connection')
def test_login_post_success_sets_session(mock_gc, client):
    row = _login_user_row()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = row
    mock_gc.return_value = mock_conn

    rv = client.post(
        '/login',
        data={'usuario': 'tuser', 'password': 'secret123'},
        follow_redirects=False,
    )
    assert rv.status_code == 302
    loc = rv.headers.get('Location', '')
    path = urlparse(loc).path or '/'
    assert path == '/' or path.endswith('/')

    with client.session_transaction() as sess:
        assert sess.get('user_id') == 99
        assert sess.get('username') == 'tuser'
        assert sess.get('rol') == 'BODEGA'


@patch('routes.frontend_routes.DatabaseConnection.get_connection')
def test_login_post_wrong_password(mock_gc, client):
    row = _login_user_row(password_plain='other')
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = row
    mock_gc.return_value = mock_conn

    rv = client.post(
        '/login',
        data={'usuario': 'tuser', 'password': 'wrongpass99'},
        follow_redirects=False,
    )
    assert rv.status_code == 200
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_superadmin_route_redirects_unauthenticated(client):
    rv = client.get('/superadmin/usuarios', follow_redirects=False)
    assert rv.status_code == 302
    assert 'login' in (rv.headers.get('Location') or '').lower()


def test_superadmin_forbidden_for_bodega_session(client):
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['rol'] = 'BODEGA'
        sess['username'] = 'bodega1'

    rv = client.get('/superadmin/usuarios', follow_redirects=False)
    assert rv.status_code == 302
    loc = rv.headers.get('Location', '')
    assert 'login' not in loc.lower()


@patch('routes.frontend_routes._fetch_softland_centros_costo_opciones', return_value=[])
@patch('routes.frontend_routes.DatabaseConnection.get_connection')
def test_superadmin_usuarios_get_renders(mock_gc, _mock_cc, client):
    row = _login_user_row(rol_nombre='SUPERADMIN')
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = row
    mock_gc.return_value = mock_conn

    client.post('/login', data={'usuario': 'tuser', 'password': 'secret123'})

    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []

    rv = client.get('/superadmin/usuarios', follow_redirects=False)
    assert rv.status_code == 200
