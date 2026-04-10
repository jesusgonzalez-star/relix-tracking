from config import TestingConfig


class _StrictApiConfig(TestingConfig):
    TESTING = False
    DEBUG = False
    API_SECRET = 'secret-for-strict-test'


def test_softland_401_without_key_when_production_like():
    from app import create_app

    app = create_app(_StrictApiConfig)
    with app.test_client() as c:
        r = c.get('/api/softland/oc/1')
        assert r.status_code == 401
        assert r.get_json()['status'] == 'error'


def test_softland_401_wrong_key_when_production_like():
    from app import create_app

    app = create_app(_StrictApiConfig)
    with app.test_client() as c:
        r = c.get('/api/softland/oc/1', headers={'Authorization': 'Bearer wrong'})
        assert r.status_code == 401


def test_tracking_401_without_key_when_production_like():
    from app import create_app

    app = create_app(_StrictApiConfig)
    with app.test_client() as c:
        r = c.post('/api/tracking/', json={'num_oc': 1, 'estado': 'BODEGA'})
        assert r.status_code == 401
