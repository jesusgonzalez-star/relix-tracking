import logging

from flask import Blueprint, current_app, request, jsonify
from flasgger import swag_from
from marshmallow import ValidationError
from sqlalchemy.exc import IntegrityError, OperationalError

from models.tracking import DespachoTracking
from schemas.tracking import (
    despacho_tracking_create_schema,
    despacho_tracking_schema,
    despachos_tracking_list_schema,
)
from services.softland_service import SoftlandService
from services.tracking_local_service import create_tracking_row
from utils.api_auth import enforce_api_secret_before_request
from utils.errors import APIError

logger = logging.getLogger(__name__)

bp = Blueprint('tracking', __name__, url_prefix='/api/tracking')


@bp.before_request
def _require_api_secret():
    return enforce_api_secret_before_request()


def _validate_oc_in_softland(num_oc: int):
    if not current_app.config.get('TRACKING_VALIDATE_OC_IN_SOFTLAND'):
        return
    try:
        SoftlandService.obtener_detalle_oc(num_oc)
    except APIError as exc:
        # OC inexistente en Softland es un error de entrada del cliente (400),
        # no un fallo del servidor (404/500).
        if getattr(exc, 'status_code', None) in (400, 404):
            raise APIError(
                f'OC {num_oc} no existe en Softland',
                status_code=400,
            )
        raise


@bp.route('/', methods=['POST'])
@swag_from({
    'tags': ['Tracking Despachos (Local)'],
    'summary': 'Registra un nuevo seguimiento de despacho',
    'description': (
        'Crea un registro en DespachosTracking (misma tabla que el panel web). '
        'Estados API: BODEGA, TRANSITO, ENTREGADO. Opcional: idempotency_key para evitar duplicados por reintentos.'
    ),
    'parameters': [
        {
            'name': 'body',
            'in': 'body',
            'required': True,
            'schema': {
                'type': 'object',
                'properties': {
                    'num_oc': {'type': 'integer', 'example': 1001},
                    'estado': {'type': 'string', 'example': 'BODEGA', 'enum': ['BODEGA', 'TRANSITO', 'ENTREGADO']},
                    'foto_evidencia_url': {'type': 'string', 'example': 'http://storage.mx/gd.jpg'},
                    'codigo_qr_data': {'type': 'string', 'example': 'QR-1001'},
                    'idempotency_key': {'type': 'string', 'example': 'uuid-o-hash-cliente', 'maxLength': 64},
                },
                'required': ['num_oc', 'estado'],
            },
        }
    ],
    'responses': {
        201: {'description': 'Creado exitosamente'},
        200: {'description': 'Ya existía (misma idempotency_key)'},
        400: {'description': 'Fallo de validación'},
    },
})
def create_tracking():
    try:
        data = despacho_tracking_create_schema.load(request.json or {})
        _validate_oc_in_softland(data['num_oc'])
        row, created = create_tracking_row(
            num_oc=data['num_oc'],
            api_estado=data['estado'],
            foto_evidencia_url=data.get('foto_evidencia_url'),
            codigo_qr_data=data.get('codigo_qr_data'),
            idempotency_key=data.get('idempotency_key'),
        )
        payload = despacho_tracking_schema.dump(row)
        return jsonify(payload), 201 if created else 200
    except ValidationError as err:
        raise APIError('Error de validación', status_code=400, payload=err.messages)
    except ValueError as err:
        raise APIError(str(err), status_code=400)
    except IntegrityError as exc:
        num_oc = (request.json or {}).get('num_oc')
        detail = str(getattr(exc, 'orig', exc)) or str(exc)
        logger.warning("IntegrityError no recuperado en create_tracking para OC %s: %s", num_oc, detail)
        low = detail.lower()
        if 'idempotency' in low or 'api_idempotency_key' in low:
            msg = 'Conflicto: idempotency_key ya usada con datos distintos'
        elif 'unique' in low or 'duplicate' in low:
            msg = f'Conflicto de unicidad al insertar tracking: {detail}'
        else:
            msg = f'Conflicto de integridad: {detail}'
        raise APIError(msg, status_code=409)
    except OperationalError:
        logger.error("Error de conexión a BD en create_tracking", exc_info=True)
        raise APIError('Base de datos no disponible', status_code=503)


@bp.route('/oc/<int:num_oc>', methods=['GET'])
@swag_from({
    'tags': ['Tracking Despachos (Local)'],
    'summary': 'Obtiene historial de despacho (paginado)',
    'parameters': [
        {'name': 'num_oc', 'in': 'path', 'type': 'integer', 'required': True},
        {'name': 'limit', 'in': 'query', 'type': 'integer', 'required': False, 'default': 50},
        {'name': 'offset', 'in': 'query', 'type': 'integer', 'required': False, 'default': 0},
    ],
    'responses': {200: {'description': 'Historial encontrado'}},
})
def get_tracking(num_oc):
    # Backward-compatible: si no se pasa limit/offset devuelve array (legacy).
    # Si se pasa, devuelve objeto paginado {data, total, limit, offset}.
    paginated = 'limit' in request.args or 'offset' in request.args
    try:
        limit = int(request.args.get('limit', 200))
        offset = int(request.args.get('offset', 0))
    except (TypeError, ValueError):
        raise APIError('limit/offset deben ser enteros', status_code=400)
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    base = DespachoTracking.query.filter_by(num_oc=num_oc)
    query = base.order_by(DespachoTracking.id.desc()).limit(limit).offset(offset)
    tracks = query.all()
    data = despachos_tracking_list_schema.dump(tracks)

    if paginated:
        return jsonify({
            'data': data,
            'total': base.count(),
            'limit': limit,
            'offset': offset,
        }), 200
    return jsonify(data), 200
