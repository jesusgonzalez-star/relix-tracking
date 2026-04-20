"""Dashboard principal – rutas / y /admin/reset-local-tracking."""

import logging
import time
from datetime import datetime, date

from flask import (
    render_template, request, redirect, url_for, flash,
    session, jsonify,
)
import pyodbc

from utils.auth import login_required, has_any_role
from utils.permissions import roles_for
from utils.db_legacy import DatabaseConnection
from repositories.local_db import local_db_transaction
from config import SoftlandConfig
from services.softland_sql_fragments import SOFTLAND_OC_SALDO_AGG_APPLY
from routes.frontend import bp
from routes.frontend._helpers import (
    logger,
    _DASHBOARD_PAGE_SIZE,
    _DASHBOARD_FILTER_IDS_CAP,
    _ensure_local_tracking_table,
    _ensure_faena_cc_column,
    _normalize_cc_assignments,
    _get_folios_by_centros_costo,
    _folio_matches_centros_costo_tokens,
    _fetch_latest_tracking_rows_by_folio,
    _load_partial_flags_by_folio,
    _load_reception_summary_by_folio,
    _load_active_envio_id_by_folio,
    _load_pending_bodega_dispatch_by_folio,
    _load_sent_totals_by_folio,
    _canonical_tracking_state,
    _normalize_state_value,
    _state_in,
    _build_eta_badge,
    _to_date,
    _parse_iso_date,
    _resolve_softland_column,
    _sanitize_next_url,
    _erp_scopes_softland_by_aux,
    _label_fecha_tipo_bodega,
    _build_bodega_fecha_where_prefix,
    _append_req_filter_to_parts,
    _append_num_oc_filter_to_parts,
    _get_softland_dashboard_cache,
    _set_softland_dashboard_cache,
    _bodega_dashboard_row_label,
    _bodega_dashboard_estado_passes_filter,
    _faena_matches_tracking_estado,
    _faena_trk_row_passes_dashboard_sql_filters,
    _faena_softland_req_labels_map,
    _folios_entrega_parcial_bodega_safe,
    _load_master_data_entrega_parcial_faena,
    _folios_tracking_en_ruta,
    _folios_tracking_entregado,
    _folios_local_recepcion_parcial,
    _folios_local_recepcion_rechazada,
    _sql_where_column_in_ints,
    _master_data_entrega_parcial_sin_softland,
    _derive_bodega_tracking_status,
    _load_softland_oc_items,
    _sync_despachos_tracking_header,
    _dashboard_centros_costo_opciones,
    _dashboard_centros_costo_opciones_faena,
)


# ============================================
# DASHBOARD PRINCIPAL (MEJORADO)
# ============================================


