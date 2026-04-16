"""Rutas de faena – órdenes, requisiciones, entregas y recepción."""

import os
import re
import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from PIL import Image, ImageDraw

from flask import (
    render_template, request, redirect, url_for, flash,
    session, current_app, abort,
)
from werkzeug.utils import secure_filename
import pyodbc

from utils.auth import login_required, has_any_role
from utils.permissions import roles_for
from utils.db_legacy import DatabaseConnection
from config import SoftlandConfig
from utils.sql_helpers import softland_connection, softland_cursor
from utils.recepcion_form import (
    consume_recepcion_form_token,
    mint_recepcion_form_token,
    verify_recepcion_form_token,
)
from utils.cc_helpers import (
    normalize_cc_assignments as _normalize_cc_assignments,
    build_softland_cc_match_clause as _build_softland_cc_match_clause,
    ensure_faena_cc_column as _ensure_faena_cc_column,
    get_faena_cc_assignments as _get_faena_cc_assignments,
    get_folios_by_centros_costo as _get_folios_by_centros_costo,
    folio_matches_centros_costo_tokens as _folio_matches_centros_costo_tokens,
    faena_user_has_cc_access_to_folio as _faena_user_has_cc_access_to_folio,
    fetch_softland_centros_costo_opciones as _fetch_softland_centros_costo_opciones,
)
from services.softland_sql_fragments import SOFTLAND_OC_SALDO_AGG_APPLY
from routes.frontend import bp
from routes.frontend._helpers import (
    _ensure_local_tracking_table,
    _parse_iso_date,
    _to_date,
    _build_eta_badge,
    _state_in,
    _normalize_state_value,
    _canonical_tracking_state,
    _sync_despachos_tracking_header,
    _load_softland_oc_items,
    _sanitize_next_url,
    _get_evidence_upload_dir,
    allowed_file,
    _normalize_oc_linea_num,
    _map_cantidad_recibida_faena_por_linea_oc,
    _faena_line_key,
    _parse_evidencia_urls_field,
    _resolve_evidence_url,
    _resolve_evidence_urls_all,
    _faena_recepcion_evidence_urls,
    _load_faena_recepcion_evidence_urls_por_oc,
    _resolve_softland_column,
    _fetch_latest_tracking_rows_by_folio,
    _load_reception_summary_by_folio,
    _load_pending_bodega_dispatch_by_folio,
    _bodega_dashboard_row_label,
    _derive_bodega_tracking_status,
    _sql_case_linea_despacho_parcial_bodega,
    _load_envios_agrupados_por_guia,
    _crear_notificaciones_bodega,
    _DASHBOARD_PAGE_SIZE,
    logger,
    ST_EN_RUTA, ST_ENTREGADO,
    LST_ENTREGADO, LST_PARCIAL, LST_RECHAZADO,
)


