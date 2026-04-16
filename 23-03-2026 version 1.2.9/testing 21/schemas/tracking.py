from marshmallow import Schema, fields, validate, EXCLUDE

from extensions import ma
from models.tracking import DespachoTracking
class DespachoTrackingCreateSchema(Schema):
    """Entrada POST /api/tracking (contrato estable para clientes móviles)."""

    num_oc = fields.Integer(
        required=True,
        validate=validate.Range(min=1, max=9999999, error='num_oc debe estar entre 1 y 9999999'),
    )
    estado = fields.String(
        required=True,
        validate=validate.OneOf(['BODEGA', 'TRANSITO', 'ENTREGADO']),
    )
    foto_evidencia_url = fields.String(
        required=False,
        allow_none=True,
        load_default=None,
        validate=validate.Regexp(
            r'^https?://',
            error='foto_evidencia_url debe ser una URL válida (http:// o https://)',
        ),
    )
    codigo_qr_data = fields.String(required=False, allow_none=True, load_default=None)
    idempotency_key = fields.String(
        required=False,
        allow_none=True,
        load_default=None,
        validate=validate.Length(max=64),
    )

    class Meta:
        unknown = EXCLUDE


class DespachoTrackingSchema(ma.SQLAlchemyAutoSchema):
    """Serialización de filas DespachosTracking hacia JSON de la API."""

    class Meta:
        model = DespachoTracking
        load_instance = False
        include_fk = True


despacho_tracking_create_schema = DespachoTrackingCreateSchema()
despacho_tracking_schema = DespachoTrackingSchema()
despachos_tracking_list_schema = DespachoTrackingSchema(many=True)