def _dashboard_faena(ctx):
    """Dashboard para perfil FAENA (filtrado por CC y asignación directa)."""
    cursor = ctx["cursor"]; conn = ctx["conn"]; user_role = ctx["user_role"]; user_id = ctx["user_id"]
    faena_cc_asignados = ctx["faena_cc_asignados"]
    filtro_desde_raw = ctx["filtro_desde_raw"]; filtro_hasta_raw = ctx["filtro_hasta_raw"]
    filtro_desde_date = ctx["filtro_desde_date"]; filtro_hasta_date = ctx["filtro_hasta_date"]
    tracking_estado_raw = ctx["tracking_estado_raw"]; fecha_tipo_raw = ctx["fecha_tipo_raw"]
    cc_filter_raw = ctx["cc_filter_raw"]; cc_filter_token = ctx["cc_filter_token"]
    num_req_filtro_raw = ctx["num_req_filtro_raw"]; num_oc_filtro_raw = ctx["num_oc_filtro_raw"]
    page = ctx["page"]; page_size = ctx["page_size"]; row_offset = ctx["row_offset"]
    current_list_url = ctx["current_list_url"]
    # Solo los estados operativos acordados para perfil FAENA (sin no_entregado / ERP / entregado sueltos).
    faena_tracking_allowed = {
        '',
        'recepcion_parcial',
        'recepcion_rechazada',
        'recepcion_completa',
        'entrega_parcial_faena',
        'en_ruta',
        'envio_completo_en_ruta',
    }
    if tracking_estado_raw not in faena_tracking_allowed:
        tracking_estado_raw = ''
    faena_sql_estado_filter = tracking_estado_raw if tracking_estado_raw in ('en_ruta', 'entregado') else ''
    if tracking_estado_raw == 'envio_completo_en_ruta':
        faena_sql_estado_filter = 'en_ruta'
    if tracking_estado_raw == 'recepcion_completa':
        # Recepción completa en faena implica cierre entregado.
        faena_sql_estado_filter = 'entregado'
    faena_where_extra = ""
    faena_params_extra = []
    if fecha_tipo_raw == 'entrega_faena':
        if filtro_desde_date:
            faena_where_extra += (
                " AND D.FechaHoraEntrega IS NOT NULL"
                " AND DATE(D.FechaHoraEntrega) >= ?"
            )
            faena_params_extra.append(filtro_desde_raw)
        if filtro_hasta_date:
            faena_where_extra += (
                " AND D.FechaHoraEntrega IS NOT NULL"
                " AND DATE(D.FechaHoraEntrega) <= ?"
            )
            faena_params_extra.append(filtro_hasta_raw)
    else:
        if filtro_desde_date:
            faena_where_extra += (
                " AND DATE(COALESCE(D.FechaHoraEntrega, D.FechaHoraSalida)) >= ?"
            )
            faena_params_extra.append(filtro_desde_raw)
        if filtro_hasta_date:
            faena_where_extra += (
                " AND DATE(COALESCE(D.FechaHoraEntrega, D.FechaHoraSalida)) <= ?"
            )
            faena_params_extra.append(filtro_hasta_raw)
    faena_oc_filter_sql = ""
    faena_oc_filter_params = []
    if num_oc_filtro_raw.isdigit():
        faena_oc_filter_sql = " AND D.NumOc = ?"
        faena_oc_filter_params.append(int(num_oc_filtro_raw))
    effective_cc_tokens = []
    selected_cc_mode = bool(cc_filter_token and cc_filter_token in set(faena_cc_asignados))
    if selected_cc_mode:
        effective_cc_tokens = [cc_filter_token]
    elif cc_filter_token and cc_filter_token not in set(faena_cc_asignados):
        # CC seleccionado no está en las asignaciones del usuario: ignorar filtro inválido.
        cc_filter_token = ''
        cc_filter_raw = ''
        if faena_cc_asignados:
            effective_cc_tokens = list(dict.fromkeys(faena_cc_asignados))
    elif faena_cc_asignados:
        effective_cc_tokens = list(dict.fromkeys(faena_cc_asignados))

    faena_folios_for_visibility = set()
    num_oc_only = int(num_oc_filtro_raw) if num_oc_filtro_raw.isdigit() else None
    if num_oc_only is not None:
        if effective_cc_tokens and _folio_matches_centros_costo_tokens(
            num_oc_only, effective_cc_tokens
        ):
            faena_folios_for_visibility = {num_oc_only}
    elif effective_cc_tokens:
        faena_folios_for_visibility = _get_folios_by_centros_costo(effective_cc_tokens)

    logger.info(
        "FAENA dashboard: user=%s, cc_asignados=%d, effective_cc=%d, "
        "selected_cc=%r, folios_cc=%d",
        user_id, len(faena_cc_asignados), len(effective_cc_tokens),
        cc_filter_token or '(todos)', len(faena_folios_for_visibility),
    )

    faena_visibility_clause = "D.transportista_asignado_id = ?"
    faena_visibility_params = [user_id]
    if faena_folios_for_visibility:
        folios_csv = ",".join(str(int(x)) for x in sorted(faena_folios_for_visibility))
        if selected_cc_mode:
            # Filtro de CC explícito en FAENA: comportamiento estricto.
            folios_int_list = [int(x) for x in folios_csv.split(',') if x.strip().isdigit()]
            placeholders_vis = ",".join(["?"] * len(folios_int_list))
            faena_visibility_clause = f"""
                D.NumOc IN ({placeholders_vis})
            """
            faena_visibility_params = list(folios_int_list)
        else:
            # Modo general FAENA: asignados directos + CC permitidos.
            folios_int_list = [int(x) for x in folios_csv.split(',') if x.strip().isdigit()]
            placeholders_vis = ",".join(["?"] * len(folios_int_list))
            faena_visibility_clause = f"""
                (
                    D.transportista_asignado_id = ?
                    OR D.NumOc IN ({placeholders_vis})
                )
            """
            faena_visibility_params.extend(folios_int_list)

    # Unión ERP (CC asignados) ∪ OCs con envío asignado al usuario: incluye OCs sin fila local aún.
    cursor.execute(
        """
        SELECT U.NumOc
        FROM (
            SELECT
                NumOc,
                transportista_asignado_id,
                ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
            FROM DespachosTracking
        ) U
        WHERE U.rn = 1
          AND U.transportista_asignado_id = ?
        """,
        (user_id,),
    )
    faena_assigned_folio_set = {
        int(r[0]) for r in cursor.fetchall() if r and r[0] is not None
    }
    if num_oc_only is not None:
        faena_union_folios = set()
        if num_oc_only in faena_assigned_folio_set:
            faena_union_folios.add(num_oc_only)
        if num_oc_only in faena_folios_for_visibility:
            faena_union_folios.add(num_oc_only)
    elif selected_cc_mode:
        # Filtro CC estricto: solo OCs del CC seleccionado, sin mezclar asignaciones directas.
        faena_union_folios = set(faena_folios_for_visibility)
    else:
        faena_union_folios = set(faena_folios_for_visibility) | faena_assigned_folio_set

    faena_rp_partial_frozenset = frozenset()
    faena_rr_rechazada_frozenset = frozenset()
    if tracking_estado_raw == 'recepcion_parcial':
        try:
            _rp = set(_folios_local_recepcion_parcial(cursor, num_oc_filtro_raw))
            if num_oc_only is not None:
                _rp = {x for x in _rp if int(x) == int(num_oc_only)}
            # Incluir todas las OCs parciales detectadas en BD local: la intersección solo con
            # CC/asignación dejaba el filtro vacío cuando el ERP aún no refleja la misma vista.
            faena_rp_partial_frozenset = frozenset(_rp)
            faena_union_folios = faena_union_folios | _rp
        except Exception:
            faena_rp_partial_frozenset = frozenset()

    if tracking_estado_raw == 'recepcion_rechazada':
        try:
            _rr = set(_folios_local_recepcion_rechazada(cursor, num_oc_filtro_raw))
            if num_oc_only is not None:
                _rr = {x for x in _rr if int(x) == int(num_oc_only)}
            faena_rr_rechazada_frozenset = frozenset(_rr)
            faena_union_folios = faena_union_folios | _rr
        except Exception:
            faena_rr_rechazada_frozenset = frozenset()

    ordered_union = sorted(faena_union_folios, reverse=True)
    _faena_trk_chunk = 380
    trk_by_folio = {}
    for _i in range(0, len(ordered_union), _faena_trk_chunk):
        _chunk = ordered_union[_i : _i + _faena_trk_chunk]
        trk_by_folio.update(_fetch_latest_tracking_rows_by_folio(cursor, _chunk))

    filtered_faena_folios = []
    for _folio in ordered_union:
        _trk = trk_by_folio.get(_folio)
        if not _faena_trk_row_passes_dashboard_sql_filters(
            _trk,
            faena_sql_estado_filter,
            fecha_tipo_raw,
            filtro_desde_date,
            filtro_hasta_date,
            filtro_desde_raw,
            filtro_hasta_raw,
            folio_int=_folio,
            recepcion_parcial_folios=(
                faena_rp_partial_frozenset
                if tracking_estado_raw == 'recepcion_parcial'
                else None
            ),
            recepcion_rechazada_folios=(
                faena_rr_rechazada_frozenset
                if tracking_estado_raw == 'recepcion_rechazada'
                else None
            ),
        ):
            continue
        filtered_faena_folios.append(_folio)

    _win = filtered_faena_folios[row_offset : row_offset + page_size + 1]
    has_more = len(_win) > page_size
    _page_folios = _win[:page_size]

    local_rows = []
    for _folio in _page_folios:
        _trk = trk_by_folio.get(_folio)
        if _trk:
            local_rows.append(_trk)
        else:
            local_rows.append(
                (_folio, 'PENDIENTE_EN_SOFTLAND', None, None, None)
            )

    softland_map = {}
    folios_local = [int(row[0]) for row in local_rows if row and row[0] is not None]
    folios_scope = set(folios_local)
    # Importante: no recalcular/repaginar alcance FAENA aquí.
    # La consulta SQL de local_rows ya trae visibilidad + filtros + paginación correctos.

    trk_map = _fetch_latest_tracking_rows_by_folio(cursor, list(folios_scope))
    partial_map = _load_partial_flags_by_folio(cursor, list(folios_scope))
    reception_summary_map = _load_reception_summary_by_folio(cursor, list(folios_scope))
    active_envio_map_faena = _load_active_envio_id_by_folio(cursor, list(folios_scope))
    # Solo este filtro necesita remanente línea a línea vs ERP (costoso); el resto evita N× Softland.
    pending_bodega_map = {}
    if tracking_estado_raw == 'envio_completo_en_ruta':
        pending_bodega_map = _load_pending_bodega_dispatch_by_folio(cursor, list(folios_scope))

    def _faena_resolve_cc_exprs(cursor_sf_inner):
        cc_desc_col = _resolve_softland_column(
            cursor_sf_inner,
            'OW_vsnpTraeEncabezadoOCompra',
            ('DescCC', 'DesCC', 'CentroCosto', 'NomCC'),
        )
        cc_code_col = _resolve_softland_column(
            cursor_sf_inner,
            'OW_vsnpTraeEncabezadoOCompra',
            ('CodiCC', 'CodCC', 'CentroCosto', 'CCosto'),
        )
        cc_select_expr = "'Sin CC' AS CentroCosto"
        if cc_desc_col and cc_code_col:
            cc_select_expr = (
                f"COALESCE(NULLIF(LTRIM(RTRIM(OC.{cc_desc_col})), ''), "
                f"NULLIF(LTRIM(RTRIM(OC.{cc_code_col})), ''), 'Sin CC') AS CentroCosto"
            )
        elif cc_desc_col:
            cc_select_expr = (
                f"COALESCE(NULLIF(LTRIM(RTRIM(OC.{cc_desc_col})), ''), 'Sin CC') AS CentroCosto"
            )
        elif cc_code_col:
            cc_select_expr = (
                f"COALESCE(NULLIF(LTRIM(RTRIM(OC.{cc_code_col})), ''), 'Sin CC') AS CentroCosto"
            )
        cc_where_expr = "UPPER(LTRIM(RTRIM('SIN CC')))"
        if cc_desc_col and cc_code_col:
            cc_where_expr = (
                f"UPPER(LTRIM(RTRIM(COALESCE(NULLIF(OC.{cc_desc_col}, ''), "
                f"NULLIF(OC.{cc_code_col}, ''), 'SIN CC'))))"
            )
        elif cc_desc_col:
            cc_where_expr = (
                f"UPPER(LTRIM(RTRIM(COALESCE(NULLIF(OC.{cc_desc_col}, ''), 'SIN CC'))))"
            )
        elif cc_code_col:
            cc_where_expr = (
                f"UPPER(LTRIM(RTRIM(COALESCE(NULLIF(OC.{cc_code_col}, ''), 'SIN CC'))))"
            )
        return cc_select_expr, cc_where_expr

    conn_softland_faena = None
    try:

        conn_softland_faena = pyodbc.connect(
            SoftlandConfig.get_connection_string(), timeout=20
        )
        cursor_sf = conn_softland_faena.cursor()
        cc_select_expr, _ = _faena_resolve_cc_exprs(cursor_sf)

        if folios_scope:
            folio_list = sorted(int(f) for f in folios_scope)
            placeholders = ",".join(["?"] * len(folio_list))
            cursor_sf.execute(
                f"""
                SELECT
                    OC.NumOc,
                    COALESCE(TRY_CONVERT(date, OC.FechaOC, 103), TRY_CONVERT(date, OC.FechaOC)) AS FechaEmision,
                    COALESCE(TRY_CONVERT(date, OC.FecFinalOC, 103), TRY_CONVERT(date, OC.FecFinalOC)) AS FechaLlegadaEstimada,
                    COALESCE(OC.NomAux, 'Sin Proveedor') AS Proveedor,
                    {cc_select_expr},
                    ISNULL(OC.ValorTotMB, 0) AS MontoTotal,
                    OC.NumInterOc AS NumInterOC
                FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                WHERE OC.NumOc IN ({placeholders})
                """,
                tuple(folio_list),
            )
            oc_rows_loc = cursor_sf.fetchall()
            num_inters = []
            folios_sin_numinter = []
            for r in oc_rows_loc:
                if len(r) <= 6 or r[6] is None:
                    folios_sin_numinter.append(int(r[0]))
                    continue
                try:
                    num_inters.append(int(r[6]))
                except (TypeError, ValueError):
                    folios_sin_numinter.append(int(r[0]))
            folio_a_numinter = {}
            if folios_sin_numinter:
                ph_orden = ",".join(["?"] * len(folios_sin_numinter))
                cursor_sf.execute(
                    f"""
                    SELECT O.NumOC, O.NumInterOC
                    FROM softland.owordencom O WITH (NOLOCK)
                    WHERE O.NumOC IN ({ph_orden})
                      AND O.NumInterOC IS NOT NULL """,
                    tuple(folios_sin_numinter),
                )
                for ord_row in cursor_sf.fetchall():
                    try:
                        fo = int(ord_row[0])
                        ni = int(ord_row[1])
                        folio_a_numinter[fo] = ni
                        num_inters.append(ni)
                    except (TypeError, ValueError):
                        pass
            req_map = {}
            try:
                req_map = _faena_softland_req_labels_map(cursor_sf, num_inters)
            except Exception as req_exc:
                logger.warning(
                    "Faena: no se pudo cargar requisiciones por NumInterOC: %s",
                    req_exc,
                    exc_info=True,
                )
            for row_sf in oc_rows_loc:
                folio_sf = int(row_sf[0])
                num_inter_raw = row_sf[6] if len(row_sf) > 6 else None
                try:
                    num_inter_key = int(num_inter_raw) if num_inter_raw is not None else None
                except (TypeError, ValueError):
                    num_inter_key = None
                if num_inter_key is None:
                    num_inter_key = folio_a_numinter.get(folio_sf)
                softland_map[folio_sf] = {
                    'fecha_emision': _to_date(row_sf[1]),
                    'fecha_eta': _to_date(row_sf[2]),
                    'proveedor': row_sf[3] or 'Sin Proveedor',
                    'cc': row_sf[4] or 'Sin CC',
                    'monto': float(row_sf[5] or 0),
                    'requisicion': req_map.get(num_inter_key, 'Sin requisición'),
                }
    except Exception as exc:
        logger.warning(
            "No fue posible enriquecer vista faena con Softland en tiempo real: %s",
            exc,
            exc_info=True,
        )
    finally:
        if conn_softland_faena:
            try:
                conn_softland_faena.close()
            except Exception:
                pass

    ordenes = []
    folios_render = sorted(int(f) for f in folios_scope)
    folios_render.reverse()
    for folio in folios_render:
        trk = trk_map.get(folio)
        softland_row = softland_map.get(folio, {})
        estado_tracking = _canonical_tracking_state((trk[1] if trk else 'PENDIENTE_EN_SOFTLAND') or 'PENDIENTE_EN_SOFTLAND')
        is_dispatched_to_me = bool(trk and trk[4] == user_id)
        fecha_entrega = trk[3] if trk else None
        fecha_salida = trk[2] if trk else None
        eta_label, eta_class = _build_eta_badge(softland_row.get('fecha_eta'), estado_tracking, fecha_entrega)
        rec_sum = reception_summary_map.get(folio, {}) or {}
        reception_status = rec_sum.get('status_label', 'No recepcionado')
        need_qty_oc = float(rec_sum.get('need_qty') or 0)
        got_qty_oc = float(rec_sum.get('got_qty') or 0)
        erp_need_qty_oc = float(rec_sum.get('erp_need_qty') or 0)
        trace_pb_oc = bool(rec_sum.get('trace_parcial_envio_bodega'))
        # En FAENA, "recepción" debe reflejar solo recepción real en faena,
        # no el hecho de que esté En Ruta.
        has_any_arrival = reception_status in ('Recepcionado parcial', 'Recepcionado completo')
        bodega_tracking_status = (
            'Entrega total' if reception_status == 'Recepcionado completo' else
            'Recepción parcial' if has_any_arrival else
            'No entregado'
        )
        pend_f = bool(pending_bodega_map.get(folio, False))
        bodega_tracking_status = _bodega_dashboard_row_label(
            estado_tracking, bodega_tracking_status, pend_f
        )
        ordenes.append((
            folio,               # folio
            softland_row.get('fecha_emision'),  # fecha emision
            softland_row.get('fecha_eta'),      # fecha llegada estimada
            softland_row.get('proveedor', 'Tracking Local'),    # proveedor
            softland_row.get('requisicion', 'Sin requisición'),   # requisicion
            softland_row.get('monto', 0),       # monto
            'A',                 # placeholder
            estado_tracking,     # estado tracking
            None,
            fecha_salida,        # fecha salida
            fecha_entrega,       # fecha entrega
            0,
            0,
            softland_row.get('cc', 'Sin CC'),
            bool(partial_map.get(folio, 0)),
            reception_status,
            eta_label,
            eta_class,
            bodega_tracking_status,
            bool(has_any_arrival),
            bool(is_dispatched_to_me),
            active_envio_map_faena.get(folio),
            False,
            bool(pending_bodega_map.get(folio, False)),
            need_qty_oc,
            got_qty_oc,
            erp_need_qty_oc,
            trace_pb_oc,
        ))
    ordenes = [
        o for o in ordenes if _faena_matches_tracking_estado(
            o, tracking_estado_raw,
            recepcion_rechazada_folios=faena_rr_rechazada_frozenset if tracking_estado_raw == 'recepcion_rechazada' else None,
        )
    ]

    # Estadísticas consistentes con los folios realmente visibles (incluye CC de Softland).
    _st_total = len(filtered_faena_folios)
    _st_bodega = 0
    _st_ruta = 0
    _st_entregado = 0
    for _fol in filtered_faena_folios:
        _t = trk_by_folio.get(_fol)
        if _t and len(_t) > 1:
            _en = _normalize_state_value((_t[1] or ''))
            if _en in ('EN BODEGA', 'INGRESADO', 'DISPONIBLE EN BODEGA'):
                _st_bodega += 1
            elif _en == 'EN RUTA':
                _st_ruta += 1
            elif _en == 'ENTREGADO':
                _st_entregado += 1
    estadisticas = (_st_total, _st_bodega, _st_ruta, _st_entregado, 0)

    centros_costo_opciones = _dashboard_centros_costo_opciones_faena(ordenes, faena_cc_asignados)

    return render_template(
        'index.html',
        ordenes=ordenes,
        estadisticas=estadisticas,
        user_role=user_role,
        can_reset_local_tracking=has_any_role(user_role, ['SUPERADMIN']),
        can_import=False,
        can_dispatch=False,
        can_view_global=False,
        can_view_details=False,
        can_receive=True,
        can_search_requisicion=True,
        auto_refresh_ms=15000,
        page=page,
        page_size=page_size,
        has_more=has_more,
        has_previous=(page > 1),
        filtro_desde=filtro_desde_raw,
        filtro_hasta=filtro_hasta_raw,
        tracking_estado_selected=tracking_estado_raw,
        fecha_tipo_selected=fecha_tipo_raw,
        fecha_tipo_label=_label_fecha_tipo_bodega(fecha_tipo_raw),
        dashboard_today=date.today(),
        centros_costo_opciones=centros_costo_opciones,
        num_req_filtro=num_req_filtro_raw,
        num_oc_filtro=num_oc_filtro_raw,
        current_list_url=current_list_url,
        selected_dashboard_cc=cc_filter_raw,
        server_cc_filter_mode=True,
        cc_filter_server_side=True,
    )


