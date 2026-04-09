def test_404_not_treated_as_500(client):
    r = client.get('/ruta-que-no-existe-nunca-xyz')
    assert r.status_code == 404


def test_unexpected_error_html_for_browser(client):
    r = client.get('/__pytest__/boom_html')
    assert r.status_code == 500
    ct = (r.headers.get('Content-Type') or '').lower()
    assert 'text/html' in ct


def test_unexpected_error_json_for_api_path(client):
    r = client.get('/api/__pytest__/boom_json')
    assert r.status_code == 500
    data = r.get_json()
    assert data['status'] == 'error'
    assert 'mensaje' in data


def test_unexpected_error_json_with_accept_header(client):
    r = client.get(
        '/__pytest__/boom_html',
        headers={'Accept': 'application/json'},
    )
    assert r.status_code == 500
    assert r.get_json()['status'] == 'error'


def test_api_error_handler(client):
    r = client.get('/api/__pytest__/api_error')
    assert r.status_code == 422
    body = r.get_json()
    assert body['status'] == 'error'
    assert body['mensaje'] == 'solicitud inválida'
