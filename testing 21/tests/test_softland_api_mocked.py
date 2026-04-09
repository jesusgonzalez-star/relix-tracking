from unittest.mock import patch

from utils.errors import APIError


@patch('routes.softland_routes.SoftlandService.obtener_detalle_oc')
def test_softland_oc_ok(mock_detalle, client, api_headers):
    mock_detalle.return_value = {
        'folio': 100,
        'proveedor': 'Prov SA',
        'fecha_emision': '2024-06-01',
        'guia_entrada': True,
        'productos': [{'codigo': 'X', 'descripcion': 'Y', 'cantidad': 1}],
    }
    r = client.get('/api/softland/oc/100', headers=api_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert body['folio'] == 100
    assert body['proveedor'] == 'Prov SA'
    assert body['guia_entrada'] is True
    assert isinstance(body['productos'], list)
    mock_detalle.assert_called_once_with(100)


@patch('routes.softland_routes.SoftlandService.obtener_detalle_oc')
def test_softland_oc_api_error_404(mock_detalle, client, api_headers):
    mock_detalle.side_effect = APIError('OC no existe', status_code=404)
    r = client.get('/api/softland/oc/999999', headers=api_headers)
    assert r.status_code == 404
    assert r.get_json()['status'] == 'error'
    assert 'no existe' in r.get_json()['mensaje'].lower() or 'OC' in r.get_json()['mensaje']


@patch('routes.softland_routes.SoftlandService.obtener_detalle_oc')
def test_softland_oc_api_error_503(mock_detalle, client, api_headers):
    mock_detalle.side_effect = APIError('ERP caído', status_code=503)
    r = client.get('/api/softland/oc/1', headers=api_headers)
    assert r.status_code == 503
    assert r.get_json()['status'] == 'error'