def _dashboard_bodega(ctx):
    """Dashboard para perfiles BODEGA/VISUALIZADOR."""
    cursor = ctx["cursor"]; conn = ctx["conn"]; user_role = ctx["user_role"]; user_id = ctx["user_id"]
    aux_id_softland = ctx.get("aux_id_softland")
    faena_cc_asignados = ctx["faena_cc_asignados"]
    filtro_desde_raw = ctx["filtro_desde_raw"]; filtro_hasta_raw = ctx["filtro_hasta_raw"]
    filtro_desde_date = ctx["filtro_desde_date"]; filtro_hasta_date = ctx["filtro_hasta_date"]
    tracking_estado_raw = ctx["tracking_estado_raw"]; fecha_tipo_raw = ctx["fecha_tipo_raw"]
    cc_filter_raw = ctx["cc_filter_raw"]
    cc_filter_token = ctx.get("cc_filter_token", '')
    num_req_filtro_raw = ctx["num_req_filtro_raw"]; num_oc_filtro_raw = ctx["num_oc_filtro_raw"]
    page = ctx["page"]; page_size = ctx["page_size"]; row_offset = ctx["row_offset"]
    current_list_url = ctx["current_list_url"]
    folios_envio_parcial = []
    if tracking_estado_raw == 'entrega_parcial_faena':
        folios_envio_parcial = _folios_entrega_parcial_bodega_safe(cursor)

    folios_en_ruta_list = []
    if tracking_estado_raw == 'en_ruta':
        folios_en_ruta_list = _folios_tracking_en_ruta(
            cursor,
            filtro_desde_date,
            filtro_hasta_date,
            filtro_desde_raw,
            filtro_hasta_raw,
        )
    folios_entregados_list = []
    if tracking_estado_raw == 'entregado':
        folios_entregados_list = _folios_tracking_entregado(
            cursor,
            filtro_desde_date,
            filtro_hasta_date,
            filtro_desde_raw,
            filtro_hasta_raw,
        )
    if num_oc_filtro_raw.isdigit():
        try:
            _n_oc = int(num_oc_filtro_raw)
            folios_envio_parcial = [f for f in folios_envio_parcial if int(f) == _n_oc]
            folios_en_ruta_list = [f for f in folios_en_ruta_list if int(f) == _n_oc]
            folios_entregados_list = [f for f in folios_entregados_list if int(f) == _n_oc]
        except (TypeError, ValueError):
            pass

    folios_envio_parcial_set = frozenset(folios_envio_parcial)

    folios_recepcion_parcial_local = []
    folios_recepcion_parcial_combined = []
    if tracking_estado_raw == 'recepcion_parcial':
        folios_recepcion_parcial_local = _folios_local_recepcion_parcial(cursor, num_oc_filtro_raw)
        folios_recepcion_parcial_combined = list(folios_recepcion_parcial_local or [])

    folios_recepcion_rechazada_combined = []
    if tracking_estado_raw == 'recepcion_rechazada':
        folios_recepcion_rechazada_combined = list(_folios_local_recepcion_rechazada(cursor, num_oc_filtro_raw) or [])

    # Query principal integrando Softland Remoto (Master) y DespachosTracking (Local)
    master_data = []
    has_more_softland = False
    softland_total_oc = None
    softland_en_bodega_entrega_total = None
    conn_softland = None
    use_softland_dashboard_cache = tracking_estado_raw not in (
        'entrega_parcial_faena',
        'en_ruta',
        'entregado',
        'recepcion_parcial',
        'recepcion_rechazada',
    )
    try:
        cache_key = (
            f"v2eb|{(user_role or '').upper()}|{aux_id_softland or ''}|"
            f"d{filtro_desde_raw or '-'}|h{filtro_hasta_raw or '-'}|"
            f"ft{fecha_tipo_raw}|"
            f"r{num_req_filtro_raw or '-'}|oc{num_oc_filtro_raw or '-'}|"
            f"cc{cc_filter_token or '-'}|"
            f"t{tracking_estado_raw or '-'}|p{page}|s{page_size}"
        )
        cached = (
            _get_softland_dashboard_cache(cache_key)
            if use_softland_dashboard_cache
            else None
        )
        if cached:
            master_data = cached['rows']
            has_more_softland = bool(cached.get('has_more'))
            softland_total_oc = cached.get('total_count')
            softland_en_bodega_entrega_total = cached.get('en_bodega_entrega_total')
        else:
            conn_softland = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
            cursor_s = conn_softland.cursor()

            if tracking_estado_raw == 'entrega_parcial_faena':
                softland_en_bodega_entrega_total = None
                if not has_any_role(user_role, ['FAENA']):
                    shared_eb_ep, shared_eb_ep_p = _build_bodega_fecha_where_prefix(
                        fecha_tipo_raw,
                        filtro_desde_date,
                        filtro_hasta_date,
                        filtro_desde_raw,
                        filtro_hasta_raw,
                        cursor,
                        num_req_filtro_raw=num_req_filtro_raw,
                        cursor_softland=cursor_s,
                        num_oc_filtro_raw=num_oc_filtro_raw,
                        cc_filter_token=cc_filter_token,
                    )
                    where_eb_parts = list(shared_eb_ep)
                    where_eb_params = list(shared_eb_ep_p)
                    if _erp_scopes_softland_by_aux(user_role) and aux_id_softland:
                        where_eb_parts.append(
                            "EXISTS (SELECT 1 FROM softland.owordencom OH WITH (NOLOCK) WHERE OH.NumInterOC = OC.NumInterOc AND OH.CodAux = ?)"
                        )
                        where_eb_params.append(aux_id_softland)
                    _append_req_filter_to_parts(where_eb_parts, where_eb_params, num_req_filtro_raw)
                    _append_num_oc_filter_to_parts(where_eb_parts, where_eb_params, num_oc_filtro_raw)
                    where_eb_parts.append("ISNULL(softland_aggr.QtySolicitadaTotal, 0) > 0")
                    where_eb_parts.append(
                        "ISNULL(softland_aggr.QtyIngresadaTotal, 0) >= ISNULL(softland_aggr.QtySolicitadaTotal, 0)"
                    )
                    where_eb_sql = " WHERE " + " AND ".join(where_eb_parts)
                    eb_count_query = f"""
                        SELECT COUNT(1)
                        FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                        {SOFTLAND_OC_SALDO_AGG_APPLY}
                        {where_eb_sql}
                    """
                    cursor_s.execute(eb_count_query, tuple(where_eb_params))
                    eb_row = cursor_s.fetchone()
                    softland_en_bodega_entrega_total = int((eb_row[0] if eb_row else 0) or 0)
                master_data, has_more_softland, softland_total_oc = _load_master_data_entrega_parcial_faena(
                    cursor_s,
                    folios_envio_parcial,
                    row_offset,
                    page_size,
                    filtro_desde_date,
                    filtro_hasta_date,
                    filtro_desde_raw,
                    filtro_hasta_raw,
                    user_role,
                    aux_id_softland,
                    cursor_local=cursor,
                    num_req_filtro_raw=num_req_filtro_raw,
                    num_oc_filtro_raw=num_oc_filtro_raw,
                    cc_filter_token=cc_filter_token,
                )
            elif tracking_estado_raw == 'recepcion_parcial':
                softland_en_bodega_entrega_total = None
                shared_parts, shared_params = _build_bodega_fecha_where_prefix(
                    fecha_tipo_raw,
                    filtro_desde_date,
                    filtro_hasta_date,
                    filtro_desde_raw,
                    filtro_hasta_raw,
                    cursor,
                    num_req_filtro_raw=num_req_filtro_raw,
                    cursor_softland=cursor_s,
                    num_oc_filtro_raw=num_oc_filtro_raw,
                    cc_filter_token=cc_filter_token,
                )
                where_softland_parts = list(shared_parts)
                where_params = list(shared_params)
                if _erp_scopes_softland_by_aux(user_role) and aux_id_softland:
                    where_softland_parts.append(
                        "EXISTS (SELECT 1 FROM softland.owordencom OH WITH (NOLOCK) WHERE OH.NumInterOC = OC.NumInterOc AND OH.CodAux = ?)"
                    )
                    where_params.append(aux_id_softland)
                _append_req_filter_to_parts(where_softland_parts, where_params, num_req_filtro_raw)
                _append_num_oc_filter_to_parts(where_softland_parts, where_params, num_oc_filtro_raw)
                where_softland_parts.append("ISNULL(softland_aggr.QtyIngresadaTotal, 0) > 0")
                where_softland_parts.append(
                    "ISNULL(softland_aggr.QtyIngresadaTotal, 0) < ISNULL(softland_aggr.QtySolicitadaTotal, 0)"
                )
                where_softland_sql = " WHERE " + " AND ".join(where_softland_parts)
                cap = int(_DASHBOARD_FILTER_IDS_CAP)
                rp_ids_sql = f"""
                    SELECT TOP ({cap}) OC.NumOc
                    FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                    {SOFTLAND_OC_SALDO_AGG_APPLY}
                    {where_softland_sql}
                    ORDER BY OC.NumOc DESC
                """
                cursor_s.execute(rp_ids_sql, tuple(where_params))
                erp_rp = [int(r[0]) for r in cursor_s.fetchall() if r and r[0] is not None]
                loc_rp = {int(x) for x in (folios_recepcion_parcial_local or [])}
                combined_rp = sorted(loc_rp | set(erp_rp), reverse=True)
                folios_recepcion_parcial_combined = list(combined_rp)
                if not has_any_role(user_role, ['FAENA']):
                    where_eb_parts = list(shared_parts)
                    where_eb_params = list(shared_params)
                    if _erp_scopes_softland_by_aux(user_role) and aux_id_softland:
                        where_eb_parts.append(
                            "EXISTS (SELECT 1 FROM softland.owordencom OH WITH (NOLOCK) WHERE OH.NumInterOC = OC.NumInterOc AND OH.CodAux = ?)"
                        )
                        where_eb_params.append(aux_id_softland)
                    _append_req_filter_to_parts(where_eb_parts, where_eb_params, num_req_filtro_raw)
                    _append_num_oc_filter_to_parts(where_eb_parts, where_eb_params, num_oc_filtro_raw)
                    where_eb_parts.append("ISNULL(softland_aggr.QtySolicitadaTotal, 0) > 0")
                    where_eb_parts.append(
                        "ISNULL(softland_aggr.QtyIngresadaTotal, 0) >= ISNULL(softland_aggr.QtySolicitadaTotal, 0)"
                    )
                    where_eb_sql = " WHERE " + " AND ".join(where_eb_parts)
                    eb_count_query = f"""
                        SELECT COUNT(1)
                        FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                        {SOFTLAND_OC_SALDO_AGG_APPLY}
                        {where_eb_sql}
                    """
                    cursor_s.execute(eb_count_query, tuple(where_eb_params))
                    eb_row = cursor_s.fetchone()
                    softland_en_bodega_entrega_total = int((eb_row[0] if eb_row else 0) or 0)
                master_data, has_more_softland, softland_total_oc = _load_master_data_entrega_parcial_faena(
                    cursor_s,
                    combined_rp,
                    row_offset,
                    page_size,
                    filtro_desde_date,
                    filtro_hasta_date,
                    filtro_desde_raw,
                    filtro_hasta_raw,
                    user_role,
                    aux_id_softland,
                    cursor_local=cursor,
                    num_req_filtro_raw=num_req_filtro_raw,
                    num_oc_filtro_raw=num_oc_filtro_raw,
                    cc_filter_token=cc_filter_token,
                )
            elif tracking_estado_raw == 'en_ruta':
                softland_en_bodega_entrega_total = None
                master_data, has_more_softland, softland_total_oc = _load_master_data_entrega_parcial_faena(
                    cursor_s,
                    folios_en_ruta_list,
                    row_offset,
                    page_size,
                    None,
                    None,
                    filtro_desde_raw,
                    filtro_hasta_raw,
                    user_role,
                    aux_id_softland,
                    cursor_local=cursor,
                    num_req_filtro_raw=num_req_filtro_raw,
                    num_oc_filtro_raw=num_oc_filtro_raw,
                    cc_filter_token=cc_filter_token,
                )
            elif tracking_estado_raw == 'entregado':
                softland_en_bodega_entrega_total = None
                master_data, has_more_softland, softland_total_oc = _load_master_data_entrega_parcial_faena(
                    cursor_s,
                    folios_entregados_list,
                    row_offset,
                    page_size,
                    None,
                    None,
                    filtro_desde_raw,
                    filtro_hasta_raw,
                    user_role,
                    aux_id_softland,
                    cursor_local=cursor,
                    num_req_filtro_raw=num_req_filtro_raw,
                    num_oc_filtro_raw=num_oc_filtro_raw,
                    cc_filter_token=cc_filter_token,
                )
            elif tracking_estado_raw == 'recepcion_rechazada':
                softland_en_bodega_entrega_total = None
                master_data, has_more_softland, softland_total_oc = _load_master_data_entrega_parcial_faena(
                    cursor_s,
                    folios_recepcion_rechazada_combined,
                    row_offset,
                    page_size,
                    None,
                    None,
                    filtro_desde_raw,
                    filtro_hasta_raw,
                    user_role,
                    aux_id_softland,
                    cursor_local=cursor,
                    num_req_filtro_raw=num_req_filtro_raw,
                    num_oc_filtro_raw=num_oc_filtro_raw,
                    cc_filter_token=cc_filter_token,
                )
            else:
                shared_parts, shared_params = _build_bodega_fecha_where_prefix(
                    fecha_tipo_raw,
                    filtro_desde_date,
                    filtro_hasta_date,
                    filtro_desde_raw,
                    filtro_hasta_raw,
                    cursor,
                    num_req_filtro_raw=num_req_filtro_raw,
                    cursor_softland=cursor_s,
                    num_oc_filtro_raw=num_oc_filtro_raw,
                    cc_filter_token=cc_filter_token,
                    skip_year_predicate=(tracking_estado_raw == 'entrega_total'),
                )
                where_softland_parts = list(shared_parts)
                where_params = list(shared_params)
                if _erp_scopes_softland_by_aux(user_role) and aux_id_softland:
                    where_softland_parts.append(
                        "EXISTS (SELECT 1 FROM softland.owordencom OH WITH (NOLOCK) WHERE OH.NumInterOC = OC.NumInterOc AND OH.CodAux = ?)"
                    )
                    where_params.append(aux_id_softland)
                _append_req_filter_to_parts(where_softland_parts, where_params, num_req_filtro_raw)
                _append_num_oc_filter_to_parts(where_softland_parts, where_params, num_oc_filtro_raw)
                if tracking_estado_raw == 'no_entregado':
                    where_softland_parts.append("ISNULL(softland_aggr.QtyIngresadaTotal, 0) <= 0")
                elif tracking_estado_raw == 'entrega_total':
                    where_softland_parts.append("ISNULL(softland_aggr.QtyIngresadaTotal, 0) > 0")
                    where_softland_parts.append("ISNULL(softland_aggr.QtyIngresadaTotal, 0) >= ISNULL(softland_aggr.QtySolicitadaTotal, 0)")

                where_softland_sql = " WHERE " + " AND ".join(where_softland_parts)

                count_query = f"""
                    SELECT COUNT(1)
                    FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                    {SOFTLAND_OC_SALDO_AGG_APPLY}
                    {where_softland_sql}
                """
                cursor_s.execute(count_query, tuple(where_params))
                count_row = cursor_s.fetchone()
                softland_total_oc = int((count_row[0] if count_row else 0) or 0)

                if not has_any_role(user_role, ['FAENA']):
                    where_eb_parts = list(shared_parts)
                    where_eb_params = list(shared_params)
                    if _erp_scopes_softland_by_aux(user_role) and aux_id_softland:
                        where_eb_parts.append(
                            "EXISTS (SELECT 1 FROM softland.owordencom OH WITH (NOLOCK) WHERE OH.NumInterOC = OC.NumInterOc AND OH.CodAux = ?)"
                        )
                        where_eb_params.append(aux_id_softland)
                    _append_req_filter_to_parts(where_eb_parts, where_eb_params, num_req_filtro_raw)
                    _append_num_oc_filter_to_parts(where_eb_parts, where_eb_params, num_oc_filtro_raw)
                    where_eb_parts.append("ISNULL(softland_aggr.QtySolicitadaTotal, 0) > 0")
                    where_eb_parts.append(
                        "ISNULL(softland_aggr.QtyIngresadaTotal, 0) >= ISNULL(softland_aggr.QtySolicitadaTotal, 0)"
                    )
                    where_eb_sql = " WHERE " + " AND ".join(where_eb_parts)
                    eb_count_query = f"""
                        SELECT COUNT(1)
                        FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                        {SOFTLAND_OC_SALDO_AGG_APPLY}
                        {where_eb_sql}
                    """
                    cursor_s.execute(eb_count_query, tuple(where_eb_params))
                    eb_row = cursor_s.fetchone()
                    softland_en_bodega_entrega_total = int((eb_row[0] if eb_row else 0) or 0)

                softland_query = f"""
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
                        CASE
                            WHEN ISNULL(softland_aggr.TotalLineas, 0) > 0 THEN 1
                            ELSE 0
                        END AS TieneGuia,
                        CASE
                            WHEN ISNULL(softland_aggr.QtyIngresadaTotal, 0) > 0 THEN 1
                            ELSE 0
                        END AS HasAnyArrival,
                        ISNULL(softland_aggr.QtySolicitadaTotal, 0) AS QtySolicitadaTotal,
                        ISNULL(softland_aggr.QtyIngresadaTotal, 0) AS QtyIngresadaTotal
                    FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                    {SOFTLAND_OC_SALDO_AGG_APPLY}
                    {where_softland_sql}
                    ORDER BY OC.NumOc DESC
                    OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
                """
                query_params = tuple(where_params + [row_offset, page_size + 1])
                cursor_s.execute(softland_query, query_params)
                oc_rows = cursor_s.fetchall()
                has_more_softland = len(oc_rows) > page_size
                if has_more_softland:
                    oc_rows = oc_rows[:page_size]

                req_map = {}
                num_inter_values = [r[6] for r in oc_rows if len(r) > 6 and r[6] is not None]
                if num_inter_values:
                    placeholders = ",".join(["?"] * len(num_inter_values))
                    req_query = f"""
                        SELECT
                            Q.NumInterOC,
                            COALESCE(
                                MAX(NULLIF(LTRIM(RTRIM(R.Solicita)), '')),
                                MAX(NULLIF(LTRIM(RTRIM(S.DesSolic)), ''))
                            ) AS Solicitante
                        FROM softland.owreqoc Q WITH (NOLOCK)
                        LEFT JOIN softland.owrequisicion R WITH (NOLOCK) ON Q.NumReq = R.NumReq
                        LEFT JOIN softland.owsolicitanterq S WITH (NOLOCK) ON R.CodSolicita = S.CodSolic
                        WHERE Q.NumInterOC IN ({placeholders})
                        GROUP BY Q.NumInterOC
                    """
                    cursor_s.execute(req_query, tuple(num_inter_values))
                    req_map = {row[0]: (row[1] or 'Sin requisición') for row in cursor_s.fetchall()}

                master_data = []
                for oc in oc_rows:
                    num_inter = oc[6]
                    master_data.append((
                        oc[0],
                        oc[1],
                        oc[2],
                        oc[3],
                        req_map.get(num_inter, 'Sin requisición'),
                        oc[4],
                        oc[5],
                        oc[7],
                        oc[8],
                        oc[9],
                        oc[10],
                    ))
            if use_softland_dashboard_cache:
                _set_softland_dashboard_cache(
                    cache_key,
                    master_data,
                    has_more_softland,
                    softland_total_oc,
                    en_bodega_entrega_total=softland_en_bodega_entrega_total,
                )
    except Exception as e:
        if isinstance(e, pyodbc.Error):
            logger.error(f"Error BD Softland en dashboard: {e}")
            flash('No se pudo conectar a Softland temporalmente. Mostrando datos disponibles.', 'warning')
        else:
            logger.error(f"Error inesperado en dashboard (revisar código): {e}", exc_info=True)
            flash('Error inesperado al cargar el panel. Revise los logs del servidor.', 'danger')
        if tracking_estado_raw == 'entrega_parcial_faena' and folios_envio_parcial:
            master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
                folios_envio_parcial, row_offset, page_size
            )
        elif tracking_estado_raw == 'en_ruta' and folios_en_ruta_list:
            master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
                folios_en_ruta_list, row_offset, page_size
            )
        elif tracking_estado_raw == 'entregado' and folios_entregados_list:
            master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
                folios_entregados_list, row_offset, page_size
            )
        elif tracking_estado_raw == 'recepcion_parcial' and folios_recepcion_parcial_combined:
            master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
                folios_recepcion_parcial_combined, row_offset, page_size
            )
        elif tracking_estado_raw == 'recepcion_rechazada' and folios_recepcion_rechazada_combined:
            master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
                folios_recepcion_rechazada_combined, row_offset, page_size
            )
    finally:
        if conn_softland:
            conn_softland.close()

    if (
        tracking_estado_raw == 'recepcion_parcial'
        and not (master_data or [])
        and folios_recepcion_parcial_combined
    ):
        master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
            folios_recepcion_parcial_combined, row_offset, page_size
        )
    if (
        tracking_estado_raw == 'recepcion_rechazada'
        and not (master_data or [])
        and folios_recepcion_rechazada_combined
    ):
        master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
            folios_recepcion_rechazada_combined, row_offset, page_size
        )
    if (
        tracking_estado_raw == 'entregado'
        and not (master_data or [])
        and folios_entregados_list
    ):
        master_data, has_more_softland, softland_total_oc = _master_data_entrega_parcial_sin_softland(
            folios_entregados_list, row_offset, page_size
        )

    # Traer Tracking Local optimizado: solo folios visibles del bloque actual.
    tracking_local = {}
    partial_flags_map = {}
    reception_summary_map = {}
    sent_totals_map = {}
    if has_any_role(user_role, ['FAENA']):
        cursor.execute(
            """
            SELECT NumOc, Estado, FechaHoraSalida, FechaHoraEntrega, transportista_asignado_id
            FROM DespachosTracking
            WHERE transportista_asignado_id = ?
              AND UPPER(LTRIM(RTRIM(REPLACE(Estado, '_', ' ')))) IN ('EN RUTA', 'ENTREGADO')
            """,
            (user_id,),
        )
        tracking_local = {row[0]: row for row in cursor.fetchall()}
        partial_flags_map = _load_partial_flags_by_folio(cursor, list(tracking_local.keys()))
        reception_summary_map = _load_reception_summary_by_folio(cursor, list(tracking_local.keys()))
    else:
        visible_folios = []
        for row in master_data or []:
            if not row or row[0] is None:
                continue
            try:
                visible_folios.append(int(row[0]))
            except (TypeError, ValueError):
                continue
        if visible_folios:
            tracking_local = _fetch_latest_tracking_rows_by_folio(cursor, visible_folios)
            partial_flags_map = _load_partial_flags_by_folio(cursor, visible_folios)
            reception_summary_map = _load_reception_summary_by_folio(cursor, visible_folios)
            sent_totals_map = _load_sent_totals_by_folio(cursor, visible_folios)
            # Cabecera mal marcada Entregado con OC aún parcial en Softland: corregir sin abrir otra pantalla.
            if has_any_role(user_role, ['BODEGA', 'SUPERADMIN', 'VISUALIZADOR']):
                resynced = []
                for row in master_data:
                    if len(resynced) >= 5:
                        break
                    if not row or row[0] is None or len(row) < 11:
                        continue
                    folio_oc = int(row[0])
                    trk = tracking_local.get(folio_oc)
                    if not trk or not _state_in(trk[1], ('Entregado',)):
                        continue
                    try:
                        qty_sol = float(row[9] or 0)
                        qty_ing = float(row[10] or 0)
                    except Exception:
                        continue
                    if qty_sol <= 1e-9 or qty_ing + 1e-9 >= qty_sol:
                        continue
                    items_rs = _load_softland_oc_items(folio_oc)
                    if not items_rs:
                        continue
                    _sync_despachos_tracking_header(cursor, conn, folio_oc, items_rs)
                    resynced.append(folio_oc)
                if resynced:
                    conn.commit()
                    for k, v in _fetch_latest_tracking_rows_by_folio(cursor, resynced).items():
                        tracking_local[k] = v

    folios_for_envio_link = set(tracking_local.keys())
    for _r in master_data or []:
        if _r and _r[0] is not None:
            folios_for_envio_link.add(int(_r[0]))
    active_envio_map = _load_active_envio_id_by_folio(cursor, list(folios_for_envio_link))

    # Contadores globales por perfil (no dependen de la página visible).
    local_stats_where_extra = ""
    local_stats_params = []
    if filtro_desde_date:
        local_stats_where_extra += " AND DATE(COALESCE(FechaHoraEntrega, FechaHoraSalida)) >= ?"
        local_stats_params.append(filtro_desde_raw)
    if filtro_hasta_date:
        local_stats_where_extra += " AND DATE(COALESCE(FechaHoraEntrega, FechaHoraSalida)) <= ?"
        local_stats_params.append(filtro_hasta_raw)

    stats_sql_base = """
        SELECT
            COUNT(1) AS TotalOC,
            SUM(CASE WHEN UPPER(LTRIM(RTRIM(REPLACE(Estado, '_', ' ')))) IN ('EN BODEGA', 'INGRESADO', 'DISPONIBLE EN BODEGA') THEN 1 ELSE 0 END) AS EnBodega,
            SUM(CASE WHEN UPPER(LTRIM(RTRIM(REPLACE(Estado, '_', ' ')))) = 'EN RUTA' THEN 1 ELSE 0 END) AS Despachados,
            SUM(CASE WHEN UPPER(LTRIM(RTRIM(REPLACE(Estado, '_', ' ')))) = 'ENTREGADO' THEN 1 ELSE 0 END) AS Entregados
        FROM DespachosTracking
        WHERE 1=1
    """

    if has_any_role(user_role, ['FAENA']):
        stats_sql = stats_sql_base + " AND transportista_asignado_id = ?" + local_stats_where_extra
        cursor.execute(stats_sql, tuple([user_id] + local_stats_params))
    else:
        stats_sql = stats_sql_base + local_stats_where_extra
        cursor.execute(stats_sql, tuple(local_stats_params))
    stats_row = cursor.fetchone()
    stats = {
        'TotalOC': int(stats_row[0] or 0),
        'EnBodega': int(stats_row[1] or 0),
        'Despachados': int(stats_row[2] or 0),
        'Entregados': int(stats_row[3] or 0),
    }
    # La tarjeta «En bodega» debe reflejar el conteo local por estado, no el agregado ERP de recepción completa.

    ordenes = []

    for row in master_data:
        try:
            folio_int = int(row[0])
        except (TypeError, ValueError):
            continue
        trk = tracking_local.get(folio_int)
        tiene_guia = row[7]
        has_any_arrival = bool(row[8])
        qty_solicitada_total = float(row[9] or 0)
        qty_ingresada_total = float(row[10] or 0)
        fecha_emision = _to_date(row[1])
        fecha_llegada_estimada = _to_date(row[2])

        if trk:
            estado_tracking = _canonical_tracking_state(trk[1])
        elif tiene_guia:
            estado_tracking = 'EN_BODEGA'
        else:
            estado_tracking = 'PENDIENTE_EN_SOFTLAND'
        if tracking_estado_raw == 'en_ruta':
            estado_tracking = 'En Ruta'
        if tracking_estado_raw == 'entregado':
            estado_tracking = 'Entregado'
        eta_label, eta_class = _build_eta_badge(
            fecha_llegada_estimada,
            estado_tracking,
            trk[3] if trk else None,
        )
        rec_sum_row = reception_summary_map.get(folio_int, {}) or {}
        reception_status = rec_sum_row.get('status_label', 'No recepcionado')
        need_qty_oc = float(rec_sum_row.get('need_qty') or 0)
        got_qty_oc = float(rec_sum_row.get('got_qty') or 0)
        faena_has_rejected = bool(rec_sum_row.get('has_rejected', False))
        sent_total = float(sent_totals_map.get(folio_int, 0.0))
        pending_dispatch_qty = max(qty_ingresada_total - sent_total, 0.0)
        pend_bodega_faena = bool(has_any_arrival and pending_dispatch_qty > 1e-6)
        bodega_tracking_status = _bodega_dashboard_row_label(
            estado_tracking,
            _derive_bodega_tracking_status(
                qty_solicitada_total, qty_ingresada_total, pend_bodega_faena
            ),
            pend_bodega_faena,
        )
        if faena_has_rejected:
            bodega_tracking_status = 'Recepción rechazada en faena'
        can_dispatch_more = bool(has_any_arrival and pending_dispatch_qty > 1e-6)
        if tracking_estado_raw == 'entrega_parcial_faena':
            # Ya restringido por Softland IN (folios); no repetir con partial_flags_map (evita falsos negativos).
            if folio_int not in folios_envio_parcial_set:
                continue
            # Si la recepción en faena ya está completa, no debe mostrarse como parcial.
            if reception_status == 'Recepcionado completo':
                continue
        elif tracking_estado_raw == 'en_ruta':
            pass
        elif tracking_estado_raw == 'entregado':
            if not _state_in(estado_tracking, ('Entregado',)):
                continue
        elif not _bodega_dashboard_estado_passes_filter(
            qty_solicitada_total,
            qty_ingresada_total,
            bodega_tracking_status,
            tracking_estado_raw,
            reception_summary_map.get(folio_int),
        ):
            continue

        # Aplicar Filtros RBAC Aislamiento Total
        if has_any_role(user_role, ['FAENA']) and not trk:
            # El transportista solo opera sobre las suyas localmente fetchadas ('En Ruta')
            continue

        is_dispatched_to_me = bool(
            trk and len(trk) > 4 and trk[4] == session.get('user_id')
        )
        ordenes.append((
            folio_int, fecha_emision, fecha_llegada_estimada, row[3] or 'Sin Proveedor', row[4] or 'Sin requisición', row[6], 'A', estado_tracking, None,
            trk[2] if trk else None,
            trk[3] if trk else None,
            0, 0, row[5] or 'Sin CC',
            bool(partial_flags_map.get(folio_int, 0)),
            reception_status,
            eta_label,
            eta_class,
            bodega_tracking_status,
            has_any_arrival,
            is_dispatched_to_me,
            active_envio_map.get(folio_int),
            can_dispatch_more,
            pend_bodega_faena,
            need_qty_oc,
            got_qty_oc,
        ))

    # Fallback: si no vino maestro ERP, mostrar tracking local base.
    # Nunca rellenar con "todo el tracking" cuando el usuario pidió requisición o modo entrega faena:
    # esas vistas dependen del maestro ERP / IN(folios) y el fallback ignoraría num_req y la lógica de faena.
    master_folios = {row[0] for row in master_data}
    has_more = False
    if not master_data:
        skip_unfiltered_tracking_fallback = bool(
            (num_req_filtro_raw or "").strip()
        ) or (num_oc_filtro_raw or "").strip().isdigit() or (
            fecha_tipo_raw == "entrega_faena"
        )
        if skip_unfiltered_tracking_fallback:
            fallback_items = []
            has_more = False
        elif has_any_role(user_role, ['FAENA']):
            fallback_rows = list(tracking_local.values())
            start = row_offset
            end = row_offset + page_size + 1
            fallback_rows = fallback_rows[start:end]
            has_more = len(fallback_rows) > page_size
            if has_more:
                fallback_rows = fallback_rows[:page_size]
            fallback_items = [(row[0], row) for row in fallback_rows]
        else:
            fallback_params = []
            if tracking_estado_raw == 'en_ruta':
                fallback_sql = """
                    SELECT U.NumOc, U.Estado, U.FechaHoraSalida, U.FechaHoraEntrega, U.transportista_asignado_id
                    FROM (
                        SELECT
                            NumOc, Estado, FechaHoraSalida, FechaHoraEntrega, transportista_asignado_id,
                            ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
                        FROM DespachosTracking
                    ) U
                    WHERE U.rn = 1
                      AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(U.Estado, ''), '_', ' ')))) = 'EN RUTA'
                """
                if filtro_desde_date:
                    fallback_sql += (
                        " AND (U.FechaHoraSalida IS NULL OR DATE(U.FechaHoraSalida) >= ?)"
                    )
                    fallback_params.append(filtro_desde_raw)
                if filtro_hasta_date:
                    fallback_sql += (
                        " AND (U.FechaHoraSalida IS NULL OR DATE(U.FechaHoraSalida) <= ?)"
                    )
                    fallback_params.append(filtro_hasta_raw)
            elif tracking_estado_raw == 'entregado':
                fallback_sql = """
                    SELECT U.NumOc, U.Estado, U.FechaHoraSalida, U.FechaHoraEntrega, U.transportista_asignado_id
                    FROM (
                        SELECT
                            NumOc, Estado, FechaHoraSalida, FechaHoraEntrega, transportista_asignado_id,
                            ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
                        FROM DespachosTracking
                    ) U
                    WHERE U.rn = 1
                      AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(U.Estado, ''), '_', ' ')))) = 'ENTREGADO'
                """
                if filtro_desde_date:
                    fallback_sql += (
                        " AND (COALESCE(U.FechaHoraEntrega, U.FechaHoraSalida) IS NULL "
                        "OR DATE(COALESCE(U.FechaHoraEntrega, U.FechaHoraSalida)) >= ?)"
                    )
                    fallback_params.append(filtro_desde_raw)
                if filtro_hasta_date:
                    fallback_sql += (
                        " AND (COALESCE(U.FechaHoraEntrega, U.FechaHoraSalida) IS NULL "
                        "OR DATE(COALESCE(U.FechaHoraEntrega, U.FechaHoraSalida)) <= ?)"
                    )
                    fallback_params.append(filtro_hasta_raw)
            else:
                fallback_sql = """
                    SELECT NumOc, Estado, FechaHoraSalida, FechaHoraEntrega, transportista_asignado_id
                    FROM DespachosTracking
                    WHERE 1=1
                """
                if filtro_desde_date:
                    fallback_sql += (
                        " AND DATE(COALESCE(FechaHoraEntrega, FechaHoraSalida)) >= ?"
                    )
                    fallback_params.append(filtro_desde_raw)
                if filtro_hasta_date:
                    fallback_sql += (
                        " AND DATE(COALESCE(FechaHoraEntrega, FechaHoraSalida)) <= ?"
                    )
                    fallback_params.append(filtro_hasta_raw)
            if tracking_estado_raw == 'entrega_parcial_faena':
                fb_in_sql, fb_in_params = _sql_where_column_in_ints("NumOc", folios_envio_parcial)
                fallback_sql += f" AND ({fb_in_sql})"
                fallback_params.extend(fb_in_params)
            fallback_sql += " ORDER BY NumOc DESC LIMIT ? OFFSET ?"
            fallback_params.extend([page_size + 1, row_offset])
            cursor.execute(fallback_sql, tuple(fallback_params))
            fallback_all = cursor.fetchall()
            has_more = len(fallback_all) > page_size
            fallback_items = [(row[0], row) for row in fallback_all[:page_size]]

        if tracking_estado_raw == 'entrega_parcial_faena' and fallback_items:
            partial_flags_map.update(
                _load_partial_flags_by_folio(cursor, [x[0] for x in fallback_items])
            )

        pending_bodega_fallback_map = {}
        if fallback_items and has_any_role(user_role, ['FAENA']):
            pending_bodega_fallback_map = _load_pending_bodega_dispatch_by_folio(
                cursor, [x[0] for x in fallback_items]
            )

        for folio_local, trk in fallback_items:
            if folio_local in master_folios:
                continue
            estado_tracking = _canonical_tracking_state(trk[1] or 'INGRESADO')
            if has_any_role(user_role, ['FAENA']) and not _state_in(estado_tracking, ('En Ruta', 'Entregado')):
                continue
            eta_label, eta_class = _build_eta_badge(None, estado_tracking, trk[3])
            rec_sum_fb = reception_summary_map.get(int(folio_local), {}) or {}
            reception_status = rec_sum_fb.get('status_label', 'No recepcionado')
            need_qty_fb = float(rec_sum_fb.get('need_qty') or 0)
            got_qty_fb = float(rec_sum_fb.get('got_qty') or 0)
            # En fallback FAENA, mantener criterio: recepción parcial/completa real.
            has_any_arrival = reception_status in ('Recepcionado parcial', 'Recepcionado completo')
            pending_fb = bool(pending_bodega_fallback_map.get(int(folio_local), False))
            if pending_fb:
                base_bodega_fb = 'Pendiente despacho a faena'
            else:
                base_bodega_fb = (
                    'Despacho completo desde bodega' if reception_status == 'Recepcionado completo' else
                    'Recepción parcial' if has_any_arrival else
                    'No entregado'
                )
            bodega_tracking_status = _bodega_dashboard_row_label(
                estado_tracking, base_bodega_fb, pending_fb
            )
            if tracking_estado_raw == 'entrega_parcial_faena':
                if int(folio_local) not in folios_envio_parcial_set:
                    continue
                # Excluir OC cerradas en faena del filtro de entrega parcial.
                if reception_status == 'Recepcionado completo':
                    continue
            elif tracking_estado_raw == 'en_ruta':
                if not _state_in(estado_tracking, ('En Ruta',)):
                    continue
            elif tracking_estado_raw == 'entregado':
                if not _state_in(estado_tracking, ('Entregado',)):
                    continue
            elif not _bodega_dashboard_estado_passes_filter(
                0.0,
                0.0,
                bodega_tracking_status,
                tracking_estado_raw,
                rec_sum_fb,
            ):
                continue

            is_dispatched_fb = bool(
                trk and len(trk) > 4 and trk[4] == session.get('user_id')
            )
            ordenes.append((
                folio_local,          # 0 folio
                None,                 # 1 fecha emision
                None,                 # 2 fecha llegada estimada
                'Tracking Local',     # 3 proveedor
                'Sin requisición',    # 4 requisicion
                0,                    # 5 monto
                'A',                  # 6 estado softland visual
                estado_tracking,      # 7 estado tracking
                None,                 # 8 placeholder
                trk[2],               # 9 fecha salida
                trk[3],               # 10 fecha entrega
                0,                    # 11 placeholder
                0,                    # 12 placeholder
                'Sin CC',             # 13 centro costo
                bool(partial_flags_map.get(int(folio_local), 0)),  # 14 envío parcial
                reception_status,      # 15 estado recepción
                eta_label,            # 16 estado ETA/entrega
                eta_class,            # 17 clase badge ETA/entrega
                bodega_tracking_status, # 18 estado de negocio (3 estados)
                bool(has_any_arrival),  # 19 llegada real
                is_dispatched_fb,
                active_envio_map.get(int(folio_local)),
                bool(has_any_arrival and _state_in(estado_tracking, ('EN_BODEGA', 'INGRESADO', 'DISPONIBLE EN BODEGA', 'En Ruta'))),
                bool(pending_bodega_fallback_map.get(int(folio_local), False)),
                need_qty_fb,
                got_qty_fb,
            ))

    # Total usa agregado global; si aún no hay tracking, usa la página visible.
    if has_any_role(user_role, ['FAENA']):
        final_total_oc = stats['TotalOC'] if stats['TotalOC'] > 0 else len(ordenes)
    else:
        if (
            softland_en_bodega_entrega_total is None
            and stats['EnBodega'] == 0
            and ordenes
        ):
            # Respaldo si Softland no entregó conteo: estados locales en la página visible.
            stats['EnBodega'] = sum(
                1 for item in ordenes
                if item[7] in ('EN_BODEGA', 'INGRESADO', 'DISPONIBLE EN BODEGA')
            )
        if softland_total_oc is not None:
            final_total_oc = int(softland_total_oc)
        else:
            final_total_oc = stats['TotalOC'] if stats['TotalOC'] > 0 else len(ordenes)
    estadisticas = (final_total_oc, stats['EnBodega'], stats['Despachados'], stats['Entregados'], 0)
    if master_data:
        has_more = has_more_softland
    has_previous = page > 1

    can_import = has_any_role(user_role, ['SUPERADMIN', 'BODEGA'])
    can_dispatch = has_any_role(user_role, ['SUPERADMIN', 'BODEGA'])
    can_view_global = has_any_role(user_role, ['VISUALIZADOR'])
    can_view_details = has_any_role(user_role, ['SUPERADMIN', 'VISUALIZADOR', 'BODEGA', 'SUPERVISOR_CONTRATO'])
    can_receive = has_any_role(user_role, ['FAENA'])
    can_reset_local_tracking = has_any_role(user_role, ['SUPERADMIN'])
    can_search_requisicion = has_any_role(user_role, ['SUPERADMIN', 'BODEGA', 'VISUALIZADOR', 'FAENA', 'SUPERVISOR_CONTRATO'])
    auto_refresh_ms = 15000 if has_any_role(user_role, ['FAENA']) else 0

    logger.info(f"Dashboard cargado para usuario {session['username']} ({user_role})")

    centros_costo_opciones = _dashboard_centros_costo_opciones(ordenes)

    return render_template('index.html',
                         ordenes=ordenes,
                         estadisticas=estadisticas,
                         user_role=user_role,
                         can_import=can_import,
                         can_dispatch=can_dispatch,
                         can_view_global=can_view_global,
                         can_view_details=can_view_details,
                         can_receive=can_receive,
                         can_reset_local_tracking=can_reset_local_tracking,
                         can_search_requisicion=can_search_requisicion,
                         auto_refresh_ms=auto_refresh_ms,
                         page=page,
                         page_size=page_size,
                         has_more=has_more,
                         has_previous=has_previous,
                         filtro_desde=filtro_desde_raw,
                         filtro_hasta=filtro_hasta_raw,
                         tracking_estado_selected=tracking_estado_raw,
                         fecha_tipo_selected=fecha_tipo_raw,
                         fecha_tipo_label=_label_fecha_tipo_bodega(fecha_tipo_raw),
                         dashboard_today=date.today(),
                         centros_costo_opciones=centros_costo_opciones,
                         selected_dashboard_cc=cc_filter_raw,
                         cc_filter_server_side=True,
                         num_req_filtro=num_req_filtro_raw,
                         num_oc_filtro=num_oc_filtro_raw,
                         current_list_url=current_list_url)


