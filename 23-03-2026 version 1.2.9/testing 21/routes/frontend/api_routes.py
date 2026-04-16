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
                AND (FechaExpiracion IS NULL OR FechaExpiracion > GETDATE())
            """, (qr_code,))

            qr = cursor.fetchone()

            if qr:
                logger.info(f"QR válido verificado: Folio {qr[0]}")
                return jsonify({
                    'valido': True,
                    'folio': qr[0],
                    'mensaje': 'QR válido y activo',
                    'fecha_expiracion': qr[3].isoformat() if qr[3] else None
                }), 200
            else:
                logger.warning(f"Intento de QR inválido o expirado")
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
                            SELECT 1 FROM softland.NW_OW_VsnpSaldoDetalleOC
                            WHERE NumOc = ? AND Codaux = ?
                            """,
                            (folio, aux_id_softland),
                        )
                        if not c_sl.fetchone():
                            return jsonify({'error': 'No autorizado para este folio'}), 403
                    finally:
                        conn_sl.close()

            cursor.execute("""
                WITH EstadoOC AS (
                    SELECT
                        OC.NumOc AS FolioOC,
                        MAX(Aux.NomAux) AS NomProv,
                        MAX(Req.Solicitante) AS Solicitante,
                        MAX(P.DesProd) + CASE WHEN COUNT(DISTINCT Det.codprod) > 1 THEN ' (+' + CAST(COUNT(DISTINCT Det.codprod)-1 AS VARCHAR) + ')' ELSE '' END AS ProductoResumen,
                        MAX(G.Orden) AS TieneGuia,
                        MAX(D.FechaHoraSalida) AS FechaDespacho,
                        MAX(D.Transportista) AS Transportista,
                        MAX(D.GuiaDespacho) AS GuiaDespacho,
                        MAX(D.Estado) AS EstadoDespachoLocal,
                        MAX(D.FechaHoraEntrega) AS FechaEntregaCliente
                    FROM softland.OW_vsnpTraeEncabezadoOCompra OC
                    LEFT JOIN softland.Dw_VsnpRequerimientosMateriasPrimas Req ON OC.NumOc = Req.Orden
                    LEFT JOIN softland.NW_OW_VsnpSaldoDetalleOC S ON OC.NumOc = S.numoc
                    LEFT JOIN softland.EC_VsnpTraeAuxiliaresLogCwtauxi Aux ON S.Codaux = Aux.CodAux
                    LEFT JOIN softland.ow_vsnpMovimIWDetalleOC Det ON OC.NumOc = Det.numoc
                    LEFT JOIN softland.IW_vsnpProductos P ON Det.codprod = P.CodProd
                    LEFT JOIN softland.IW_vsnpGuiasEntradaxOC G ON OC.NumOc = G.Orden
                    LEFT JOIN (
                        SELECT TOP 1 NumOc, FechaHoraSalida, Transportista, GuiaDespacho, Estado, FechaHoraEntrega
                        FROM DespachosTracking
                        WHERE NumOc = ?
                        ORDER BY Id DESC
                    ) D ON D.NumOc = OC.NumOc
                    WHERE OC.NumOc = ?
                    GROUP BY OC.NumOc
                )
                SELECT
                    FolioOC,
                    COALESCE(NomProv, 'Sin Proveedor') AS NomProv,
                    Solicitante,
                    ProductoResumen,
                    CASE
                        WHEN EstadoDespachoLocal IS NOT NULL THEN EstadoDespachoLocal
                        WHEN TieneGuia IS NOT NULL THEN 'EN_BODEGA'
                        ELSE 'PENDIENTE_EN_SOFTLAND'
                    END AS EstadoGeneral,
                    NULL AS FechaRecepcionBodega,
                    FechaDespacho,
                    FechaEntregaCliente,
                    COALESCE(Transportista, 'N/A') AS Transportista,
                    COALESCE(GuiaDespacho, 'N/A') AS GuiaDespacho,
                    COALESCE(EstadoDespachoLocal, 'PENDIENTE') AS EstadoEntrega
                FROM EstadoOC
            """, (folio, folio))

            orden = cursor.fetchone()

            if orden:
                return jsonify({
                    'folio': orden[0],
                    'proveedor': orden[1],
                    'solicitante': orden[2],
                    'producto': orden[3],
                    'estado': orden[4],
                    'fecha_recepcion': orden[5].isoformat() if orden[5] else None,
                    'fecha_despacho': orden[6].isoformat() if orden[6] else None,
                    'fecha_entrega': orden[7].isoformat() if orden[7] else None,
                    'transportista': orden[8],
                    'guia': orden[9],
                    'estado_entrega': orden[10]
                }), 200
            else:
                return jsonify({'error': 'Orden no encontrada'}), 404

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error en estado_orden: {str(e)}", exc_info=True)
        return jsonify({'error': 'Error interno'}), 500
