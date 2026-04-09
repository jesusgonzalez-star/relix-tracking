def test_tracking_post_and_get(client, api_headers):
    payload = {'num_oc': 91001, 'estado': 'BODEGA'}
    r = client.post('/api/tracking/', json=payload, headers=api_headers)
    assert r.status_code == 201, r.get_data(as_text=True)

    r2 = client.get('/api/tracking/oc/91001', headers=api_headers)
    assert r2.status_code == 200
    rows = r2.get_json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert rows[0]['num_oc'] == 91001


def test_tracking_validation_error(client, api_headers):
    r = client.post('/api/tracking/', json={'num_oc': 1, 'estado': 'INVALIDO'}, headers=api_headers)
    assert r.status_code == 400
    body = r.get_json()
    assert body.get('status') == 'error'
