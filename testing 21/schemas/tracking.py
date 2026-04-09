from extensions import ma
from marshmallow import fields, validate
from models.tracking import DespachoTracking

class DespachoTrackingSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = DespachoTracking
        load_instance = True
        
    estado = fields.String(required=True, validate=validate.OneOf(['BODEGA', 'TRANSITO', 'ENTREGADO']))
    num_oc = fields.Integer(required=True)
    foto_evidencia_url = fields.String(required=False, allow_none=True)
    codigo_qr_data = fields.String(required=False, allow_none=True)
