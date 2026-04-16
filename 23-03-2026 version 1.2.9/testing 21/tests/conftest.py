"""Fixtures compartidas para la suite de tests."""

import pytest
from app import create_app
from config import TestingConfig
from extensions import db as _db


@pytest.fixture(scope='session')
def app():
    """Crea la aplicación Flask con configuración de testing (SQLite en memoria)."""
    application = create_app(TestingConfig)
    yield application


@pytest.fixture(scope='function')
def client(app):
    """Cliente HTTP de prueba."""
    with app.test_client() as c:
        yield c


@pytest.fixture(scope='function')
def db(app):
    """Base de datos limpia para cada test."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()
