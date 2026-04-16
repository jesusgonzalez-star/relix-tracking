"""Rutas de bodega – importación de OC, recepción y despacho."""

import os
import re
import json
import uuid
import logging
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import (
    render_template, request, redirect, url_for, flash,
    session, current_app, abort,
)
from werkzeug.utils import secure_filename
import pyodbc

from utils.auth import login_required, has_any_role, sanitize_input
from utils.permissions import roles_for
from utils.db_legacy import DatabaseConnection
from repositories.local_db import local_db_transaction
from utils.errors import APIError
from services.softland_service import SoftlandService
from config import SoftlandConfig
from utils.sql_helpers import softland_connection, softland_cursor
from utils.despacho_form import (
    consume_despacho_form_token,
    mint_despacho_form_token,
    verify_despacho_form_token,
)
from utils.cc_helpers import (
    normalize_cc_assignments as _normalize_cc_assignments,
    build_softland_cc_match_clause as _build_softland_cc_match_clause,
    ensure_faena_cc_column as _ensure_faena_cc_column,
    get_faena_cc_assignments as _get_faena_cc_assignments,
)

from routes.frontend import bp
from routes.frontend._helpers import (
    logger,
    allowed_file,
    _ensure_local_tracking_table,
    _load_softland_oc_items,
    _summarize_softland_arrival,
    _sync_despachos_tracking_header,
    _resolve_evidence_url,
    _resolve_evidence_urls_all,
    _resolve_softland_column,
    _get_evidence_upload_dir,
    _normalize_oc_linea_num,
    _bodega_envio_line_key,
    _aggregate_softland_oc_items_by_line,
    _sum_enviado_por_linea,
    _sum_enviado_por_numlinea,
    _pendiente_bodega,
    _compute_entrega_parcial_bodega_envio,
    _oc_has_pending_bodega_dispatch,
    _state_in,
    _normalize_state_value,
    _canonical_tracking_state,
    _normalize_patente,
    _is_valid_patente,
    _sanitize_next_url,
    _faena_user_has_cc_access_to_folio,
    _erp_scopes_softland_by_aux,
    _folios_local_recepcion_parcial,
    _load_faena_recepcion_evidence_urls_por_oc,
    _load_envios_agrupados_por_guia,
    ST_EN_BODEGA, ST_EN_RUTA, ST_ENTREGADO,
    LST_EN_RUTA, LST_PARCIAL,
)
from services.softland_sql_fragments import SOFTLAND_OC_SALDO_AGG_APPLY


# ---------------------------------------------------------------------------
# Ruta: Importar OC
# ---------------------------------------------------------------------------

@bp.route('/bodega/importar_oc', methods=['POST'])
@login_required(roles=roles_for('import_oc'))
def importar_oc():
    """Importa una OC desde Softland a la tabla local de tracking marcándola como INGRESADO"""
    folio = request.form.get('folio', type=int)
    if not folio:
        flash('Debe ingresar un número de OC', 'warning')
        return redirect(url_for('frontend.index'))

    try:
        with local_db_transaction() as (conn, cursor):
            _ensure_local_tracking_table(cursor, conn)
            cursor.execute("SELECT Estado FROM DespachosTracking WHERE NumOc = ?", (folio,))
            res = cursor.fetchone()
            if res:
                flash(f'La Orden de Compra ya está importada en local (Estado: {res[0]})', 'info')
                return redirect(url_for('frontend.index'))

            try:
                detalle = SoftlandService.obtener_detalle_oc(folio)
                if not detalle.get('guia_entrada'):
                    flash(
                        'Atención: La OC existe en Softland pero no tiene Guía de Entrada en el ERP aún.',
                        'warning',
                    )
                cursor.execute(
                    """
                    INSERT INTO DespachosTracking (NumOc, Estado, RegistradoPor)
                    VALUES (?, 'INGRESADO', ?)
                    """,
                    (folio, session.get('user_id')),
                )
                flash(
                    f'¡OC #{folio} importada con éxito! (Proveedor: {detalle.get("proveedor")}). Lista en Bodega.',
                    'success',
                )
            except APIError:
                cursor.execute(
                    """
                    INSERT INTO DespachosTracking (NumOc, Estado, RegistradoPor, Observaciones)
                    VALUES (?, 'INGRESADO', ?, ?)
                    """,
                    (folio, session.get('user_id'), 'Importada localmente sin conexión ERP'),
                )
                flash(f'OC #{folio} creada en tracking local (modo sin ERP).', 'warning')
            return redirect(url_for('frontend.index'))
    except RuntimeError:
        flash('Error de conexión local', 'danger')
        return redirect(url_for('frontend.index'))
    except Exception as e:
        logger.error("Error importando OC %s: %s", folio, e)
        flash('Error interno al importar la OC', 'danger')
        return redirect(url_for('frontend.index'))


