"""Auditoría y logging de cambios críticos."""
import json
import logging
from datetime import datetime

from flask import session

logger = logging.getLogger(__name__)


def audit_log(tabla: str, accion: str, usuario: str = None, registro_id: int = None,
              valores_antes: dict = None, valores_despues: dict = None, detalles: str = None):
    """Registra cambio en AuditLog (no rompe si falla — solo log)."""
    try:
        from models.tracking import AuditLog
        from extensions import db

        if usuario is None:
            usuario = session.get('user_id') if session else None

        log_entry = AuditLog(
            usuario=usuario,
            tabla=tabla,
            accion=accion,
            registro_id=registro_id,
            valores_antes=json.dumps(valores_antes, default=str) if valores_antes else None,
            valores_despues=json.dumps(valores_despues, default=str) if valores_despues else None,
            detalles=detalles,
        )
        # Sesión independiente: la auditoría persiste aunque el caller haga
        # rollback. Usa el mismo engine que db.session para compartir conexión.
        from sqlalchemy.orm import Session as SASession
        audit_session = SASession(bind=db.engine, expire_on_commit=False)
        try:
            audit_session.add(log_entry)
            audit_session.commit()
        except Exception:
            audit_session.rollback()
            raise
        finally:
            audit_session.close()
    except Exception as e:
        logger.warning(f"Fallo al registrar auditoría: {e}")
