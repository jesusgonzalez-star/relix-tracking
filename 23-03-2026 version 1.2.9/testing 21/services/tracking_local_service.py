"""
Escrituras de tracking local compartidas por la API.
Mapea estados del contrato API (BODEGA / TRANSITO / ENTREGADO) a los valores
que usa el panel (DespachosTracking) para una sola fuente de verdad en BD.
"""
from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError

from extensions import db
from models.tracking import DespachoTracking

logger = logging.getLogger(__name__)

API_TO_DB_ESTADO = {
    'BODEGA': 'EN_BODEGA',
    'TRANSITO': 'EN RUTA',
    'ENTREGADO': 'ENTREGADO',
}


def map_api_estado_to_db(api_estado: str) -> str:
    key = (api_estado or '').strip().upper()
    return API_TO_DB_ESTADO.get(key, api_estado or 'INGRESADO')


def create_tracking_row(
    *,
    num_oc: int,
    api_estado: str,
    foto_evidencia_url: str | None = None,
    codigo_qr_data: str | None = None,
    idempotency_key: str | None = None,
):
    """
    Inserta una fila en DespachosTracking. Si idempotency_key ya existe, devuelve la fila existente.
    Hace commit; ante fallo hace rollback y reintenta lectura por clave duplicada (doble envío / red).
    """
    db_estado = map_api_estado_to_db(api_estado)
    key = (idempotency_key or '').strip() or None

    if key:
        existing = DespachoTracking.query.filter_by(api_idempotency_key=key).first()
        if existing is not None:
            return existing, False

    row = DespachoTracking(
        num_oc=num_oc,
        estado=db_estado,
        foto_evidencia_url=foto_evidencia_url,
        codigo_qr_data=codigo_qr_data,
        api_idempotency_key=key,
    )
    db.session.add(row)
    try:
        db.session.commit()
        return row, True
    except IntegrityError as exc:
        db.session.rollback()
        logger.info(
            "IntegrityError al insertar tracking (posible duplicado): num_oc=%s key=%s — %s",
            num_oc,
            key,
            exc,
        )
        if key:
            existing = DespachoTracking.query.filter_by(api_idempotency_key=key).first()
            if existing is not None:
                return existing, False
        raise