@bp.route('/faena/ordenes')
@login_required(roles=roles_for('faena_operations'))
def faena_ordenes_cc():
    """Listado paginado de todas las OC Softland del(los) centro(s) de costo del usuario FAENA, con tracking y recepción."""

    user_id = session.get('user_id')
    user_role = session.get('rol')
    is_super = has_any_role(user_role, ['SUPERADMIN'])
    faena_cc = None
    if not is_super:
        conn_u = DatabaseConnection.get_connection()
        if not conn_u:
            flash('Error de conexión', 'danger')
            return redirect(url_for('frontend.index'))
        try:
            cu = conn_u.cursor()
            _ensure_faena_cc_column(cu)
            conn_u.commit()
            cu.execute("SELECT CentrosCostoAsignados FROM UsuariosSistema WHERE Id = ?", (user_id,))
            urow = cu.fetchone()
            faena_cc = _normalize_cc_assignments(urow[0] if urow else '')
        finally:
            conn_u.close()
        if not faena_cc:
            flash('No tiene centros de costo asignados para consultar órdenes.', 'warning')
            return redirect(url_for('frontend.index'))

    filtro_desde_raw = (request.args.get('desde') or '').strip()
    filtro_hasta_raw = (request.args.get('hasta') or '').strip()
    filtro_desde_date = _parse_iso_date(filtro_desde_raw)
    filtro_hasta_date = _parse_iso_date(filtro_hasta_raw)
    if filtro_desde_raw and not filtro_desde_date:
        flash('La fecha Desde no es válida. Use YYYY-MM-DD.', 'warning')
        filtro_desde_raw = ''
        filtro_desde_date = None
    if filtro_hasta_raw and not filtro_hasta_date:
        flash('La fecha Hasta no es válida. Use YYYY-MM-DD.', 'warning')
        filtro_hasta_raw = ''
        filtro_hasta_date = None
    if filtro_desde_date and filtro_hasta_date and filtro_desde_date > filtro_hasta_date:
        flash('Rango de fechas inválido.', 'warning')
        filtro_desde_raw = ''
        filtro_hasta_raw = ''
        filtro_desde_date = None
        filtro_hasta_date = None

    page = request.args.get('page', default=1, type=int) or 1
    if page < 1:
        page = 1
    page_size = _DASHBOARD_PAGE_SIZE
    row_offset = (page - 1) * page_size

    where_parts = []
    params = []
    if faena_cc is not None:
        cc_match_sql, _ = _build_softland_cc_match_clause('OC', len(faena_cc))
        where_parts.append(cc_match_sql)
        params.extend(faena_cc)
        params.extend(faena_cc)
    if filtro_desde_date:
        where_parts.append(
            "COALESCE(TRY_CONVERT(date, OC.FechaOC, 103), TRY_CONVERT(date, OC.FechaOC)) >= ?"
        )
        params.append(filtro_desde_raw)
    if filtro_hasta_date:
        where_parts.append(
            "COALESCE(TRY_CONVERT(date, OC.FechaOC, 103), TRY_CONVERT(date, OC.FechaOC)) <= ?"
        )
        params.append(filtro_hasta_raw)
    where_sql = ' AND '.join(where_parts) if where_parts else '1=1'

    oc_rows = []
    total_count = 0
    has_more = False
    conn_softland = None
    try:
        conn_softland = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
        cursor_s = conn_softland.cursor()
        cursor_s.execute(
            f"""
            SELECT COUNT(1)
            FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
            WHERE {where_sql}
            """,
            tuple(params),
        )
        tr = cursor_s.fetchone()
        total_count = int((tr[0] if tr else 0) or 0)

        cursor_s.execute(
            f"""
            SELECT
                OC.NumOc AS Folio,
                COALESCE(TRY_CONVERT(date, OC.FechaOC, 103), TRY_CONVERT(date, OC.FechaOC)) AS FechaEmision,
                COALESCE(TRY_CONVERT(date, OC.FecFinalOC, 103), TRY_CONVERT(date, OC.FecFinalOC)) AS FechaLlegadaEstimada,
                COALESCE(OC.NomAux, 'Sin Proveedor') AS Proveedor,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(OC.DescCC)), ''),
                    NULLIF(LTRIM(RTRIM(OC.CodiCC)), ''),
                    'Sin CC'
                ) AS CentroCosto,
                ISNULL(OC.ValorTotMB, 0) AS MontoTotal,
                OC.NumInterOc AS NumInterOC,
                CASE WHEN ISNULL(softland_aggr.TotalLineas, 0) > 0 THEN 1 ELSE 0 END AS TieneGuia,
                CASE WHEN ISNULL(softland_aggr.QtyIngresadaTotal, 0) > 0 THEN 1 ELSE 0 END AS HasAnyArrival,
                ISNULL(softland_aggr.QtySolicitadaTotal, 0) AS QtySolicitadaTotal,
                ISNULL(softland_aggr.QtyIngresadaTotal, 0) AS QtyIngresadaTotal
            FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
            {SOFTLAND_OC_SALDO_AGG_APPLY}
            WHERE {where_sql}
            ORDER BY OC.NumOc DESC
            OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
            """,
            tuple(params + [row_offset, page_size + 1]),
        )
        oc_rows = cursor_s.fetchall()
        has_more = len(oc_rows) > page_size
        if has_more:
            oc_rows = oc_rows[:page_size]

        req_map = {}
        num_inter_values = [r[6] for r in oc_rows if len(r) > 6 and r[6] is not None]
        if num_inter_values:
            req_placeholders = ','.join(['?'] * len(num_inter_values))
            cursor_s.execute(
                f"""
                SELECT
                    Q.NumInterOC,
                    COALESCE(
                        MAX(NULLIF(LTRIM(RTRIM(R.Solicita)), '')),
                        MAX(NULLIF(LTRIM(RTRIM(S.DesSolic)), ''))
                    ) AS Solicitante
                FROM softland.owreqoc Q WITH (NOLOCK)
                LEFT JOIN softland.owrequisicion R WITH (NOLOCK) ON Q.NumReq = R.NumReq
                LEFT JOIN softland.owsolicitanterq S WITH (NOLOCK) ON R.CodSolicita = S.CodSolic
                WHERE Q.NumInterOC IN ({req_placeholders})
                GROUP BY Q.NumInterOC
                """,
                tuple(num_inter_values),
            )
            req_map = {row[0]: (row[1] or 'Sin requisición') for row in cursor_s.fetchall()}
    except Exception as exc:
        logger.error('faena_ordenes_cc Softland: %s', exc, exc_info=True)
        flash('No se pudo consultar Softland en este momento.', 'danger')
        return redirect(url_for('frontend.index'))
    finally:
        if conn_softland:
            conn_softland.close()

    filas = []
    conn_local = DatabaseConnection.get_connection()
    if conn_local and oc_rows:
        try:
            cursor = conn_local.cursor()
            _ensure_local_tracking_table(cursor, conn_local)
            conn_local.commit()
            folios = [int(r[0]) for r in oc_rows if r and r[0] is not None]
            tracking_local = _fetch_latest_tracking_rows_by_folio(cursor, folios)
            reception_summary_map = _load_reception_summary_by_folio(cursor, folios)
            pending_bodega_cc_map = _load_pending_bodega_dispatch_by_folio(cursor, folios)
            for oc in oc_rows:
                folio = int(oc[0])
                trk = tracking_local.get(folio)
                tiene_guia = bool(oc[7])
                qty_sol = float(oc[9] or 0)
                qty_ing = float(oc[10] or 0)
                if trk:
                    estado_tracking = _canonical_tracking_state(trk[1] or 'INGRESADO')
                elif tiene_guia:
                    estado_tracking = 'EN_BODEGA'
                else:
                    estado_tracking = 'PENDIENTE_EN_SOFTLAND'
                reception_status = reception_summary_map.get(folio, {}).get('status_label', 'No recepcionado')
                pend_cc = bool(pending_bodega_cc_map.get(folio, False))
                bodega_tracking_status = _bodega_dashboard_row_label(
                    estado_tracking,
                    _derive_bodega_tracking_status(qty_sol, qty_ing, pend_cc),
                    pend_cc,
                )
                filas.append({
                    'folio': folio,
                    'fecha_emision': _to_date(oc[1]),
                    'fecha_eta': _to_date(oc[2]),
                    'proveedor': oc[3] or 'Sin Proveedor',
                    'requisicion': req_map.get(oc[6], 'Sin requisición'),
                    'cc': oc[4] or 'Sin CC',
                    'monto': float(oc[5] or 0),
                    'estado_tracking': estado_tracking,
                    'reception_status': reception_status,
                    'bodega_tracking_status': bodega_tracking_status,
                })
        finally:
            conn_local.close()

    total_pages = max(1, (total_count + page_size - 1) // page_size) if total_count else 1
    return render_template(
        'faena_ordenes_cc.html',
        filas=filas,
        can_view_monto=is_super,
        page=page,
        page_size=page_size,
        has_more=has_more,
        has_previous=page > 1,
        total_count=total_count,
        total_pages=total_pages,
        filtro_desde=filtro_desde_raw,
        filtro_hasta=filtro_hasta_raw,
    )


@bp.route('/faena/requisiciones')
@login_required(roles=roles_for('faena_operations'))
def faena_requisiciones():
    """Requisiciones con OCs asociadas, acotadas al(los) centro(s) de costo del usuario FAENA."""
    from collections import defaultdict

    user_id = session.get('user_id')
    user_role = session.get('rol')
    is_super = has_any_role(user_role, ['SUPERADMIN'])
    faena_cc = None
    if not is_super:
        conn_u = DatabaseConnection.get_connection()
        if not conn_u:
            flash('Error de conexión', 'danger')
            return redirect(url_for('frontend.index'))
        try:
            cu = conn_u.cursor()
            _ensure_faena_cc_column(cu)
            conn_u.commit()
            cu.execute("SELECT CentrosCostoAsignados FROM UsuariosSistema WHERE Id = ?", (user_id,))
            urow = cu.fetchone()
            faena_cc = _normalize_cc_assignments(urow[0] if urow else '')
        finally:
            conn_u.close()
        if not faena_cc:
            flash('No tiene centros de costo asignados.', 'warning')
            return redirect(url_for('frontend.index'))

    num_req_raw = (request.args.get('num_req') or '').strip()

    where_parts = []
    params = []
    if faena_cc is not None:
        cc_match_sql, _ = _build_softland_cc_match_clause('O', len(faena_cc))
        where_parts.append(cc_match_sql)
        params.extend(faena_cc)
        params.extend(faena_cc)
    if num_req_raw:
        where_parts.append('CAST(Q.NumReq AS NVARCHAR(50)) LIKE ?')
        escaped = num_req_raw.replace('%', '[%]').replace('_', '[_]')
        params.append(f'%{escaped}%')
    where_sql = ' AND '.join(where_parts) if where_parts else '1=1'

    grouped = []
    conn_softland = None
    try:
        conn_softland = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
        cursor = conn_softland.cursor()
        cursor.execute(
            f"""
            SELECT
                Q.NumReq,
                O.NumOC,
                COALESCE(TRY_CONVERT(date, O.FechaOC, 103), TRY_CONVERT(date, O.FechaOC)) AS FechaOC,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(O.DescCC)), ''),
                    NULLIF(LTRIM(RTRIM(O.CodiCC)), ''),
                    'Sin CC'
                ) AS CentroCosto
            FROM softland.owreqoc Q WITH (NOLOCK)
            JOIN softland.owordencom O WITH (NOLOCK) ON Q.NumInterOC = O.NumInterOC
            WHERE {where_sql}
            ORDER BY Q.NumReq DESC, O.NumOC DESC
            """,
            tuple(params),
        )
        rows = cursor.fetchall()
        by_req = defaultdict(list)
        for r in rows:
            if not r or r[0] is None:
                continue
            num_req = r[0]
            by_req[num_req].append({
                'num_oc': int(r[1]) if r[1] is not None else None,
                'fecha_oc': r[2],
                'cc': r[3] or 'Sin CC',
            })
        def _sort_req_item(item):
            k = item[0]
            try:
                return (0, -int(k))
            except (TypeError, ValueError):
                return (1, str(k or ''))

        grouped = sorted(by_req.items(), key=_sort_req_item)
    except Exception as exc:
        logger.error('faena_requisiciones: %s', exc, exc_info=True)
        flash('No se pudo consultar requisiciones en Softland.', 'danger')
        return redirect(url_for('frontend.index'))
    finally:
        if conn_softland:
            conn_softland.close()

    return render_template(
        'faena_requisiciones.html',
        grouped=grouped,
        num_req_filter=num_req_raw,
    )


# ============================================
# RUTAS PARA TRANSPORTISTAS
# ============================================

@bp.route('/transportista/entregas')
@login_required(roles=roles_for('faena_operations'))
def mis_entregas():
    """Lista entregas pendientes asignadas (fuente local robusta)."""
    user_role = session.get('rol')
    if has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN']):
        # Interfaz unificada FAENA: evitar volver a la vista legacy con navbar antiguo.
        tracking_estado = (request.args.get('tracking_estado') or '').strip()
        redirect_params = {}
        if tracking_estado in ('en_ruta', 'entregado'):
            redirect_params['tracking_estado'] = tracking_estado
        return redirect(url_for('frontend.index', **redirect_params))
    try:
        conn = DatabaseConnection.get_connection()
        if not conn:
            flash('Error de conexión', 'danger')
            return redirect(url_for('frontend.index'))

        try:
            cursor = conn.cursor()
            _ensure_local_tracking_table(cursor, conn)
            conn.commit()
            user_role = session.get('rol')
            user_id = session.get('user_id')
            desde = (request.args.get('desde') or '').strip()
            hasta = (request.args.get('hasta') or '').strip()

            _xp = _sql_case_linea_despacho_parcial_bodega("X")
            query_local = f"""
                SELECT
                    E.NumOc AS FolioOC,
                    COALESCE(NULLIF(LTRIM(RTRIM(E.Transportista)), ''), 'Despacho Asignado') AS NomProv,
                    E.FechaHoraSalida AS FechaDespacho,
                    E.Estado,
                    E.Estado AS EstadoGeneral,
                    COALESCE(E.GuiaDespacho, 'N/A') AS GuiaDespacho,
                    COALESCE(E.Transportista, 'N/A') AS Transportista,
                    E.UrlFotoEvidencia,
                    (
                        CASE
                            WHEN E.EntregaParcialBodega = 1 THEN 1
                            ELSE COALESCE((
                                SELECT MAX(CASE WHEN {_xp} THEN 1 ELSE 0 END)
                                FROM DespachosEnvioDetalle X
                                WHERE X.EnvioId = E.Id
                            ), 0)
                        END
                    ) AS TieneParcial,
                    E.Id AS EnvioId
                FROM DespachosEnvio E
                WHERE UPPER(LTRIM(RTRIM(REPLACE(E.Estado, '_', ' ')))) IN ('EN RUTA', 'ENTREGADO')
            """
            params_local = []
            if desde:
                query_local += " AND CAST(COALESCE(E.FechaHoraEntrega, E.FechaHoraSalida) AS date) >= ?"
                params_local.append(desde)
            if hasta:
                query_local += " AND CAST(COALESCE(E.FechaHoraEntrega, E.FechaHoraSalida) AS date) <= ?"
                params_local.append(hasta)
            if has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN']):
                query_local += " AND E.transportista_asignado_id = ?"
                params_local.append(user_id)

            query_local += """
                ORDER BY
                    CASE WHEN UPPER(LTRIM(RTRIM(REPLACE(E.Estado, '_', ' ')))) = 'EN RUTA' THEN 0 ELSE 1 END,
                    COALESCE(E.FechaHoraEntrega, E.FechaHoraSalida) DESC
            """
            cursor.execute(query_local, params_local)
            entregas_raw = cursor.fetchall()
            reception_map = _load_reception_summary_by_folio(cursor, [e[0] for e in entregas_raw])
            entregas = [
                (
                    e[0], e[1], e[2],
                    _canonical_tracking_state(e[3]),
                    e[4], e[5], e[6], (_resolve_evidence_url(cursor, e[0], e[7], envio_id=e[9]) or e[7]), bool(e[8] or 0),
                    reception_map.get(int(e[0]), {}).get('status_label', 'No recepcionado'),
                    int(e[9]) if e[9] is not None else None,
                ) for e in entregas_raw
            ]
            total_en_ruta = sum(1 for e in entregas if _state_in(e[3], ('En Ruta',)))
            total_entregadas = sum(1 for e in entregas if _state_in(e[3], ('Entregado',)))
            return render_template(
                'mis_entregas.html',
                entregas=entregas,
                total_en_ruta=total_en_ruta,
                total_entregadas=total_entregadas,
                filtro_desde=desde,
                filtro_hasta=hasta
            )

        finally:
            conn.close()

    except Exception as e:
        logger.error("Error en mis_entregas: %s", e, exc_info=True)
        flash('Error al cargar entregas', 'danger')
        return redirect(url_for('frontend.index'))

@bp.route(
    '/transportista/entregar/envio/<int:envio_id>',
    methods=['GET', 'POST'],
    endpoint='recibir_producto_envio',
)
@login_required(roles=roles_for('faena_operations'))
def recibir_producto(envio_id):
    """Recepción en faena por envío (cada despacho de bodega es un registro independiente)."""
    try:
        conn = DatabaseConnection.get_connection()
        if not conn:
            flash('Error de conexión', 'danger')
            return redirect(url_for('frontend.index'))

        try:
            cursor = conn.cursor()
            _ensure_local_tracking_table(cursor, conn)
            conn.commit()
            user_role = session.get('rol')
            user_id = session.get('user_id')
            next_url = _sanitize_next_url(request.form.get('next') or request.args.get('next') or '')
            default_list_url = next_url or url_for('frontend.index')

            cursor.execute("""
                SELECT E.Id, E.NumOc, E.Estado, E.Transportista, E.PatenteVehiculo, E.GuiaDespacho, E.UrlFotoEvidencia,
                       E.transportista_asignado_id, E.Observaciones
                FROM DespachosEnvio E
                WHERE E.Id = ?
            """, (envio_id,))
            envio_row = cursor.fetchone()
            if not envio_row:
                flash('Envío no encontrado.', 'danger')
                return redirect(default_list_url)

            folio = int(envio_row[1])
            if has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN']):
                assigned_to_user = (envio_row[7] == user_id)
                cc_ok = _faena_user_has_cc_access_to_folio(user_id, folio)
                if not assigned_to_user and not cc_ok:
                    flash('No autorizado para recepcionar este envío (centro de costo o asignación).', 'danger')
                    return redirect(default_list_url)

            if request.method == 'POST':
                saved_photo_path = None
                try:
                    geo = (request.form.get('geolocation') or '').strip()
                    guia_ingresada = (request.form.get('guia_verificada') or '').strip()
                    observaciones_recepcion = (request.form.get('observaciones_recepcion') or '').strip()
                    receive_form_url = url_for('frontend.recibir_producto_envio', envio_id=envio_id, next=next_url)

                    if not verify_recepcion_form_token(
                        session, envio_id, request.form.get('recepcion_form_token')
                    ):
                        flash(
                            'Formulario expirado o ya fue enviado. Actualice la página e intente de nuevo.',
                            'warning',
                        )
                        return redirect(receive_form_url)

                    if not _state_in(envio_row[2], (ST_EN_RUTA,)):
                        flash('Este envío ya no está en ruta.', 'warning')
                        return redirect(default_list_url)

                    guia_registrada = (envio_row[5] or '').strip()
                    if not guia_ingresada:
                        flash('Debe ingresar el número de guía de despacho para confirmar la recepción.', 'warning')
                        return redirect(receive_form_url)
                    if guia_registrada and guia_ingresada != guia_registrada:
                        flash('La guía ingresada no coincide con la guía de despacho registrada.', 'danger')
                        return redirect(receive_form_url)
                    if len(observaciones_recepcion) < 8:
                        flash('Debe ingresar observaciones de recepción (mínimo 8 caracteres).', 'warning')
                        return redirect(receive_form_url)

                    foto = request.files.get('foto')
                    if not foto:
                        flash('Debe adjuntar una foto de evidencia para completar la recepción.', 'warning')
                        return redirect(receive_form_url)
                    if not allowed_file(foto):
                        flash('Formato de foto no permitido. Usa PNG/JPG/JPEG/WEBP/HEIC.', 'warning')
                        return redirect(receive_form_url)

                    cursor.execute("""
                        SELECT Id, NumLineaOc, CodProd, DescripcionProd, CantidadEnviada
                        FROM DespachosEnvioDetalle
                        WHERE EnvioId = ?
                        ORDER BY NumLineaOc, Id
                    """, (envio_id,))
                    detail_rows = cursor.fetchall()

                    # --- Recepción parcial por línea ---
                    line_updates = []
                    has_partial = False
                    has_rejected = False
                    _TOL = Decimal('0.0001')
                    for row in detail_rows:
                        det_id = row[0]
                        num_linea = row[1]
                        cod_prod = row[2] or 'N/A'
                        qty_enviada = Decimal(str(row[4] or 0))

                        qty_input = (request.form.get(f'cantidad_recibida_{det_id}') or '').strip()
                        motivo = (request.form.get(f'motivo_rechazo_{det_id}') or '').strip()
                        try:
                            qty_recibida = Decimal(qty_input)
                            if qty_recibida < 0:
                                qty_recibida = Decimal('0')
                            if qty_recibida > qty_enviada:
                                qty_recibida = qty_enviada
                        except Exception:
                            # Campo vacío o inválido: requiere valor explícito para evitar
                            # marcar todo como recibido por un form malformado.
                            if not qty_input:
                                flash(
                                    f'Debe indicar la cantidad recibida para el producto '
                                    f'{cod_prod} (línea {num_linea or "-"}).',
                                    'warning',
                                )
                                return redirect(receive_form_url)
                            # Valor no numérico con motivo → rechazo; sin motivo → error
                            if motivo:
                                qty_recibida = Decimal('0')
                            else:
                                flash(
                                    f'Cantidad no válida para el producto {cod_prod} (línea {num_linea or "-"}).',
                                    'warning',
                                )
                                return redirect(receive_form_url)

                        if qty_enviada <= _TOL:
                            estado_linea = LST_ENTREGADO
                        elif qty_recibida >= qty_enviada - _TOL:
                            estado_linea = LST_ENTREGADO
                        elif qty_recibida > _TOL:
                            estado_linea = LST_PARCIAL
                            has_partial = True
                            if not motivo:
                                flash(
                                    f'Debe indicar el motivo para la recepción parcial del '
                                    f'producto {cod_prod} (línea {num_linea or "-"}).',
                                    'warning'
                                )
                                return redirect(receive_form_url)
                        else:
                            estado_linea = LST_RECHAZADO
                            has_rejected = True
                            if not motivo:
                                flash(
                                    f'Debe indicar el motivo de rechazo para el producto '
                                    f'{cod_prod} (línea {num_linea or "-"}).',
                                    'warning'
                                )
                                return redirect(receive_form_url)

                        line_updates.append((det_id, qty_recibida, motivo or None, estado_linea))

                    if line_updates and all(lu[3] == LST_RECHAZADO for lu in line_updates):
                        flash(
                            'Debe aceptar al menos un producto. Si ningún artículo llegó, '
                            'contacte a Bodega para gestionar la devolución.',
                            'warning'
                        )
                        return redirect(receive_form_url)

                    cursor.execute(
                        """
                        SELECT Id FROM DespachosEnvio WITH (UPDLOCK, ROWLOCK)
                        WHERE Id = ?
                          AND UPPER(LTRIM(RTRIM(REPLACE(Estado, '_', ' ')))) = 'EN RUTA'
                        """,
                        (envio_id,),
                    )
                    if not cursor.fetchone():
                        flash('Este envío ya no está en ruta o está siendo procesado por otra sesión.', 'warning')
                        return redirect(receive_form_url)

                    safe_name = secure_filename(foto.filename or '')
                    ext = os.path.splitext(safe_name)[1].lower()
                    if not ext:
                        mime_to_ext = {
                            'image/jpeg': '.jpg',
                            'image/jpg': '.jpg',
                            'image/png': '.png',
                            'image/webp': '.webp',
                            'image/heic': '.heic',
                            'image/heif': '.heif',
                        }
                        ext = mime_to_ext.get((foto.mimetype or '').lower(), '.jpg')
                    filename = f"entrega_{folio}_e{envio_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
                    saved_photo_path = os.path.join(_get_evidence_upload_dir(), filename)
                    foto.save(saved_photo_path)
                    foto_url = url_for('frontend.get_evidencia', filename=filename)
                    prev_urls = _parse_evidencia_urls_field(envio_row[6])
                    merged_urls = list(prev_urls) + [foto_url]
                    merged_foto = merged_urls[0] if len(merged_urls) == 1 else json.dumps(merged_urls, ensure_ascii=False)

                    cursor.execute("""
                        UPDATE DespachosEnvio SET
                            Estado = ?,
                            FechaHoraEntrega = GETDATE(),
                            UrlFotoEvidencia = COALESCE(?, UrlFotoEvidencia),
                            Observaciones = CASE
                                WHEN ? IS NOT NULL AND LEN(?) > 0 THEN
                                    CONCAT(
                                        COALESCE(Observaciones, ''),
                                        CASE WHEN Observaciones IS NULL OR Observaciones = '' THEN '' ELSE ' | ' END,
                                        'Recepción Faena: ',
                                        ?,
                                        CASE WHEN ? IS NOT NULL AND LEN(?) > 0 THEN CONCAT(' | Geo:', ?) ELSE '' END
                                    )
                                WHEN ? IS NOT NULL AND LEN(?) > 0 THEN
                                    CONCAT(COALESCE(Observaciones, ''), CASE WHEN Observaciones IS NULL OR Observaciones = '' THEN '' ELSE ' | ' END, 'Geo:', ?)
                                ELSE Observaciones
                            END
                        WHERE Id = ?
                          AND UPPER(LTRIM(RTRIM(REPLACE(Estado, '_', ' ')))) = 'EN RUTA'
                    """, (
                        ST_ENTREGADO,
                        merged_foto,
                        observaciones_recepcion,
                        observaciones_recepcion,
                        observaciones_recepcion,
                        geo,
                        geo,
                        geo,
                        geo,
                        geo,
                        geo,
                        envio_id,
                    ))
                    if cursor.rowcount == 0:
                        conn.rollback()
                        flash('No se pudo cerrar el envío (estado ya actualizado).', 'warning')
                        return redirect(default_list_url)

                    # Acumular líneas problemáticas para notificación
                    lineas_problema = []

                    # Actualizar cada línea con su cantidad e estado real
                    for det_id, qty_recibida, motivo, estado_linea in line_updates:
                        cursor.execute("""
                            UPDATE DespachosEnvioDetalle
                            SET EstadoLinea = ?,
                                CantidadRecibida = ?,
                                MotivoRechazo = ?,
                                FechaRecepcion = GETDATE(),
                                RecibidoPor = ?
                            WHERE Id = ?
                              AND EnvioId = ?
                        """, (estado_linea, qty_recibida, motivo, user_id, det_id, envio_id))

                        # Si es PARCIAL o RECHAZADO, agregar a lista para notificación
                        if estado_linea in (LST_PARCIAL, LST_RECHAZADO):
                            # Encontrar la línea original para obtener datos
                            for row in detail_rows:
                                if row[0] == det_id:
                                    lineas_problema.append({
                                        'num_oc': folio,
                                        'cod_prod': row[2] or 'N/A',
                                        'desc_prod': row[3] or 'Sin descripción',
                                        'cant_enviada': float(row[4] or 0),
                                        'cant_recibida': float(qty_recibida),
                                        'motivo': motivo,
                                        'estado_linea': estado_linea,
                                        'recibido_por': session.get('nombre', session.get('username', 'Desconocido'))
                                    })
                                    break

                    # Marcar cabecera si hubo recepción parcial o rechazo de alguna línea
                    is_parcial_faena = has_partial or has_rejected
                    cursor.execute(
                        "UPDATE DespachosEnvio SET RecepcionParcialFaena = ? WHERE Id = ?",
                        (1 if is_parcial_faena else 0, envio_id)
                    )

                    softland_items = _load_softland_oc_items(folio)
                    _sync_despachos_tracking_header(cursor, conn, folio, softland_items)

                    # Crear notificaciones de discrepancias para bodega
                    if lineas_problema:
                        _crear_notificaciones_bodega(conn, envio_id, guia_registrada, lineas_problema)

                    conn.commit()
                    consume_recepcion_form_token(session, envio_id)
                    logger.info(f"Entrega registrada: Envío {envio_id}, OC {folio}, Usuario {user_id}, parcial={is_parcial_faena}")
                    if is_parcial_faena:
                        flash('✓ Recepción parcial registrada. Productos faltantes o dañados quedan documentados.', 'success')
                    else:
                        flash('✓ ¡Producto recibido exitosamente!', 'success')

                except Exception as e:
                    conn.rollback()
                    if saved_photo_path and os.path.exists(saved_photo_path):
                        try:
                            os.remove(saved_photo_path)
                        except Exception:
                            logger.warning("No se pudo eliminar evidencia temporal: %s", saved_photo_path)
                    logger.error("Error en recepción: %s", e, exc_info=True)
                    flash('Error interno al registrar la recepción. Intente nuevamente.', 'danger')

                return redirect(default_list_url)

            if not _state_in(envio_row[2], (ST_EN_RUTA, ST_ENTREGADO)):
                flash('Envío no disponible para recepción.', 'danger')
                return redirect(default_list_url)

            cursor.execute("""
                SELECT Id, NumLineaOc, CodProd, DescripcionProd, CantidadEnviada, EstadoLinea
                FROM DespachosEnvioDetalle
                WHERE EnvioId = ?
                ORDER BY NumLineaOc, Id
            """, (envio_id,))
            despacho_raw = cursor.fetchall()
            qty_rec_map = _map_cantidad_recibida_faena_por_linea_oc(cursor, folio)
            despacho_items = [
                tuple(row) + (float(qty_rec_map.get(_faena_line_key(row[1], row[2]), 0.0)),)
                for row in despacho_raw
            ]

            fotos_bodega = _resolve_evidence_urls_all(cursor, folio, envio_row[6], envio_id=envio_id)
            foto_single = (
                fotos_bodega[0]
                if fotos_bodega
                else (_resolve_evidence_url(cursor, folio, envio_row[6], envio_id=envio_id) or envio_row[6])
            )
            envios_oc_raw = _load_envios_agrupados_por_guia(cursor, folio) or []
            envios_oc = []
            envios_oc_kpis = {
                "total_guias": 0,
                "en_ruta": 0,
                "entregadas": 0,
                "total_enviado": 0.0,
                "total_fotos": 0,
            }
            for bucket in envios_oc_raw:
                ev = bucket.get("envio") if isinstance(bucket, dict) else None
                if not ev:
                    continue
                lineas = list(bucket.get("lineas") or [])
                total_enviado = 0.0
                for li in lineas:
                    try:
                        # (línea, cod, desc, qty_prog, qty_env, estado)
                        q_env = float(li[4] if len(li) > 4 else (li[3] if len(li) > 3 else 0) or 0)
                        total_enviado += q_env
                    except Exception:
                        continue
                estado_norm = _canonical_tracking_state(ev[3])
                fotos = list(bucket.get("fotos") or [])
                envios_oc_kpis["total_guias"] += 1
                envios_oc_kpis["total_enviado"] += total_enviado
                envios_oc_kpis["total_fotos"] += len(fotos)
                if _state_in(estado_norm, ("En Ruta",)):
                    envios_oc_kpis["en_ruta"] += 1
                elif _state_in(estado_norm, ("Entregado",)):
                    envios_oc_kpis["entregadas"] += 1
                envios_oc.append(
                    {
                        "envio_id": int(ev[0]) if ev[0] is not None else None,
                        "guia": (ev[1] or "").strip(),
                        "fecha_salida": ev[2],
                        "estado": estado_norm,
                        "transportista": ev[4],
                        "patente": ev[5],
                        "fotos": fotos,
                        "lineas": lineas,
                        "total_enviado": total_enviado,
                        "lineas_count": len(lineas),
                        "fotos_count": len(fotos),
                        "is_current": int(ev[0]) == int(envio_id),
                    }
                )
            envios_oc.sort(
                key=lambda x: (
                    0 if x.get("is_current") else 1,
                    0 if _state_in(x.get("estado"), ("En Ruta",)) else 1,
                    0 - int(x.get("envio_id") or 0),
                )
            )
            recepcion_form_token = mint_recepcion_form_token(session, envio_id)
            return render_template(
                'recibir_producto.html',
                envio_id=envio_id,
                folio=folio,
                estado=_canonical_tracking_state(envio_row[2]),
                foto_url=foto_single,
                fotos_urls=fotos_bodega,
                transportista=envio_row[3],
                patente_vehiculo=envio_row[4],
                guia=envio_row[5],
                despacho_items=despacho_items,
                envios_oc=envios_oc,
                envios_oc_kpis=envios_oc_kpis,
                next_url=next_url,
                recepcion_form_token=recepcion_form_token,
            )

        finally:
            conn.close()

    except Exception as e:
        logger.error("Error en recibir_producto: %s", e, exc_info=True)
        flash('Error inesperado', 'danger')
        return redirect(url_for('frontend.index'))


@bp.route(
    '/transportista/entregar/<int:folio>',
    methods=['GET', 'POST'],
    endpoint='recibir_producto_folio_legacy',
)
@login_required(roles=roles_for('faena_operations'))
def recibir_producto_legacy_por_folio(folio):
    """Compatibilidad: redirige o permite elegir envío de la OC."""
    if request.method == 'POST':
        flash('Abra la recepción desde el listado (cada envío tiene su propio enlace).', 'warning')
        return redirect(url_for('frontend.index'))
    try:
        conn = DatabaseConnection.get_connection()
        if not conn:
            return redirect(url_for('frontend.index'))
        try:
            cursor = conn.cursor()
            _ensure_local_tracking_table(cursor, conn)
            conn.commit()
            user_role = session.get('rol')
            user_id = session.get('user_id')
            next_url = _sanitize_next_url(request.args.get('next') or '')

            sql = """
                SELECT E.Id, E.Estado, E.GuiaDespacho, E.PatenteVehiculo, E.FechaHoraSalida
                FROM DespachosEnvio E
                WHERE E.NumOc = ?
                  AND UPPER(LTRIM(RTRIM(REPLACE(E.Estado, '_', ' ')))) IN ('EN RUTA', 'ENTREGADO')
            """
            params = [folio]
            if has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN']):
                cc_folio = _faena_user_has_cc_access_to_folio(user_id, folio)
                if cc_folio:
                    # Con CC en la OC puede recepcionar cualquier guía en ruta de este folio (no solo la asignada).
                    pass
                else:
                    cursor.execute("""
                        SELECT 1
                        FROM DespachosEnvio
                        WHERE NumOc = ? AND transportista_asignado_id = ?
                    """, (folio, user_id))
                    if not cursor.fetchone():
                        flash('No autorizado para este centro de costo.', 'danger')
                        return redirect(url_for('frontend.index'))
                    sql += " AND E.transportista_asignado_id = ?"
                    params.append(user_id)
            sql += """
                ORDER BY
                    CASE
                        WHEN UPPER(LTRIM(RTRIM(REPLACE(E.Estado, '_', ' ')))) = 'EN RUTA' THEN 0
                        WHEN UPPER(LTRIM(RTRIM(REPLACE(E.Estado, '_', ' ')))) = 'ENTREGADO' THEN 1
                        ELSE 2
                    END,
                    E.Id DESC
            """
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            if not rows:
                raise LookupError("Sin envíos disponibles para el folio")

            envios_en_ruta = [r for r in rows if _state_in(r[1], ('En Ruta',))]
            if len(envios_en_ruta) == 1:
                return redirect(url_for('frontend.recibir_producto_envio', envio_id=int(envios_en_ruta[0][0]), next=next_url))
            if len(envios_en_ruta) > 1:
                return redirect(url_for('frontend.recibir_producto_envio', envio_id=int(envios_en_ruta[0][0]), next=next_url))

            first = rows[0]
            if first and first[0] is not None:
                return redirect(url_for('frontend.recibir_producto_envio', envio_id=int(first[0]), next=next_url))
        finally:
            conn.close()
    except Exception:
        logger.warning("Error en recibir_producto_legacy_por_folio (folio=%s)", folio, exc_info=True)
    flash('No hay envío en ruta para esta OC. Use Recepciones Faena para ver envíos abiertos.', 'warning')
    return redirect(url_for('frontend.index'))