# ---------------------------------------------------------------------------
# Helper local: envíos agrupados por guía
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Ruta: Recepción bodega (detalle read-only)
# ---------------------------------------------------------------------------

@bp.route('/bodega/recepcion/<int:folio>', methods=['GET'])
@login_required(roles=roles_for('view_recepcion'))
def recepcion_bodega(folio):
    """Muestra detalles ReadOnly de los productos de una OC desde el ERP"""

    try:
        cc_filter_raw = (request.args.get('cc') or '').strip()
        num_oc_filter_raw = (request.args.get('num_oc') or '').strip()
        cc_filter_token = " ".join(cc_filter_raw.upper().split()) if cc_filter_raw else ""
        num_oc_filter = int(num_oc_filter_raw) if num_oc_filter_raw.isdigit() else None

        # 1. Llamar a la Capa de Servicio param métricas O(1)
        detalle_erp = SoftlandService.obtener_detalle_oc(folio)
        despacho_items = _load_softland_oc_items(folio)

        # 2. RBAC - Aislamiento de Datos Nivel Fila (Row-Level Security)
        user_role = session.get('rol')
        user_id = session.get('user_id')

        if _erp_scopes_softland_by_aux(user_role):
            conn_local = DatabaseConnection.get_connection()
            try:
                cursor_local = conn_local.cursor()
                cursor_local.execute("SELECT aux_id_softland FROM UsuariosSistema WHERE Id = ?", user_id)
                user_data = cursor_local.fetchone()
                aux_id_softland = user_data[0] if user_data else None
            finally:
                conn_local.close()

            # Si el visualizador tiene mapeo aux, se aplica filtro por auxiliar.
            # Si no tiene mapeo, se permite acceso de lectura global (perfil consulta interno).
            if aux_id_softland:
                conn_softland = SoftlandService.get_connection()
                try:
                    c_s = conn_softland.cursor()
                    c_s.execute("SELECT 1 FROM softland.NW_OW_VsnpSaldoDetalleOC WHERE NumOc = ? AND Codaux = ?", (folio, aux_id_softland))
                    if not c_s.fetchone():
                        logger.warning(f"Acceso denegado: VISUALIZADOR {user_id} ({aux_id_softland}) intentó ver OC {folio} no asociada")
                        abort(403)
                finally:
                    conn_softland.close()

        if has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN']):
            conn_u = DatabaseConnection.get_connection()
            try:
                cu = conn_u.cursor()
                cu.execute("SELECT CentrosCostoAsignados FROM UsuariosSistema WHERE Id = ?", (user_id,))
                urow = cu.fetchone()
                faena_cc = _normalize_cc_assignments(urow[0] if urow else "")
            finally:
                conn_u.close()
            if not faena_cc:
                flash('No tiene centros de costo asignados para consultar órdenes.', 'warning')
                return redirect(url_for('frontend.index'))
            cc_allowed = False
            conn_cc = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
            try:
                cc_c = conn_cc.cursor()
                cc_match_sql, _ = _build_softland_cc_match_clause('OC', len(faena_cc))
                cc_c.execute(
                    f"""
                    SELECT 1 FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                    WHERE OC.NumOc = ?
                      AND {cc_match_sql}
                    """,
                    tuple([folio] + list(faena_cc) + list(faena_cc)),
                )
                cc_allowed = bool(cc_c.fetchone())
            finally:
                conn_cc.close()
            if not cc_allowed:
                # Alineado con el dashboard: permitir si la guía está asignada al usuario o la OC figura como
                # recepción parcial en BD local, aunque la cabecera ERP no calce CC (formato, stub, olas, etc.).
                conn_loc_chk = DatabaseConnection.get_connection()
                try:
                    cl = conn_loc_chk.cursor()
                    cl.execute(
                        """
                        SELECT TOP 1 transportista_asignado_id
                        FROM DespachosTracking
                        WHERE NumOc = ?
                        ORDER BY Id DESC
                        """,
                        (folio,),
                    )
                    tr_row = cl.fetchone()
                    assigned_me = (
                        tr_row
                        and tr_row[0] is not None
                        and int(tr_row[0]) == int(user_id)
                    )
                    partial_folios = set(_folios_local_recepcion_parcial(cl, str(folio)))
                    partial_ok = int(folio) in partial_folios
                finally:
                    conn_loc_chk.close()
                if not assigned_me and not partial_ok:
                    logger.warning("FAENA %s sin acceso a OC %s (CC / asignación / parcial)", user_id, folio)
                    abort(403)

        # 3. Cargar detalle local de entrega/evidencia para Bodega.
        tracking_local = None
        tracking_fotos = []
        detalle_local = []
        envios_por_guia = []
        faena_entrega_fotos = []
        tiene_lineas_rechazadas = False
        conn_local = DatabaseConnection.get_connection()
        if conn_local:
            try:
                c_local = conn_local.cursor()
                _ensure_local_tracking_table(c_local, conn_local)
                conn_local.commit()
                if despacho_items:
                    _sync_despachos_tracking_header(c_local, conn_local, folio, despacho_items)
                    conn_local.commit()
                c_local.execute("""
                    SELECT TOP 1 NumOc, Estado, GuiaDespacho, UrlFotoEvidencia, FechaHoraSalida, FechaHoraEntrega
                    FROM DespachosTracking
                    WHERE NumOc = ?
                    ORDER BY Id DESC
                """, (folio,))
                tracking_row = c_local.fetchone()
                if tracking_row:
                    tracking_local = tuple(tracking_row)
                    tracking_fotos = _resolve_evidence_urls_all(c_local, folio, tracking_local[3])
                    resolved_url = tracking_fotos[0] if tracking_fotos else _resolve_evidence_url(
                        c_local, folio, tracking_local[3]
                    )
                    tracking_local = (
                        tracking_local[:3]
                        + (resolved_url or tracking_local[3],)
                        + tracking_local[4:]
                    )
                detalle_local = []
                try:
                    c_local.execute("""
                        SELECT
                            NumLineaOc,
                            CodProd,
                            DescripcionProd,
                            COALESCE(TRY_CONVERT(DECIMAL(18,4), CantidadSolicitada), TRY_CONVERT(DECIMAL(18,4), CantidadEnviada)) AS QtyProg,
                            TRY_CONVERT(DECIMAL(18,4), CantidadEnviada) AS QtyEnv,
                            EstadoLinea,
                            MotivoRechazo,
                            TRY_CONVERT(DECIMAL(18,4), CantidadRecibida) AS QtyRecibida
                        FROM DespachosEnvioDetalle
                        WHERE NumOc = ?
                        ORDER BY EnvioId DESC, NumLineaOc, Id
                    """, (folio,))
                    detalle_local = c_local.fetchall()
                except Exception:
                    detalle_local = []
                if not detalle_local:
                    c_local.execute("""
                        SELECT
                            NumLineaOc,
                            CodProd,
                            DescripcionProd,
                            COALESCE(TRY_CONVERT(DECIMAL(18,4), CantidadSolicitada), TRY_CONVERT(DECIMAL(18,4), CantidadEnviada)) AS QtyProg,
                            TRY_CONVERT(DECIMAL(18,4), CantidadEnviada) AS QtyEnv,
                            EstadoLinea,
                            NULL AS MotivoRechazo,
                            TRY_CONVERT(DECIMAL(18,4), CantidadEnviada) AS QtyRecibida
                        FROM DespachosTrackingDetalle
                        WHERE NumOc = ?
                        ORDER BY NumLineaOc, Id
                    """, (folio,))
                    detalle_local = c_local.fetchall()
                envios_por_guia = _load_envios_agrupados_por_guia(c_local, folio)
                faena_entrega_fotos = _load_faena_recepcion_evidence_urls_por_oc(c_local, folio)
                # Detectar si hay líneas rechazadas para mostrar alerta en el detalle
                tiene_lineas_rechazadas = any(
                    (d[5] or '').upper().strip() == 'RECHAZADO'
                    for d in (detalle_local or [])
                    if len(d) > 5
                )
                if not tiene_lineas_rechazadas and envios_por_guia:
                    for g in envios_por_guia:
                        for d in g.get('lineas', []):
                            if len(d) > 5 and (d[5] or '').upper().strip() == 'RECHAZADO':
                                tiene_lineas_rechazadas = True
                                break
                        if tiene_lineas_rechazadas:
                            break
            finally:
                conn_local.close()
        if num_oc_filter is not None and num_oc_filter != int(folio):
            despacho_items = []

        if cc_filter_token and despacho_items:
            filtered_items = []
            for item in despacho_items:
                item_cc = " ".join(str((item or {}).get('centro_costo_linea') or '').upper().split())
                if cc_filter_token in item_cc:
                    filtered_items.append(item)
            despacho_items = filtered_items

        # Agregar totales reales de faena a despacho_items
        # Calcula por cada producto lo que faena realmente recibió
        if despacho_items and detalle_local:
            # Construir mapa de producto → (cantidad recibida, tiene rechazos)
            faena_received_map = {}
            faena_rechazados = set()

            for d in detalle_local:
                if len(d) > 7:  # Ahora tenemos 8 campos (con QtyRecibida)
                    cod_prod = (d[1] or '').strip().upper()
                    estado = (d[5] or '').upper().strip()
                    qty_recibida = float(d[7] or 0)  # d[7] es CantidadRecibida (nuevo)

                    if cod_prod not in faena_received_map:
                        faena_received_map[cod_prod] = 0.0
                    faena_received_map[cod_prod] += qty_recibida

                    if estado == 'RECHAZADO':
                        faena_rechazados.add(cod_prod)

            # Actualizar despacho_items con cantidades reales de faena
            for item in despacho_items:
                cod_prod = (item.get('codprod') or '').strip().upper()
                item['qty_recibida_faena'] = faena_received_map.get(cod_prod, 0.0)
                item['tiene_rechazo'] = cod_prod in faena_rechazados

        # 4. Renderizar Plantilla HTML Puramente Visual
        return render_template('recepcion_bodega.html',
                             orden=detalle_erp,
                             folio=folio,
                             cc_filter=cc_filter_raw,
                             num_oc_filter=num_oc_filter_raw,
                             despacho_items=despacho_items,
                             tracking_local=tracking_local,
                             tracking_fotos=tracking_fotos,
                             faena_entrega_fotos=faena_entrega_fotos,
                             detalle_local=detalle_local,
                             envios_por_guia=envios_por_guia or [],
                             tiene_lineas_rechazadas=tiene_lineas_rechazadas)

    except APIError:
        flash('Softland no está disponible en este momento para ver el detalle ERP.', 'warning')
        return redirect(url_for('frontend.index'))
    except Exception as e:
        logger.error("Error crítico en la vista detalle OC %s: %s", folio, e, exc_info=True)
        flash('No se pudo abrir el detalle de la orden en este momento.', 'danger')
        return redirect(url_for('frontend.index'))