@bp.route('/debug/rechazados')
@login_required()
def debug_rechazados():
    """Diagnóstico temporal: traza completa del filtro recepcion_rechazada.
    Solo disponible con DEBUG=True; en producción devuelve 404.
    """
    from flask import current_app, abort
    if not current_app.config.get('DEBUG'):
        abort(404)
    import traceback as _tb
    out = []
    try:
        conn = DatabaseConnection.get_connection()
        cursor = conn.cursor()

        # 1. Folios que devuelve _folios_local_recepcion_rechazada
        folios = _folios_local_recepcion_rechazada(cursor, "")
        out.append(f"<h3>1. folios_local_recepcion_rechazada: {folios}</h3>")

        # 2. Raw query de rechazados
        cursor.execute("""
            SELECT D.NumOc, D.EstadoLinea, E.Id, E.Estado
            FROM DespachosEnvioDetalle D
            INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
            WHERE UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) = 'RECHAZADO'
        """)
        rows = cursor.fetchall()
        out.append(f"<h3>2. Raw RECHAZADO rows: {rows}</h3>")

        # 3. DespachosTracking para esos folios
        if folios:
            placeholders = ','.join(['?' for _ in folios])
            sql = "SELECT NumOc, Estado, transportista_asignado_id FROM DespachosTracking WHERE NumOc IN (" + placeholders + ")"
            cursor.execute(sql, tuple(folios))
            trk = cursor.fetchall()
            out.append(f"<h3>3. DespachosTracking para {folios}: {trk}</h3>")
        else:
            out.append("<h3>3. Sin folios rechazados — no hay datos para mostrar</h3>")

        # 4. Softland connection test
        try:
            import pyodbc as _pyodbc
            from config import SoftlandConfig as _SC
            cs = _pyodbc.connect(_SC.get_connection_string(), timeout=5)
            cs.close()
            out.append("<h3>4. Conexión Softland: OK</h3>")
        except Exception as e2:
            out.append(f"<h3>4. Conexión Softland FALLA: {e2}</h3>")

        conn.close()
    except Exception as e:
        out.append(f"<pre>Error: {e}\n{_tb.format_exc()}</pre>")
    return '<br>'.join(out)


