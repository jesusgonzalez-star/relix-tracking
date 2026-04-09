"""Tests de autorización y respuesta de /api/estado_orden (conexiones mockeadas)."""
from unittest.mock import MagicMock, patch

from utils.errors import APIError


def _session_client(client, *, user_id=1, rol='SUPERADMIN'):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id
        sess['rol'] = rol
    return client


@patch('routes.frontend_routes.DatabaseConnection.get_connection')
def test_estado_orden_superadmin_404_when_no_row(mock_get_db, client):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_get_db.return_value = mock_conn
    mock_conn.cursor.return_value = mock_cur
    mock_cur.fetchone.return_value = None

    c = _session_client(client, rol='SUPERADMIN')
    r = c.get('/api/estado_orden/999999')
    assert r.status_code == 404
    assert 'no encontrada' in (r.get_json().get('error') or '').lower()


@patch('services.softland_service.SoftlandService.get_connection')
@patch('routes.frontend_routes.DatabaseConnection.get_connection')
def test_estado_orden_visualizador_403_when_aux_not_in_oc(mock_get_db, mock_get_sl, client):
    mock_db = MagicMock()
    mock_db_cur = MagicMock()
    mock_get_db.return_value = mock_db
    mock_db.cursor.return_value = mock_db_cur
    mock_db_cur.fetchone.return_value = ('CODAUX99',)

    mock_sl = MagicMock()
    mock_sl_cur = MagicMock()
    mock_get_sl.return_value = mock_sl
    mock_sl.cursor.return_value = mock_sl_cur
    mock_sl_cur.fetchone.return_value = None

    c = _session_client(client, user_id=5, rol='VISUALIZADOR')
    r = c.get('/api/estado_orden/1001')
    assert r.status_code == 403


@patch('services.softland_service.SoftlandService.get_connection')
@patch('routes.frontend_routes.DatabaseConnection.get_connection')
def test_estado_orden_visualizador_200_when_aux_matches(mock_get_db, mock_get_sl, client):
    mock_db = MagicMock()
    mock_db_cur = MagicMock()
    mock_get_db.return_value = mock_db
    mock_db.cursor.return_value = mock_db_cur
    mock_db_cur.fetchone.side_effect = [
        ('CODAUX1',),
        (
            2001,
            'Proveedor SA',
            'Solicitante',
            'Producto X',
            'EN_BODEGA',
            None,
            None,
            None,
            'Trans',
            'G-1',
            'PENDIENTE',
        ),
    ]

    mock_sl = MagicMock()
    mock_sl_cur = MagicMock()
    mock_get_sl.return_value = mock_sl
    mock_sl.cursor.return_value = mock_sl_cur
    mock_sl_cur.fetchone.return_value = (1,)

    c = _session_client(client, user_id=5, rol='VISUALIZADOR')
    r = c.get('/api/estado_orden/2001')
    assert r.status_code == 200
    body = r.get_json()
    assert body['folio'] == 2001
    assert body['proveedor'] == 'Proveedor SA'
