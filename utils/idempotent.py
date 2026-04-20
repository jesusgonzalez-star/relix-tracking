"""Helpers para operaciones idempotentes en transacciones distribuidas."""
import uuid
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def generate_idempotency_key(prefix: str = 'op') -> str:
    """Genera clave idempotente única."""
    return f"{prefix}_{uuid.uuid4().hex[:16]}_{datetime.now(timezone.utc).timestamp()}"


def record_operation_start(idempotency_key: str, operacion: str) -> bool:
    """Registra inicio de operación. Retorna True si es la primera vez."""
    try:
        from models.tracking import IdempotentLog
        from extensions import db

        # Intentar crear registro
        log_entry = IdempotentLog(
            idempotency_key=idempotency_key,
            operacion=operacion,
            estado='INICIADO'
        )
        db.session.add(log_entry)
        db.session.commit()
        return True
    except Exception as e:
        logger.warning(f"Operación duplicada (clave ya existe): {idempotency_key}")
        return False


def mark_operation_complete(idempotency_key: str, resultado: dict = None):
    """Marca operación como completada."""
    try:
        from models.tracking import IdempotentLog
        from extensions import db

        log_entry = db.session.query(IdempotentLog).filter_by(
            idempotency_key=idempotency_key
        ).first()

        if log_entry:
            log_entry.estado = 'COMPLETADO'
            log_entry.resultado = json.dumps(resultado, default=str) if resultado else None
            db.session.commit()
    except Exception as e:
        logger.error(f"Error marcando operación completa: {e}")


def mark_operation_failed(idempotency_key: str, error_msg: str):
    """Marca operación como fallida."""
    try:
        from models.tracking import IdempotentLog
        from extensions import db

        log_entry = db.session.query(IdempotentLog).filter_by(
            idempotency_key=idempotency_key
        ).first()

        if log_entry:
            log_entry.estado = 'FALLIDO'
            log_entry.error = error_msg
            db.session.commit()
    except Exception as e:
        logger.error(f"Error marcando operación fallida: {e}")
