"""API interna del frontend – verificación QR y estado de orden."""

import logging
from datetime import datetime

from flask import (
    request, redirect, url_for, flash,
    session, jsonify,
)
import pyodbc

from utils.auth import login_required, has_any_role
from utils.permissions import roles_for
from utils.db_legacy import DatabaseConnection
from extensions import limiter
from config import SoftlandConfig
from routes.frontend import bp
from routes.frontend._helpers import (
    _ensure_local_tracking_table,
    _state_in,
    _normalize_state_value,
    _canonical_tracking_state,
    _resolve_evidence_url,
    _resolve_evidence_urls_all,
    _resolve_softland_column,
    _load_softland_oc_items,
    _summarize_softland_arrival,
    _erp_scopes_softland_by_aux,
    logger,
)
from services.softland_service import SoftlandService


@bp.route('/api/verificar_qr', methods=['POST'])
@limiter.limit('30 per minute', methods=['POST'])
@login_required(roles=roles_for('verify_qr'))
def verificar_qr():
    """API para verificar QR desde app móvil"""
    try:
        # Validar Content-Type
        if request.content_type and 'application/json' not in request.content_type:
            return jsonify({'valido': False, 'error': 'Content-Type debe ser application/json'}), 400

        data = request.json or {}
        qr_code = data.get('qr_code', '').strip()
        folio = data.get('folio')

        if not qr_code:
            return jsonify({'valido': False, 'error': 'QR requerido'}), 400

        conn = DatabaseConnection.get_connection()
        if not conn:
            logger.error("Error conexión en verificar_qr")
            return jsonify({'valido': False, 'error': 'Error de base de datos'}), 500

        try:
            cursor = conn.cursor()

            # Verificar QR válido
            cursor.execute("""
                SELECT FolioOC, Activo, Usado, FechaExpiracion
                FROM CodigosQR
                WHERE CodigoQR = ? AND Activo = 1 AND Usado = 0
                AND (FechaExpiracion IS NULL OR FechaExpiracion > UTC_TIMESTAMP())
            """, (qr_code,))

            qr = cursor.fetchone()

            if qr:
                logger.info("QR válido verificado: Folio %s", qr[0])
                return jsonify({
                    'valido': True,
                    'folio': qr[0],
                    'mensaje': 'QR válido y activo',
                    'fecha_expiracion': (qr[3] if isinstance(qr[3], str) else qr[3].isoformat()) if qr[3] else None
                }), 200
            else:
                logger.warning("Intento de QR inválido o expirado")
                return jsonify({
                    'valido': False,
                    'error': 'QR inválido, expirado o ya utilizado'
                }), 401

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error en verificar_qr: {str(e)}", exc_info=True)
        return jsonify({'valido': False, 'error': 'Error interno del servidor'}), 500


