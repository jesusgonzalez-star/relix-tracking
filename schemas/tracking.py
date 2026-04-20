import ipaddress
from urllib.parse import urlparse

from marshmallow import Schema, fields, validate, validates, ValidationError, EXCLUDE

from extensions import ma
from models.tracking import DespachoTracking


def _validate_safe_url(url: str) -> None:
    """Rechaza URLs hacia hosts privados/link-local/loopback/metadata (SSRF)."""
    if not url:
        return
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValidationError('Solo se permiten URLs http(s).')
    host = (parsed.hostname or '').strip().lower()
    if not host:
        raise ValidationError('URL sin host válido.')
    if host in ('localhost', 'metadata.google.internal'):
        raise ValidationError('Host no permitido.')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    ):
        raise ValidationError('URLs hacia IPs internas/privadas no están permitidas.')
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
        validate=[
            validate.Length(max=2048),
            validate.Regexp(
                r'^https?://',
                error='foto_evidencia_url debe ser una URL válida (http:// o https://)',
            ),
        ],
    )

    @validates('foto_evidencia_url')
    def _check_url_safe(self, value, **_):
        _validate_safe_url(value)
    codigo_qr_data = fields.String(
        required=False,
        allow_none=True,
        load_default=None,
        validate=validate.Length(max=4096),
    )
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
