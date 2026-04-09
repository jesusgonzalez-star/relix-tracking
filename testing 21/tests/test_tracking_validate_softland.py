from unittest.mock import patch

from utils.errors import APIError


def test_tracking_post_validates_oc_when_flag_enabled(client, app, api_headers):
    app.config['TRACKING_VALIDATE_OC_IN_SOFTLAND'] = True
    with patch('routes.tracking_routes.SoftlandService.obtener_detalle_oc') as m:
        m.side_effect = APIError('OC no existe', status_code=404)
        r = client.post(
            '/api/tracking/',
            json={'num_oc': 777, 'estado': 'BODEGA'},
            headers=api_headers,
        )
        assert r.status_code == 404
        assert r.get_json().get('status') == 'error'


def test_tracking_post_skips_softland_when_flag_disabled(client, api_headers):
    with patch('routes.tracking_routes.SoftlandService.obtener_detalle_oc') as m:
        r = client.post(
            '/api/tracking/',
            json={'num_oc': 88888, 'estado': 'BODEGA'},
            headers=api_headers,
        )
        assert r.status_code == 201
        m.assert_not_called()