# ---------------------------------------------------------------------------
# Excepción de control de flujo para despacho
# ---------------------------------------------------------------------------

class _DespachoFlowExit(Exception):
    """Salida controlada desde despacho_bodega (rollback vía local_db_transaction + redirect)."""

    __slots__ = ('endpoint', 'url_kwargs', 'message', 'category')

    def __init__(self, endpoint, message=None, category='warning', **url_kwargs):
        super().__init__(message or '')
        self.endpoint = endpoint
        self.url_kwargs = url_kwargs
        self.message = message
        self.category = category


# ---------------------------------------------------------------------------
# Ruta: Despacho bodega
# ---------------------------------------------------------------------------

@bp.route('/bodega/despacho/<int:folio>', methods=['GET', 'POST'])
@login_required(roles=roles_for('dispatch_bodega'))
def despacho_bodega(folio):
    """
    Despacho bodega→faena: Softland y disco fuera de transacciones locales.
    POST en dos fases BD (validar → fotos → revalidar+insertar) para no bloquear SQL durante I/O.
    """
    try:
        if request.method == 'POST':
            if not verify_despacho_form_token(
                session, folio, request.form.get('despacho_form_token')
            ):
                flash('El formulario de despacho expiró o ya fue enviado. Vuelve a abrir la orden.', 'warning')
                return redirect(url_for('frontend.despacho_bodega', folio=folio))

            transportista = sanitize_input(request.form.get('transportista', ''), 'texto')
            patente_raw = sanitize_input(request.form.get('patente_vehiculo', ''), 'texto')
            patente_vehiculo = _normalize_patente(patente_raw)
            guia = sanitize_input(request.form.get('guia', ''), 'texto')
            observaciones = sanitize_input(request.form.get('observaciones', ''), 'texto')
            items_present = (request.form.get('items_present') or '').strip() == '1'
            receptor_id = request.form.get('receptor_id', type=int)

            if not guia or not receptor_id:
                flash('Debe indicar guía y receptor de faena asignado.', 'warning')
                return redirect(url_for('frontend.despacho_bodega', folio=folio))
            if not patente_vehiculo:
                flash('Debe indicar la patente del camión para despachar.', 'warning')
                return redirect(url_for('frontend.despacho_bodega', folio=folio))
            if not _is_valid_patente(patente_vehiculo):
                flash('Formato de patente no válido. Ejemplo: ABCD-12.', 'warning')
                return redirect(url_for('frontend.despacho_bodega', folio=folio))

            fotos_in = [f for f in request.files.getlist('fotos') if f and (getattr(f, 'filename', None) or '').strip()]
            foto_legacy = request.files.get('foto')
            if foto_legacy and (getattr(foto_legacy, 'filename', None) or '').strip():
                fotos_in.append(foto_legacy)
            if not fotos_in:
                flash('Debe adjuntar al menos una foto de evidencia para completar el despacho.', 'warning')
                return redirect(url_for('frontend.despacho_bodega', folio=folio))
            for fup in fotos_in:
                if not allowed_file(fup):
                    flash('Formato de foto no permitido. Usa PNG/JPG/JPEG/WEBP/HEIC.', 'warning')
                    return redirect(url_for('frontend.despacho_bodega', folio=folio))

            despacho_items_softland = _load_softland_oc_items(folio)
            arrival_summary = _summarize_softland_arrival(despacho_items_softland)
            if not arrival_summary['has_any_arrival']:
                flash('No se puede despachar: la OC aún no registra llegada parcial ni total en bodega.', 'warning')
                return redirect(url_for('frontend.index'))

            post_ctx = {}

            def _post_phase1_validate(cursor, conn):
                _ensure_local_tracking_table(cursor, conn)
                cursor.execute(
                    "SELECT TOP 1 Estado FROM DespachosTracking WHERE NumOc = ? ORDER BY Id DESC",
                    (folio,),
                )
                tracking_current = cursor.fetchone()
                if not tracking_current:
                    cursor.execute(
                        """
                        INSERT INTO DespachosTracking (NumOc, Estado, RegistradoPor, Observaciones)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            folio,
                            ST_EN_BODEGA,
                            session.get('user_id'),
                            'Creada automáticamente para despacho desde llegada registrada en Softland',
                        ),
                    )
                elif not _state_in(
                    tracking_current[0],
                    (ST_EN_BODEGA, 'INGRESADO', 'DISPONIBLE EN BODEGA', ST_EN_RUTA),
                ):
                    raise _DespachoFlowExit(
                        'frontend.index',
                        'La orden no está en un estado válido de bodega para despachar.',
                        'warning',
                    )

                sent_map = _sum_enviado_por_linea(cursor, folio)
                sent_map_line = _sum_enviado_por_numlinea(cursor, folio)

                selected_indices = request.form.getlist('item_selected_idx')
                if items_present and not selected_indices:
                    raise _DespachoFlowExit(
                        'frontend.despacho_bodega',
                        'Debe seleccionar al menos un ítem para despachar.',
                        'warning',
                        folio=folio,
                    )

                selected_items = []
                unavailable_items = []
                _TOL = Decimal('0.0001')
                for raw_idx in selected_indices:
                    idx = (raw_idx or '').strip()
                    if not idx:
                        continue
                    qty_raw = (request.form.get(f'qty_send_{idx}') or '').replace(',', '.').strip()
                    try:
                        qty_send = Decimal(qty_raw)
                    except Exception:
                        qty_send = Decimal('0')
                    if qty_send <= 0:
                        continue
                    codprod = (request.form.get(f'item_codprod_{idx}', '') or '').strip() or 'N/A'
                    descripcion = (request.form.get(f'item_desc_{idx}', '') or '').strip() or 'Sin descripción'
                    try:
                        qty_solicitada = Decimal((request.form.get(f'item_qtysol_{idx}') or '0').replace(',', '.'))
                    except Exception:
                        qty_solicitada = Decimal('0')
                    try:
                        qty_ingresada = Decimal((request.form.get(f'item_qtying_{idx}') or '0').replace(',', '.'))
                    except Exception:
                        qty_ingresada = Decimal('0')
                    if qty_ingresada <= 0:
                        unavailable_items.append(codprod or descripcion or f"línea {idx}")
                        continue
                    num_linea = request.form.get(f'item_numlinea_{idx}', type=int)
                    line_key = _bodega_envio_line_key(num_linea, codprod)
                    line_norm = _normalize_oc_linea_num(num_linea)
                    already_sent = (
                        Decimal(str(sent_map_line.get(line_norm, 0)))
                        if line_norm is not None
                        else Decimal(str(sent_map.get(line_key, 0)))
                    )
                    if already_sent + qty_send > qty_ingresada + _TOL:
                        raise _DespachoFlowExit(
                            'frontend.despacho_bodega',
                            (
                                f'Para el ítem {codprod or idx}: ya se despacharon {already_sent} de {qty_ingresada} '
                                f'recibidos en bodega; no puede enviar {qty_send} adicionales.'
                            ),
                            'warning',
                            folio=folio,
                        )
                    if qty_solicitada > 0 and already_sent + qty_send > qty_solicitada + _TOL:
                        raise _DespachoFlowExit(
                            'frontend.despacho_bodega',
                            (
                                f'La cantidad acumulada a enviar para {codprod or idx} no puede superar '
                                f'la solicitada ({qty_solicitada}).'
                            ),
                            'warning',
                            folio=folio,
                        )
                    num_interoc = request.form.get(f'item_numinteroc_{idx}', type=int)
                    selected_items.append(
                        (
                            num_interoc,
                            num_linea,
                            codprod,
                            descripcion,
                            qty_solicitada,
                            qty_ingresada,
                            qty_send,
                        )
                    )

                if unavailable_items:
                    sample = ", ".join(unavailable_items[:5])
                    extra = "..." if len(unavailable_items) > 5 else ""
                    raise _DespachoFlowExit(
                        'frontend.despacho_bodega',
                        (
                            f'No hay cantidad recibida para enviar en: {sample}{extra}. '
                            'Actualiza la recepción en bodega o selecciona otros ítems.'
                        ),
                        'warning',
                        folio=folio,
                    )

                if items_present and not selected_items:
                    raise _DespachoFlowExit(
                        'frontend.despacho_bodega',
                        'Los ítems seleccionados deben tener cantidad a enviar mayor a 0.',
                        'warning',
                        folio=folio,
                    )
                if not selected_items:
                    raise _DespachoFlowExit(
                        'frontend.despacho_bodega',
                        'Debe incluir al menos una línea con cantidad a enviar.',
                        'warning',
                        folio=folio,
                    )

                cursor.execute(
                    """
                    SELECT U.Id, U.NombreCompleto
                    FROM UsuariosSistema U
                    JOIN Roles R ON U.RolId = R.Id
                    WHERE U.Id = ? AND U.Activo = 1 AND R.Nombre = 'FAENA'
                    """,
                    (receptor_id,),
                )
                receptor_row = cursor.fetchone()
                if not receptor_row:
                    raise _DespachoFlowExit(
                        'frontend.despacho_bodega',
                        'El receptor asignado no es válido o no está activo.',
                        'danger',
                        folio=folio,
                    )
                receptor_nombre = receptor_row[1] or f"Usuario {receptor_id}"
                transport_display = (transportista or '').strip() or receptor_nombre
                if observaciones and observaciones.strip():
                    obs_text = f"{observaciones.strip()} | Asignado a recepción: {receptor_nombre}"
                else:
                    obs_text = f"Asignado a recepción: {receptor_nombre}"

                post_ctx['selected_items'] = selected_items
                post_ctx['receptor_nombre'] = receptor_nombre
                post_ctx['transport_display'] = transport_display
                post_ctx['obs_text'] = obs_text

            with local_db_transaction() as (conn, cursor):
                _post_phase1_validate(cursor, conn)

            selected_items = post_ctx['selected_items']
            receptor_nombre = post_ctx['receptor_nombre']
            transport_display = post_ctx['transport_display']
            obs_text = post_ctx['obs_text']

            foto_urls = []
            ts_base = datetime.now().strftime('%Y%m%d%H%M%S')
            for i, foto in enumerate(fotos_in):
                safe_name = secure_filename(foto.filename or '')
                ext = os.path.splitext(safe_name)[1].lower() or '.jpg'
                filename = f"despacho_{folio}_{ts_base}_{i}_{uuid.uuid4().hex[:8]}{ext}"
                save_path = os.path.join(_get_evidence_upload_dir(), filename)
                foto.save(save_path)
                foto_urls.append(url_for('frontend.get_evidencia', filename=filename))
            foto_payload = foto_urls[0] if len(foto_urls) == 1 else json.dumps(foto_urls, ensure_ascii=False)

            envio_id = None

            def _post_phase2_write(cursor, conn):
                nonlocal envio_id
                _ensure_local_tracking_table(cursor, conn)
                # lock=True → WITH (UPDLOCK) serializa contra despachos concurrentes
                sent_map2 = _sum_enviado_por_linea(cursor, folio, lock=True)
                sent_map_line2 = _sum_enviado_por_numlinea(cursor, folio, lock=True)
                _TOL2 = Decimal('0.0001')
                for item in selected_items:
                    num_linea = item[1]
                    codprod = item[2]
                    qty_ingresada = Decimal(str(item[5] or 0))
                    qty_send = Decimal(str(item[6] or 0))
                    qty_solicitada = Decimal(str(item[4] or 0))
                    line_key = _bodega_envio_line_key(num_linea, codprod)
                    line_norm = _normalize_oc_linea_num(num_linea)
                    already_sent = (
                        Decimal(str(sent_map_line2.get(line_norm, 0)))
                        if line_norm is not None
                        else Decimal(str(sent_map2.get(line_key, 0)))
                    )
                    if already_sent + qty_send > qty_ingresada + _TOL2:
                        raise _DespachoFlowExit(
                            'frontend.despacho_bodega',
                            (
                                'Otro despacho se registró mientras completabas el formulario; '
                                'las cantidades ya no son válidas. Revisa y vuelve a intentar.'
                            ),
                            'warning',
                            folio=folio,
                        )
                    if qty_solicitada > 0 and already_sent + qty_send > qty_solicitada + _TOL2:
                        raise _DespachoFlowExit(
                            'frontend.despacho_bodega',
                            'Las cantidades ya no son válidas respecto a la OC. Vuelve a cargar el formulario.',
                            'warning',
                            folio=folio,
                        )

                envio_parcial_flag = _compute_entrega_parcial_bodega_envio(
                    despacho_items_softland, sent_map2, selected_items, sent_map_line2
                )

                cursor.execute(
                    """
                    INSERT INTO DespachosEnvio (
                        NumOc, Estado, GuiaDespacho, FechaHoraSalida, UrlFotoEvidencia,
                        Transportista, PatenteVehiculo, Observaciones, RegistradoPor, transportista_asignado_id,
                        EntregaParcialBodega
                    )
                    OUTPUT INSERTED.Id
                    VALUES (?, ?, ?, GETDATE(), ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        folio,
                        ST_EN_RUTA,
                        guia,
                        foto_payload,
                        transport_display,
                        patente_vehiculo,
                        obs_text,
                        session.get('user_id'),
                        receptor_id,
                        1 if envio_parcial_flag else 0,
                    ),
                )
                ins = cursor.fetchone()
                envio_id = int(ins[0]) if ins and ins[0] is not None else None
                if envio_id is None:
                    try:
                        cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS BIGINT)")
                        sid = cursor.fetchone()
                        if sid and sid[0] is not None:
                            envio_id = int(sid[0])
                    except Exception:
                        envio_id = None
                if not envio_id:
                    raise _DespachoFlowExit(
                        'frontend.index',
                        'No se pudo registrar el envío en base local.',
                        'danger',
                    )

                any_line_parcial = False
                for item in selected_items:
                    line_key = _bodega_envio_line_key(item[1], item[2])
                    qty_sol = Decimal(str(item[4] or 0))
                    qty_ing = Decimal(str(item[5] or 0))
                    qty_send = Decimal(str(item[6] or 0))
                    line_norm = _normalize_oc_linea_num(item[1])
                    prev_line = (
                        Decimal(str(sent_map_line2.get(line_norm, 0)))
                        if line_norm is not None
                        else Decimal(str(sent_map2.get(line_key, 0)))
                    )
                    pend_line = max(qty_ing - prev_line, Decimal('0'))
                    line_state = (
                        LST_PARCIAL
                        if (qty_send + _TOL2 < qty_sol or qty_send + _TOL2 < pend_line)
                        else LST_EN_RUTA
                    )
                    if line_state == LST_PARCIAL:
                        any_line_parcial = True
                    cursor.execute(
                        """
                        INSERT INTO DespachosEnvioDetalle (
                            EnvioId, NumOc, GuiaDespacho, NumInterOC, NumLineaOc, CodProd, DescripcionProd,
                            CantidadSolicitada, CantidadEnviada, CantidadDisponibleBodega, EstadoLinea
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            envio_id,
                            folio,
                            guia,
                            item[0],
                            item[1],
                            item[2],
                            item[3],
                            item[4],
                            item[6],
                            item[5],
                            line_state,
                        ),
                    )

                final_parcial = bool(envio_parcial_flag or any_line_parcial)
                cursor.execute(
                    "UPDATE DespachosEnvio SET EntregaParcialBodega = ? WHERE Id = ?",
                    (1 if final_parcial else 0, envio_id),
                )

                _sync_despachos_tracking_header(cursor, conn, folio, despacho_items_softland)

            try:
                with local_db_transaction() as (conn, cursor):
                    _post_phase2_write(cursor, conn)
            except _DespachoFlowExit:
                for u in foto_urls:
                    try:
                        p = os.path.join(_get_evidence_upload_dir(), os.path.basename(u))
                        if os.path.isfile(p):
                            os.remove(p)
                    except OSError:
                        pass
                raise
            except Exception as e:
                for u in foto_urls:
                    try:
                        p = os.path.join(_get_evidence_upload_dir(), os.path.basename(u))
                        if os.path.isfile(p):
                            os.remove(p)
                    except OSError:
                        pass
                logger.error("Error en despacho (fase escritura): %s", e, exc_info=True)
                flash('Error interno al registrar el despacho. Intente nuevamente.', 'danger')
                return redirect(url_for('frontend.index'))

            consume_despacho_form_token(session, folio)
            logger.info(f"Despacho (envío {envio_id}) registrado: Folio {folio}, Receptor {receptor_nombre}")
            flash(f'✓ Orden {folio} despachada y asignada a {receptor_nombre}', 'success')
            return redirect(url_for('frontend.index'))

        # GET
        despacho_items = _load_softland_oc_items(folio)
        arrival_summary = _summarize_softland_arrival(despacho_items)

        orden_local = None
        sent_map_get = {}
        sent_map_line_get = {}

        with local_db_transaction() as (conn, cursor):
            _ensure_local_tracking_table(cursor, conn)
            cursor.execute(
                "SELECT TOP 1 NumOc, Estado FROM DespachosTracking WHERE NumOc = ? ORDER BY Id DESC",
                (folio,),
            )
            orden_local = cursor.fetchone()
            if orden_local and despacho_items:
                _sync_despachos_tracking_header(cursor, conn, folio, despacho_items)
                cursor.execute(
                    "SELECT TOP 1 NumOc, Estado FROM DespachosTracking WHERE NumOc = ? ORDER BY Id DESC",
                    (folio,),
                )
                orden_local = cursor.fetchone()
            if not orden_local:
                if not arrival_summary['has_any_arrival']:
                    raise _DespachoFlowExit(
                        'frontend.index',
                        'Aún no puedes despachar esta OC: no hay productos llegados en bodega (ni parcial ni total).',
                        'warning',
                    )
                cursor.execute(
                    """
                    INSERT INTO DespachosTracking (NumOc, Estado, RegistradoPor, Observaciones)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        folio,
                        ST_EN_BODEGA,
                        session.get('user_id'),
                        'Creada automáticamente para despacho desde llegada registrada en Softland',
                    ),
                )
                orden_local = (folio, ST_EN_BODEGA)

            if not _state_in(
                orden_local[1],
                (ST_EN_BODEGA, 'INGRESADO', 'DISPONIBLE EN BODEGA', ST_EN_RUTA),
            ):
                raise _DespachoFlowExit(
                    'frontend.index',
                    'La orden debe estar en estado de bodega (o con envíos en ruta) para despachar.',
                    'warning',
                )
            if not arrival_summary['has_any_arrival']:
                raise _DespachoFlowExit(
                    'frontend.index',
                    'Aún no puedes despachar esta OC: no hay productos llegados en bodega (ni parcial ni total).',
                    'warning',
                )

            sent_map_get = _sum_enviado_por_linea(cursor, folio)
            sent_map_line_get = _sum_enviado_por_numlinea(cursor, folio)

        despacho_items_raw = list(despacho_items)
        for it in despacho_items_raw:
            line_k = _bodega_envio_line_key(it.get('num_linea'), it.get('codprod'))
            line_norm = _normalize_oc_linea_num(it.get('num_linea'))
            enviado_prev = (
                float(sent_map_line_get.get(line_norm, 0.0))
                if line_norm is not None
                else float(sent_map_get.get(line_k, 0.0))
            )
            ing = float(it.get('qty_ingresada') or 0)
            pend = _pendiente_bodega(ing, enviado_prev)
            it['qty_pendiente_bodega'] = pend
            if pend <= 0:
                it['qty_sugerida'] = 0.0
            else:
                try:
                    sug = float(it.get('qty_sugerida') or pend)
                except Exception:
                    sug = pend
                it['qty_sugerida'] = min(sug, pend)

        despacho_items = [
            it
            for it in despacho_items_raw
            if float(it.get('qty_pendiente_bodega', 0) or 0) > 1e-6
        ]
        if not despacho_items:
            if not despacho_items_raw:
                flash('No se encontraron ítems en Softland para esta OC.', 'warning')
            else:
                flash(
                    'No quedan líneas con cantidad pendiente de envío en bodega: '
                    'todo lo recibido ya fue incluido en guías de despacho.',
                    'info',
                )
            return redirect(url_for('frontend.index'))

        with local_db_transaction() as (conn, cursor):
            _ensure_local_tracking_table(cursor, conn)
            cursor.execute(
                """
                SELECT U.Id, U.NombreCompleto, U.Usuario
                FROM UsuariosSistema U
                JOIN Roles R ON U.RolId = R.Id
                WHERE U.Activo = 1 AND R.Nombre = 'FAENA'
                ORDER BY U.NombreCompleto, U.Usuario
                """
            )
            receptores = cursor.fetchall()
            if not receptores:
                raise _DespachoFlowExit(
                    'frontend.index',
                    'No hay perfiles FAENA activos para asignar este despacho.',
                    'warning',
                )

        cc_unicos = sorted(
            {((it.get('centro_costo_linea') or '').strip() or 'Sin CC') for it in despacho_items},
            key=lambda v: (v == 'Sin CC', v),
        )
        despacho_form_token = mint_despacho_form_token(session, folio)
        return render_template(
            'despacho_bodega.html',
            orden=orden_local,
            folio=folio,
            receptores=receptores,
            despacho_items=despacho_items,
            cc_unicos=cc_unicos,
            despacho_form_token=despacho_form_token,
        )

    except _DespachoFlowExit as ex:
        if ex.message:
            flash(ex.message, ex.category)
        return redirect(url_for(ex.endpoint, **ex.url_kwargs))
    except RuntimeError:
        flash('Error de conexión', 'danger')
        return redirect(url_for('frontend.index'))
    except Exception as e:
        logger.error("Error en despacho_bodega: %s", e, exc_info=True)
        flash('Error inesperado', 'danger')
        return redirect(url_for('frontend.index'))
