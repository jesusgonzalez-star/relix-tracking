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
from utils.states import API_TO_DB_ESTADO, VALID_TRACKING_STATES

logger = logging.getLogger(__name__)


def map_api_estado_to_db(api_estado: str) -> str:
    """Convierte estado API a estado BD. Lanza ValueError si el estado no es válido."""
    key = (api_estado or '').strip().upper()
    db_estado = API_TO_DB_ESTADO.get(key)
    if db_estado is None:
        raise ValueError(
            f"Estado API inválido: {api_estado!r}. "
            f"Valores permitidos: {', '.join(sorted(API_TO_DB_ESTADO))}"
        )
    return db_estado


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
            # Segundo intento: la fila puede tardar en ser visible (READ_COMMITTED).
            db.session.expire_all()
            existing = DespachoTracking.query.filter_by(api_idempotency_key=key).first()
            if existing is not None:
                return existing, False
        raise
