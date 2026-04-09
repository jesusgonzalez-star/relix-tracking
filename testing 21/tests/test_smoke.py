def test_create_app_registers_blueprints(app):
    names = {bp.name for bp in app.blueprints.values()}
    assert 'frontend' in names
    assert 'tracking' in names
    assert 'softland' in names


def test_login_page_ok(client):
    r = client.get('/login')
    assert r.status_code == 200


def test_root_redirects_unauthenticated(client):
    r = client.get('/', follow_redirects=False)
    assert r.status_code in (302, 303)
    assert '/login' in (r.headers.get('Location') or '')


def test_health_ok(client):
    r = client.get('/health')
    assert r.status_code == 200
    assert r.get_json().get('status') == 'ok'
