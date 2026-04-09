import os

import pytest

os.environ.setdefault('ENABLE_SWAGGER', 'false')


@pytest.fixture
def app():
    from app import create_app
    from config import TestingConfig
    from utils.errors import APIError

    application = create_app(TestingConfig)

    @application.route('/__pytest__/boom_html')
    def _boom_html():
        raise RuntimeError('pytest intentional server error')

    @application.route('/api/__pytest__/boom_json')
    def _boom_json():
        raise RuntimeError('pytest intentional api error')

    @application.route('/api/__pytest__/api_error')
    def _api_error():
        raise APIError('solicitud inválida', status_code=422, payload={'campo': 'x'})

    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def api_headers(app):
    secret = app.config['API_SECRET']
    return {'Authorization': f'Bearer {secret}', 'Content-Type': 'application/json'}


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield app