@bp.route('/')
@login_required()
def index():
    """Dashboard principal con filtros por rol"""
    if has_any_role(session.get('rol'), ['SUPERADMIN']):
        return redirect(url_for('frontend.gestionar_usuarios'))
    if has_any_role(session.get('rol'), ['SUPERVISOR_CONTRATO']):
        return redirect(url_for('frontend.supervisor_contratos'))
    try:
        conn = DatabaseConnection.get_connection()
        if not conn:
            logger.error("Error de conexión en index")
            return render_template('error.html',
                                 mensaje='Error de conexión a la base de datos'), 500

        try:
            cursor = conn.cursor()
            user_role = session.get('rol')
            user_id = session.get('user_id')
            filtro_desde_raw = (request.args.get('desde') or '').strip()
            filtro_hasta_raw = (request.args.get('hasta') or '').strip()
            tracking_estado_raw = (request.args.get('tracking_estado') or '').strip().lower()
            cc_filter_raw = (request.args.get('cc') or '').strip()
            cc_filter_token = " ".join(cc_filter_raw.upper().split()) if cc_filter_raw else ''
            allowed_tracking_filters = {
                '',
                'no_entregado',
                'recepcion_parcial',
                'recepcion_rechazada',
                'recepcion_completa',
                'entrega_total',
                'entrega_parcial_faena',
                'envio_completo_en_ruta',
                'en_ruta',
                'entregado',
            }
            if tracking_estado_raw not in allowed_tracking_filters:
                tracking_estado_raw = ''
            fecha_tipo_raw = (request.args.get('fecha_tipo') or 'emision').strip().lower()
            if fecha_tipo_raw not in ('emision', 'eta', 'entrega_faena'):
                fecha_tipo_raw = 'emision'
            num_req_filtro_raw = (request.args.get('num_req') or '').strip()
            if len(num_req_filtro_raw) > 80:
                num_req_filtro_raw = num_req_filtro_raw[:80]
            num_oc_filtro_raw = (request.args.get('num_oc') or '').strip()
            if len(num_oc_filtro_raw) > 20:
                num_oc_filtro_raw = num_oc_filtro_raw[:20]
            if num_oc_filtro_raw and not num_oc_filtro_raw.isdigit():
                flash('El filtro «OC» debe ser un número de folio (solo dígitos).', 'warning')
                num_oc_filtro_raw = ''
            filtro_desde_date = _parse_iso_date(filtro_desde_raw)
            filtro_hasta_date = _parse_iso_date(filtro_hasta_raw)
            if filtro_desde_raw and not filtro_desde_date:
                flash('La fecha Desde no es valida. Usa formato YYYY-MM-DD.', 'warning')
                filtro_desde_raw = ''
            if filtro_hasta_raw and not filtro_hasta_date:
                flash('La fecha Hasta no es valida. Usa formato YYYY-MM-DD.', 'warning')
                filtro_hasta_raw = ''
            if filtro_desde_date and filtro_hasta_date and filtro_desde_date > filtro_hasta_date:
                flash('Rango de fechas invalido: "Desde" no puede ser mayor que "Hasta".', 'warning')
                filtro_desde_raw = ''
                filtro_hasta_raw = ''
                filtro_desde_date = None
                filtro_hasta_date = None
            page = request.args.get('page', default=1, type=int) or 1
            if page < 1:
                page = 1
            page_size = _DASHBOARD_PAGE_SIZE
            row_offset = (page - 1) * page_size
            current_list_url = _sanitize_next_url(request.full_path or request.path)

            # Obtener perfil extendido para RBAC
            _ensure_faena_cc_column(cursor)
            cursor.execute("SELECT aux_id_softland, CentrosCostoAsignados FROM UsuariosSistema WHERE Id = ?", user_id)
            user_data = cursor.fetchone()
            aux_id_softland = user_data[0] if (user_data and user_data[0]) else None
            faena_cc_asignados = _normalize_cc_assignments(user_data[1] if user_data and len(user_data) > 1 else '')
            _ensure_local_tracking_table(cursor, conn)
            conn.commit()

            # Contexto compartido entre dashboards FAENA y BODEGA
            ctx = dict(
                cursor=cursor, conn=conn, user_role=user_role, user_id=user_id,
                aux_id_softland=aux_id_softland, faena_cc_asignados=faena_cc_asignados,
                filtro_desde_raw=filtro_desde_raw, filtro_hasta_raw=filtro_hasta_raw,
                filtro_desde_date=filtro_desde_date, filtro_hasta_date=filtro_hasta_date,
                tracking_estado_raw=tracking_estado_raw, fecha_tipo_raw=fecha_tipo_raw,
                cc_filter_raw=cc_filter_raw, cc_filter_token=cc_filter_token,
                num_req_filtro_raw=num_req_filtro_raw, num_oc_filtro_raw=num_oc_filtro_raw,
                page=page, page_size=page_size, row_offset=row_offset,
                current_list_url=current_list_url,
            )

            faena_mode = has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN'])
            if faena_mode:
                return _dashboard_faena(ctx)
            return _dashboard_bodega(ctx)


        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error en dashboard: {str(e)}", exc_info=True)
        return render_template(
            'error.html',
            mensaje='Error al cargar el dashboard',
            error_code=500,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        ), 500


