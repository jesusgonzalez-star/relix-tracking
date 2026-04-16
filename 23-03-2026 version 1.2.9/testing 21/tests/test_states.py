"""Tests para utils/states.py — consistencia de constantes de estado."""

from utils.states import (
    ST_INGRESADO, ST_EN_BODEGA, ST_EN_RUTA, ST_ENTREGADO,
    ST_CANCELADO, ST_ANULADO, ST_PENDIENTE_SOFTLAND, ST_DISPONIBLE_BODEGA,
    LST_EN_RUTA, LST_ENTREGADO, LST_PARCIAL, LST_RECHAZADO,
    VALID_TRACKING_STATES, VALID_LINE_STATES,
    STORAGE_STATE_MAP, API_TO_DB_ESTADO,
)


class TestTrackingStates:
    def test_all_constants_in_valid_set(self):
        expected = {
            ST_INGRESADO, ST_EN_BODEGA, ST_EN_RUTA, ST_ENTREGADO,
            ST_CANCELADO, ST_ANULADO, ST_PENDIENTE_SOFTLAND, ST_DISPONIBLE_BODEGA,
        }
        assert expected == VALID_TRACKING_STATES

    def test_storage_map_covers_all_states(self):
        """Cada estado canónico debe aparecer como valor en STORAGE_STATE_MAP."""
        mapped_values = set(STORAGE_STATE_MAP.values())
        for state in VALID_TRACKING_STATES:
            assert state in mapped_values, f'{state} no tiene entrada en STORAGE_STATE_MAP'

    def test_storage_map_keys_are_uppercase(self):
        """Las claves del mapa deben estar normalizadas (UPPER)."""
        for key in STORAGE_STATE_MAP:
            assert key == key.upper(), f'Clave "{key}" no es uppercase'


class TestLineStates:
    def test_all_line_constants_in_valid_set(self):
        expected = {LST_EN_RUTA, LST_ENTREGADO, LST_PARCIAL, LST_RECHAZADO}
        assert expected == VALID_LINE_STATES

    def test_line_states_are_uppercase(self):
        for state in VALID_LINE_STATES:
            assert state == state.upper(), f'Estado de línea "{state}" no es uppercase'


class TestApiToDbMapping:
    def test_all_api_states_map_to_valid_tracking_states(self):
        for api_key, db_val in API_TO_DB_ESTADO.items():
            assert db_val in VALID_TRACKING_STATES, (
                f'API state "{api_key}" mapea a "{db_val}" que no está en VALID_TRACKING_STATES'
            )

    def test_known_api_states(self):
        assert API_TO_DB_ESTADO['BODEGA'] == ST_EN_BODEGA
        assert API_TO_DB_ESTADO['TRANSITO'] == ST_EN_RUTA
        assert API_TO_DB_ESTADO['ENTREGADO'] == ST_ENTREGADO
