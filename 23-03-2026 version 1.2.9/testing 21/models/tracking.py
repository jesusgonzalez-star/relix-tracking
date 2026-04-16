"""
Modelo alineado con la tabla DespachosTracking del panel (pyodbc).
La API y el frontend comparten la misma tabla en la base local SQL Server.
"""
from extensions import db


class DespachoTracking(db.Model):
    __tablename__ = 'DespachosTracking'

    id = db.Column('Id', db.Integer, primary_key=True, autoincrement=True)
    num_oc = db.Column('NumOc', db.Integer, nullable=False, index=True)
    estado = db.Column('Estado', db.String(50), nullable=False, default='INGRESADO')
    fecha_hora_salida = db.Column('FechaHoraSalida', db.DateTime, nullable=True)
    fecha_hora_entrega = db.Column('FechaHoraEntrega', db.DateTime, nullable=True)
    foto_evidencia_url = db.Column('UrlFotoEvidencia', db.Text, nullable=True)
    codigo_qr_data = db.Column('CodigoQR', db.Text, nullable=True)
    registrado_por = db.Column('RegistradoPor', db.Integer, nullable=True)
    transportista = db.Column('Transportista', db.String(100), nullable=True)
    guia_despacho = db.Column('GuiaDespacho', db.String(50), nullable=True)
    observaciones = db.Column('Observaciones', db.Text, nullable=True)
    transportista_asignado_id = db.Column('transportista_asignado_id', db.Integer, nullable=True)
    # Idempotencia API (chofer / reintentos). Índice único filtrado en SQL Server vía migración manual opcional.
    api_idempotency_key = db.Column('ApiIdempotencyKey', db.String(64), nullable=True, unique=True, index=True)
    # Auditoría: timestamps automáticos en UTC (requiere ALTER TABLE en BD existentes).
    created_at = db.Column('CreatedAt', db.DateTime, nullable=True, server_default=db.text('GETUTCDATE()'))
    updated_at = db.Column('UpdatedAt', db.DateTime, nullable=True, server_default=db.text('GETUTCDATE()'), onupdate=db.func.now())

    def __repr__(self):
        return f'<DespachoTracking OC:{self.num_oc} Estado:{self.estado!r}>'
