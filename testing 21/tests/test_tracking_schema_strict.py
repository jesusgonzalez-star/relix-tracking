import pytest
from marshmallow import ValidationError

from schemas.tracking import DespachoTrackingSchema


@pytest.fixture
def schema():
    return DespachoTrackingSchema()


@pytest.mark.parametrize('estado', ['BODEGA', 'TRANSITO', 'ENTREGADO'])
def test_schema_estado_valido(app_ctx, schema, estado):
    obj = schema.load({'num_oc': 5001, 'estado': estado})
    assert obj.estado == estado
    assert obj.num_oc == 5001


@pytest.mark.parametrize('estado', ['', 'INGRESADO', 'Bodega', 'X'])
def test_schema_estado_invalido(app_ctx, schema, estado):
    payload = {'num_oc': 1, 'estado': estado}
    with pytest.raises(ValidationError) as exc:
        schema.load(payload)
    assert 'estado' in exc.value.messages


def test_schema_num_oc_requerido(app_ctx, schema):
    with pytest.raises(ValidationError) as exc:
        schema.load({'estado': 'BODEGA'})
    assert 'num_oc' in exc.value.messages


def test_schema_estado_requerido(app_ctx, schema):
    with pytest.raises(ValidationError) as exc:
        schema.load({'num_oc': 1})
    assert 'estado' in exc.value.messages


def test_schema_num_oc_tipo(app_ctx, schema):
    with pytest.raises(ValidationError):
        schema.load({'num_oc': 'no-int', 'estado': 'BODEGA'})


def test_opcionales_permiten_faltantes(app_ctx, schema):
    obj = schema.load({
        'num_oc': 5002,
        'estado': 'TRANSITO',
        'foto_evidencia_url': None,
        'codigo_qr_data': None,
    })
    assert obj.num_oc == 5002
    assert obj.foto_evidencia_url is None
