"""Tests de las nuevas reglas de transición, idempotencia y validación de Softland."""

from unittest.mock import patch

import pytest

from models.tracking import DespachoTracking
from services.tracking_local_service import create_tracking_row
from utils.states import (
    ST_INGRESADO, ST_EN_BODEGA, ST_EN_RUTA, ST_ENTREGADO, ST_CANCELADO,
    is_valid_transition,
)


class TestIsValidTransition:
    def test_initial_allows_any_non_terminal_path(self):
        assert is_valid_transition(None, ST_EN_BODEGA)
        assert is_valid_transition(None, ST_EN_RUTA)

    def test_terminal_blocks_further_changes(self):
        assert not is_valid_transition(ST_ENTREGADO, ST_EN_BODEGA)
        assert not is_valid_transition(ST_CANCELADO, ST_EN_RUTA)

    def test_forward_path_allowed(self):
        assert is_valid_transition(ST_EN_BODEGA, ST_EN_RUTA)
        assert is_valid_transition(ST_EN_RUTA, ST_ENTREGADO)

    def test_illegal_skip_rejected(self):
        assert not is_valid_transition(ST_INGRESADO, ST_ENTREGADO)

    def test_legacy_storage_value_normalized(self):
        assert is_valid_transition('EN BODEGA', ST_EN_RUTA)


class TestCreateTrackingRowTransitions:
    def test_reject_invalid_transition(self, db):
        db.session.add(DespachoTracking(num_oc=1001, estado=ST_ENTREGADO))
        db.session.commit()
        with pytest.raises(ValueError, match='Transición de estado inválida'):
            create_tracking_row(num_oc=1001, api_estado='BODEGA')

    def test_accept_valid_transition(self, db):
        db.session.add(DespachoTracking(num_oc=1002, estado=ST_EN_BODEGA))
        db.session.commit()
        row, created = create_tracking_row(num_oc=1002, api_estado='TRANSITO')
        assert created is True
        assert row.estado == ST_EN_RUTA

    def test_idempotency_returns_existing(self, db):
        r1, c1 = create_tracking_row(num_oc=1003, api_estado='BODEGA', idempotency_key='abc')
        r2, c2 = create_tracking_row(num_oc=1003, api_estado='BODEGA', idempotency_key='abc')
        assert c1 is True and c2 is False
        assert r1.id == r2.id


class TestApiCreateEndpoint:
    def _auth(self, app):
        return {'X-API-Key': app.config.get('API_SECRET', '')}

    def test_rejects_invalid_transition(self, app, client, db):
        db.session.add(DespachoTracking(num_oc=2001, estado=ST_ENTREGADO))
        db.session.commit()
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            resp = client.post(
                '/api/tracking/',
                json={'num_oc': 2001, 'estado': 'BODEGA'},
                headers=self._auth(app),
            )
        assert resp.status_code == 400
        assert 'Transición' in resp.get_json().get('mensaje', '')

    def test_rejects_ssrf_url(self, app, client, db):
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            resp = client.post(
                '/api/tracking/',
                json={
                    'num_oc': 2002,
                    'estado': 'BODEGA',
                    'foto_evidencia_url': 'http://127.0.0.1/evil.jpg',
                },
                headers=self._auth(app),
            )
        assert resp.status_code == 400


class TestSoftlandCacheAndRetry:
    def test_cache_returns_stored_value_without_new_fetch(self):
        from services import softland_service as svc
        svc.cache_invalidate()
        calls = {'n': 0}

        def fake_fetch(num_oc):
            calls['n'] += 1
            return {'folio': num_oc, 'productos': []}

        with patch.object(svc.SoftlandService, '_fetch_detalle_oc', side_effect=fake_fetch):
            svc.SoftlandService.obtener_detalle_oc(9999)
            svc.SoftlandService.obtener_detalle_oc(9999)
        assert calls['n'] == 1

    def test_404_not_retried(self):
        from services import softland_service as svc
        from utils.errors import APIError
        svc.cache_invalidate()
        calls = {'n': 0}

        def raiser(num_oc):
            calls['n'] += 1
            raise APIError('no existe', status_code=404)

        with patch.object(svc.SoftlandService, '_fetch_detalle_oc', side_effect=raiser):
            with pytest.raises(APIError):
                svc.SoftlandService.obtener_detalle_oc(8888, use_cache=False)
        assert calls['n'] == 1