@bp.route('/admin/reset-local-tracking', methods=['POST'])
@login_required(roles=roles_for('reset_tracking'))
def reset_local_tracking_data():
    """
    Reinicia solo datos locales de tracking para pruebas:
    - DespachosEnvioDetalle
    - DespachosEnvio
    - DespachosTrackingDetalle
    - DespachosTracking
    No toca Softland ni tablas de usuarios/perfiles.
    """
    try:
        from utils.dialect_sql import table_exists_sql, quote_ident
        # Whitelist de tablas permitidas para DELETE
        ALLOWED_DELETE_TABLES = {'DespachosEnvioDetalle', 'DespachosEnvio',
                                 'DespachosTrackingDetalle', 'DespachosTracking'}
        with local_db_transaction() as (conn, cursor):
            _ensure_local_tracking_table(cursor, conn)
            for tbl in ALLOWED_DELETE_TABLES:
                cursor.execute(table_exists_sql(), (tbl,))
                if cursor.fetchone():
                    # Validar tabla contra whitelist ANTES de ejecutar DELETE
                    if tbl not in ALLOWED_DELETE_TABLES:
                        raise ValueError(f"Tabla no permitida para DELETE: {tbl}")
                    cursor.execute(f"DELETE FROM {quote_ident(tbl)}")
        flash('Base local de tracking reiniciada correctamente (sin tocar Softland ni usuarios).', 'success')
    except Exception as exc:
        logger.error('Reset local tracking falló: %s', exc, exc_info=True)
        flash('No se pudo reiniciar la base local de tracking.', 'danger')
    return redirect(url_for('frontend.index'))


