from flask import Blueprint, jsonify
from flasgger import swag_from
from services.softland_service import SoftlandService
from utils.api_auth import enforce_api_secret_before_request

bp = Blueprint('softland', __name__, url_prefix='/api/softland')


@bp.before_request
def _require_api_secret():
    return enforce_api_secret_before_request()

@bp.route('/oc/<int:num_oc>', methods=['GET'])
@swag_from({
    'tags': ['ERP Softland (Read-Only)'],
    'summary': 'Consulta una Orden de Compra',
    'description': 'Realiza un volcado seguro y de solo lectura de la cabecera, solicitante e items resumidos de una OC específica en el ERP.',
    'parameters': [
        {
            'name': 'num_oc',
            'in': 'path',
            'type': 'integer',
            'required': True,
            'description': 'El número de Orden de Compra a consultar'
        }
    ],
    'responses': {
        200: {
            'description': 'Datos de la OC encontrados',
            'schema': {
                'type': 'object',
                'properties': {
                    'num_oc': {'type': 'integer'},
                    'solicitante': {'type': 'string'},
                    'proveedor': {'type': 'string'},
                    'producto': {'type': 'string'}
                }
            }
        },
        404: {
            'description': 'OC no encontrada'
        }
    }
})
def get_oc(num_oc):
    datos = SoftlandService.obtener_detalle_oc(num_oc)
    return jsonify(datos), 200
