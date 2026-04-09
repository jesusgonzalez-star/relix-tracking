from flask import Blueprint, current_app, request, jsonify
from flasgger import swag_from
from extensions import db
from models.tracking import DespachoTracking
from schemas.tracking import DespachoTrackingSchema
from marshmallow import ValidationError
from services.softland_service import SoftlandService
from utils.api_auth import enforce_api_secret_before_request
from utils.errors import APIError

bp = Blueprint('tracking', __name__, url_prefix='/api/tracking')


@bp.before_request
def _require_api_secret():
    return enforce_api_secret_before_request()


def _validate_oc_in_softland(num_oc: int):
    if not current_app.config.get('TRACKING_VALIDATE_OC_IN_SOFTLAND'):
        return
    SoftlandService.obtener_detalle_oc(num_oc)


tracking_schema = DespachoTrackingSchema()
trackings_schema = DespachoTrackingSchema(many=True)

@bp.route('/', methods=['POST'])
@swag_from({
    'tags': ['Tracking Despachos (Local)'],
    'summary': 'Registra un nuevo seguimiento de despacho',
    'description': 'Crea un nuevo registro en la base de datos local para una OC existente en Softland.',
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
                    'codigo_qr_data': {'type': 'string', 'example': 'QR-1001'}
                },
                'required': ['num_oc', 'estado']
            }
        }
    ],
    'responses': {
        201: {
            'description': 'Creado exitosamente'
        },
        400: {
            'description': 'Fallo de validación'
        }
    }
})
def create_tracking():
    try:
        data = tracking_schema.load(request.json)
        _validate_oc_in_softland(data.num_oc)

        db.session.add(data)
        db.session.commit()
        return jsonify(tracking_schema.dump(data)), 201
    except ValidationError as err:
        raise APIError("Error de validación", status_code=400, payload=err.messages)

@bp.route('/oc/<int:num_oc>', methods=['GET'])
@swag_from({
    'tags': ['Tracking Despachos (Local)'],
    'summary': 'Obtiene historial de despacho',
    'parameters': [{'name': 'num_oc', 'in': 'path', 'type': 'integer', 'required': True}],
    'responses': {200: {'description': 'Historial encontrado'}}
})
def get_tracking(num_oc):
    tracks = DespachoTracking.query.filter_by(num_oc=num_oc).order_by(DespachoTracking.timestamp.desc()).all()
    return jsonify(trackings_schema.dump(tracks)), 200