# ============================================
# SUPERVISOR_CONTRATO – REQUISICIONES
# ============================================

@bp.route('/supervisor/contratos')
@login_required(roles=roles_for('view_requisiciones'))
def supervisor_contratos():
    """Vista de supervisor de contrato - interfaz completamente nueva, vertical y compacta."""
    import json
    from utils.cc_helpers import fetch_faena_cc_for_user as _fetch_supervisor_cc_for_user, build_softland_cc_match_clause

    conn_softland = None
    conn_local = None
    try:
        conn_softland = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=30)
        conn_local = DatabaseConnection.get_connection()

        cursor_s = conn_softland.cursor()
        cursor_l = conn_local.cursor()

        user_id = session.get('user_id')
        user_role = session.get('rol')
        is_super = has_any_role(user_role, ['SUPERADMIN'])
        supervisor_cc = None
        where_clause_cc = ""
        query_params = []

        if not is_super:
            supervisor_cc = _fetch_supervisor_cc_for_user(user_id)
            if not supervisor_cc:
                flash('No tiene centros de costo asignados para consultar requisiciones y órdenes. Contacte al administrador.', 'warning')
                return render_template(
                    'supervisor_contrato_main.html',
                    requisiciones_json=json.dumps([])
                )
            cc_match_sql, _ = build_softland_cc_match_clause('OV', len(supervisor_cc))
            where_clause_cc = f" AND {cc_match_sql}"
            query_params.extend(supervisor_cc)
            query_params.extend(supervisor_cc)

        query = f"""
            SELECT DISTINCT TOP 100
                Q.NumReq,
                R.FEmision,
                R.FReq,
                R.CodEstado,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(R.Solicita)), ''),
                    NULLIF(LTRIM(RTRIM(S.DesSolic)), ''),
                    'Sin solicitante'
                ) AS Solicitante,
                COALESCE(NULLIF(LTRIM(RTRIM(R.CodiCC)), ''), 'Sin CC') AS CentroCosto,
                O.NumOC,
                O.FechaOC,
                COALESCE(OV.NomAux, 'Sin Proveedor') AS Proveedor,
                COALESCE(OV.ValorTotMB, 0) AS Monto,
                D.CodProd,
                COALESCE(P.DesProd, 'Sin descripción') AS DescProd,
                D.Cantidad,
                COALESCE(D.Cantidad, 0) AS CantidadOC,
                COALESCE(D.Recibido, 0) AS CantidadEnBodega
            FROM softland.owreqoc Q
            JOIN softland.owordencom O ON Q.NumInterOC = O.NumInterOC
            LEFT JOIN softland.owrequisicion R ON Q.NumReq = R.NumReq
            LEFT JOIN softland.owsolicitanterq S ON R.CodSolicita = S.CodSolic
            LEFT JOIN softland.OW_vsnpTraeEncabezadoOCompra OV ON O.NumOC = OV.NumOC
            LEFT JOIN softland.owordendet D ON O.NumInterOC = D.NumInterOC
            LEFT JOIN softland.IW_vsnpProductos P ON D.CodProd = P.CodProd
            WHERE COALESCE(
                YEAR(TRY_CONVERT(date, O.FechaOC, 103)),
                YEAR(TRY_CONVERT(date, O.FechaOC))
            ) = YEAR(GETDATE()){where_clause_cc}
            ORDER BY R.FEmision DESC, O.NumOC DESC, D.CodProd DESC
        """
        cursor_s.execute(query, tuple(query_params))
        all_rows = cursor_s.fetchall()

        requisiciones_dict = {}
        ordenes_dict = {}

        for row in all_rows:
            num_req = row[0]
            num_oc = row[6]
            cod_prod = row[10]

            if num_req not in requisiciones_dict:
                fecha_emision = row[1]
                if hasattr(fecha_emision, 'strftime'):
                    fecha_emision = fecha_emision.strftime('%Y-%m-%d') if fecha_emision else None

                fecha_requerida = row[2]
                if hasattr(fecha_requerida, 'strftime'):
                    fecha_requerida = fecha_requerida.strftime('%Y-%m-%d') if fecha_requerida else None

                requisiciones_dict[num_req] = {
                    'num_req': num_req,
                    'fecha': fecha_emision,
                    'fecha_emision': fecha_emision,
                    'fecha_requerida': fecha_requerida,
                    'estado': row[3] or 'PENDIENTE',
                    'solicitante': row[4],
                    'centro_costo': row[5],
                    'ordenes': {}
                }

            if num_oc and num_oc not in ordenes_dict:
                fecha_oc = row[7]
                if hasattr(fecha_oc, 'strftime'):
                    fecha_oc = fecha_oc.strftime('%Y-%m-%d') if fecha_oc else None

                ordenes_dict[num_oc] = {
                    'num_oc': num_oc,
                    'fecha': fecha_oc,
                    'proveedor': row[8] or 'Sin proveedor',
                    'centro_costo': row[5] or 'Sin CC',
                    'monto': float(row[9]) if row[9] else 0,
                    'lineas': []
                }
                requisiciones_dict[num_req]['ordenes'][num_oc] = ordenes_dict[num_oc]

            if num_oc and cod_prod:
                cant_oc = float(row[13]) if row[13] else (float(row[12]) if row[12] else 0)
                cant_bodega = float(row[14]) if row[14] else 0
                faltante = cant_oc - cant_bodega
                if faltante < 0:
                    faltante = 0
                ordenes_dict[num_oc]['lineas'].append([
                    cod_prod,
                    row[11],
                    float(row[12]) if row[12] else 0,
                    cant_bodega,
                    faltante,
                    num_oc
                ])

        cursor_l.execute("""
            SELECT NumOc, Estado, FechaHoraSalida, RegistradoPor
            FROM DespachosTracking
        """)
        tracking_rows = cursor_l.fetchall()
        tracking_map = {}
        for tr_row in tracking_rows:
            _fecha_raw = tr_row[2]
            if _fecha_raw is None:
                _fecha_str = None
            elif isinstance(_fecha_raw, str):
                _fecha_str = _fecha_raw
            else:
                _fecha_str = _fecha_raw.isoformat()
            tracking_map[tr_row[0]] = [
                tr_row[1],
                _fecha_str,
                tr_row[3],
                None
            ]

        # Envío concreto (viaje bodega → faena) - queda el más reciente por OC
        cursor_l.execute("""
            SELECT e.NumOc, e.Estado, e.FechaHoraSalida, e.FechaHoraEntrega,
                   e.Transportista, e.PatenteVehiculo, e.GuiaDespacho, e.Observaciones,
                   e.UrlFotoEvidencia, e.EntregaParcialBodega, e.RecepcionParcialFaena
            FROM DespachosEnvio e
            INNER JOIN (
                SELECT NumOc, MAX(Id) AS MaxId FROM DespachosEnvio GROUP BY NumOc
            ) last ON e.Id = last.MaxId
        """)

        def _iso(v):
            if v is None:
                return None
            if isinstance(v, str):
                return v
            return v.isoformat()

        envio_map = {}
        for er in cursor_l.fetchall():
            envio_map[er[0]] = {
                'estado': er[1],
                'fecha_salida': _iso(er[2]),
                'fecha_entrega': _iso(er[3]),
                'transportista': er[4],
                'patente': er[5],
                'guia': er[6],
                'observaciones': er[7],
                'foto_url': er[8],
                'parcial_bodega': bool(er[9]) if er[9] is not None else False,
                'parcial_faena': bool(er[10]) if er[10] is not None else False,
            }

        # Recepción por línea en faena (con nombre de quien recibió)
        cursor_l.execute("""
            SELECT d.NumOc, d.CodProd, d.CantidadSolicitada, d.CantidadEnviada,
                   d.CantidadRecibida, d.EstadoLinea, d.FechaRecepcion,
                   u.NombreCompleto, d.MotivoRechazo
            FROM DespachosEnvioDetalle d
            LEFT JOIN UsuariosSistema u ON d.RecibidoPor = u.Id
        """)
        recepcion_map = {}
        for rr in cursor_l.fetchall():
            recepcion_map.setdefault(rr[0], []).append({
                'cod_prod': rr[1],
                'solicitada': float(rr[2]) if rr[2] is not None else 0,
                'enviada': float(rr[3]) if rr[3] is not None else 0,
                'recibida': float(rr[4]) if rr[4] is not None else None,
                'estado_linea': rr[5],
                'fecha_recep': _iso(rr[6]),
                'recibido_por': rr[7],
                'motivo_rechazo': rr[8],
            })

        for req_data in requisiciones_dict.values():
            for oc_data in req_data['ordenes'].values():
                noc = oc_data['num_oc']
                oc_data['tracking'] = tracking_map.get(noc)
                oc_data['envio'] = envio_map.get(noc)
                oc_data['lineas_envio'] = recepcion_map.get(noc, [])

        requisiciones_data = list(requisiciones_dict.values())
        for req in requisiciones_data:
            req['ordenes'] = list(req['ordenes'].values())

        requisiciones_json = json.dumps(requisiciones_data)

        return render_template(
            'supervisor_contrato_main.html',
            requisiciones_json=requisiciones_json
        )

    except Exception as e:
        logger.error(f"Error en supervisor_contratos: {str(e)}", exc_info=True)
        flash(f'Error: {str(e)[:100]}', 'danger')
        return render_template(
            'supervisor_contrato_main.html',
            requisiciones_json=json.dumps([])
        )
    finally:
        if conn_softland:
            try:
                conn_softland.close()
            except Exception:
                pass
        if conn_local:
            try:
                conn_local.close()
            except Exception:
                pass