@bp.route('/api/estado_orden/<int:folio>', methods=['GET'])
@login_required(roles=roles_for('view_all'))
def estado_orden(folio):
    """API para obtener estado actual de una orden"""
    try:
        conn = DatabaseConnection.get_connection()
        if not conn:
            return jsonify({'error': 'Error de conexión'}), 500

        try:
            cursor = conn.cursor()
            user_role = session.get('rol')
            user_id = session.get('user_id')

            # Faena solo puede consultar órdenes asignadas a su usuario.
            if has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN']):
                ok_env = None
                try:
                    cursor.execute("""
                        SELECT 1 FROM DespachosEnvio
                        WHERE NumOc = ? AND transportista_asignado_id = ?
                    """, (folio, user_id))
                    ok_env = cursor.fetchone()
                except Exception:
                    ok_env = None
                if not ok_env:
                    cursor.execute("""
                        SELECT 1 FROM DespachosTracking
                        WHERE NumOc = ? AND transportista_asignado_id = ?
                    """, (folio, user_id))
                    if not cursor.fetchone():
                        return jsonify({'error': 'No autorizado para este folio'}), 403

            if _erp_scopes_softland_by_aux(user_role):
                cursor.execute(
                    "SELECT aux_id_softland FROM UsuariosSistema WHERE Id = ?",
                    (user_id,),
                )
                viz_row = cursor.fetchone()
                aux_id_softland = viz_row[0] if viz_row else None
                if aux_id_softland:
                    conn_sl = SoftlandService.get_connection()
                    try:
                        c_sl = conn_sl.cursor()
                        c_sl.execute(
                            """
                            SELECT 1 FROM softland.owordencom WITH (NOLOCK)
                            WHERE NumOC = ? AND CodAux = ?
                            """,
                            (folio, aux_id_softland),
                        )
                        if not c_sl.fetchone():
                            return jsonify({'error': 'No autorizado para este folio'}), 403
                    finally:
                        conn_sl.close()

            # Paso 1: Datos desde Softland (SQL Server)
            softland_data = None
            try:
                conn_softland = pyodbc.connect(
                    SoftlandConfig.get_connection_string(),
                    timeout=SoftlandConfig.DB_TIMEOUT,
                )
                try:
                    cursor_s = conn_softland.cursor()
                    cursor_s.execute("""
                        SELECT
                            OC.NumOc AS FolioOC,
                            MAX(Aux.NomAux) AS NomProv,
                            MAX(Req.Solicitante) AS Solicitante,
                            MAX(P.DesProd) + CASE WHEN COUNT(DISTINCT Det.codprod) > 1
                                THEN ' (+' + CAST(COUNT(DISTINCT Det.codprod)-1 AS VARCHAR) + ')'
                                ELSE '' END AS ProductoResumen,
                            MAX(G.Orden) AS TieneGuia
                        FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                        LEFT JOIN softland.Dw_VsnpRequerimientosMateriasPrimas Req WITH (NOLOCK) ON OC.NumOc = Req.Orden
                        LEFT JOIN softland.owordencom OH WITH (NOLOCK) ON OH.NumInterOC = OC.NumInterOc
                        LEFT JOIN softland.EC_VsnpTraeAuxiliaresLogCwtauxi Aux WITH (NOLOCK) ON OH.CodAux = Aux.CodAux
                        LEFT JOIN softland.ow_vsnpMovimIWDetalleOC Det WITH (NOLOCK) ON OC.NumOc = Det.numoc
                        LEFT JOIN softland.IW_vsnpProductos P WITH (NOLOCK) ON Det.codprod = P.CodProd
                        LEFT JOIN softland.IW_vsnpGuiasEntradaxOC G WITH (NOLOCK) ON OC.NumOc = G.Orden
                        WHERE OC.NumOc = ?
                        GROUP BY OC.NumOc
                    """, (folio,))
                    softland_data = cursor_s.fetchone()
                finally:
                    conn_softland.close()
            except Exception as exc:
                logger.warning("Softland no disponible para estado_orden: %s", exc)

            if not softland_data:
                return jsonify({'error': 'Orden no encontrada'}), 404

            # Paso 2: Datos de tracking local (MariaDB)
            cursor.execute("""
                SELECT Estado, FechaHoraSalida, Transportista, GuiaDespacho, FechaHoraEntrega
                FROM DespachosTracking
                WHERE NumOc = ?
                ORDER BY Id DESC
                LIMIT 1
            """, (folio,))
            local_row = cursor.fetchone()

            # Paso 3: Merge
            estado_local = local_row[0] if local_row else None
            tiene_guia = softland_data[4] is not None

            if estado_local:
                estado_general = estado_local
            elif tiene_guia:
                estado_general = 'EN_BODEGA'
            else:
                estado_general = 'PENDIENTE_EN_SOFTLAND'

            return jsonify({
                'folio': softland_data[0],
                'proveedor': softland_data[1] or 'Sin Proveedor',
                'solicitante': softland_data[2],
                'producto': softland_data[3],
                'estado': estado_general,
                'fecha_recepcion': None,
                'fecha_despacho': str(local_row[1]) if local_row and local_row[1] else None,
                'fecha_entrega': str(local_row[4]) if local_row and local_row[4] else None,
                'transportista': (local_row[2] if local_row and local_row[2] else 'N/A'),
                'guia': (local_row[3] if local_row and local_row[3] else 'N/A'),
                'estado_entrega': estado_local or 'PENDIENTE',
            }), 200

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error en estado_orden: {str(e)}", exc_info=True)
        return jsonify({'error': 'Error interno'}), 500
