from datetime import datetime, timezone

from extensions import db


def _utc_now():
    return datetime.now(timezone.utc)


class DespachoTracking(db.Model):
    """
    Tabla SQLAlchemy (DespachoTracking_v2) usada por la API REST /api/tracking.
    El flujo operativo del panel (bodega/faena) usa además DespachosTracking / DespachosEnvio
    vía pyodbc; son modelos paralelos salvo que integremos escrituras cruzadas.
    """
    __tablename__ = 'DespachoTracking_v2' # Usamos v2 para no interferir con el DespachosTracking del monolito actual
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    num_oc = db.Column(db.Integer, index=True, nullable=False)
    estado = db.Column(db.String(50), nullable=False, default='INGRESADO')
    foto_evidencia_url = db.Column(db.String(500), nullable=True)
    codigo_qr_data = db.Column(db.String(500), nullable=True)
    timestamp = db.Column(db.DateTime, default=_utc_now, onupdate=_utc_now)

    def __repr__(self):
        return f"<DespachoTracking OC:{self.num_oc} - Estado:{self.estado}>"
