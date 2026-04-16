"""Rutas de requisiciones – búsqueda y detalle."""

import logging

from flask import (
    render_template, request, redirect, url_for, flash,
    session, abort,
)
import pyodbc

from utils.auth import login_required, has_any_role
from utils.permissions import roles_for
from utils.db_legacy import DatabaseConnection
from utils.cc_helpers import fetch_faena_cc_for_user as _fetch_faena_cc_for_user
from config import SoftlandConfig
from routes.frontend import bp
from routes.frontend._helpers import (
    _sanitize_next_url,
    _resolve_softland_column,
    _build_softland_cc_match_clause,
    logger,
)


@bp.route('/requisicion/numero/<int:num_req>', methods=['GET'])
@login_required(roles=roles_for('view_requisiciones'))
def ir_a_requisicion_por_numero(num_req):
    """Redirige desde un N° de requisición, evitando saltos ambiguos entre OCs."""

    current_folio = request.args.get('current_folio', type=int)
    conn = None
    try:
        conn = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
        cursor = conn.cursor()

        # 1) Si la OC actual ya está vinculada a la requisición, quedarse en esa OC.
        if current_folio:
            cursor.execute("""
                SELECT TOP 1 O.NumOC
                FROM softland.owreqoc Q
                JOIN softland.owordencom O ON Q.NumInterOC = O.NumInterOC
                WHERE Q.NumReq = ? AND O.NumOC = ?
            """, (num_req, current_folio))
            current_row = cursor.fetchone()
            if current_row:
                next_url = _sanitize_next_url(request.args.get('next') or '')
                return redirect(url_for('frontend.detalle_requisicion', folio=current_folio, next=next_url))

        # 2) Buscar todas las OCs asociadas para resolver ambigüedad.
        cursor.execute("""
            SELECT O.NumOC
            FROM softland.owreqoc Q
            JOIN softland.owordencom O ON Q.NumInterOC = O.NumInterOC
            WHERE Q.NumReq = ?
            GROUP BY O.NumOC
            ORDER BY O.NumOC DESC
        """, (num_req,))
        oc_rows = cursor.fetchall()

        if not oc_rows:
            flash(f'No se encontró OC relacionada para la requisición {num_req}.', 'warning')
            return redirect(url_for('frontend.buscar_requisicion', num_req=num_req, modo='exacto'))

        if len(oc_rows) > 1:
            flash(
                f'La requisición {num_req} está asociada a varias OCs ({len(oc_rows)}). '
                'Seleccione la OC correcta en el resultado de búsqueda.',
                'info'
            )
            return redirect(url_for('frontend.buscar_requisicion', num_req=num_req, modo='exacto'))

        row = oc_rows[0]
    except Exception as e:
        logger.error(f"Error resolviendo requisición {num_req}: {e}", exc_info=True)
        flash('No se pudo resolver la requisición seleccionada.', 'danger')
        return redirect(url_for('frontend.index'))
    finally:
        if conn:
            conn.close()

    if not row:
        flash(f'No se encontró OC relacionada para la requisición {num_req}.', 'warning')
        return redirect(url_for('frontend.buscar_requisicion', num_req=num_req, modo='exacto'))

    next_url = _sanitize_next_url(request.args.get('next') or '')
    return redirect(url_for('frontend.detalle_requisicion', folio=row[0], next=next_url))


@bp.route('/requisicion/<int:folio>', methods=['GET'])
@login_required(roles=roles_for('view_requisiciones'))
def detalle_requisicion(folio):
    """Muestra el detalle completo de la requisición asociada a una OC."""

    conn = None
    try:
        conn = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
    except Exception as e:
        logger.error(f"Error conectando a Softland en detalle_requisicion ({folio}): {e}")
        flash('No se pudo conectar a Softland para consultar la requisición.', 'danger')
        return redirect(url_for('frontend.index'))

    if not conn:
        flash('Error de conexión', 'danger')
        return redirect(url_for('frontend.index'))

    try:
        cursor = conn.cursor()
        user_role_rq = session.get('rol')
        user_id_rq = session.get('user_id')
        if has_any_role(user_role_rq, ['FAENA']) and not has_any_role(user_role_rq, ['SUPERADMIN']):
            faena_cc_rq = _fetch_faena_cc_for_user(user_id_rq)
            if not faena_cc_rq:
                flash('No tiene centros de costo asignados para consultar requisiciones.', 'warning')
                return redirect(url_for('frontend.index'))
            cc_match_sql_rq, _ = _build_softland_cc_match_clause('OC', len(faena_cc_rq))
            cursor.execute(
                f"""
                SELECT 1 FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                WHERE OC.NumOc = ?
                  AND {cc_match_sql_rq}
                """,
                tuple([folio] + list(faena_cc_rq) + list(faena_cc_rq)),
            )
            if not cursor.fetchone():
                logger.warning('FAENA %s sin acceso a requisición de OC %s (CC)', user_id_rq, folio)
                abort(403)

        q_cc_col = _resolve_softland_column(cursor, 'owreqoc', ('CodiCC', 'CodCC', 'CentroCosto'))
        o_cc_col = _resolve_softland_column(cursor, 'owordencom', ('CodiCC', 'CodCC', 'CentroCosto'))
        q_cc_expr = f"NULLIF(LTRIM(RTRIM(CAST(Q.[{q_cc_col}] AS NVARCHAR(120)))), '')" if q_cc_col else "NULL"
        o_cc_expr = f"NULLIF(LTRIM(RTRIM(CAST(O.[{o_cc_col}] AS NVARCHAR(120)))), '')" if o_cc_col else "NULL"
        linea_cc_expr = f"COALESCE({q_cc_expr}, {o_cc_expr}, 'Sin CC')"

        # Cabecera de requisición vinculada a la OC
        cursor.execute("""
            SELECT TOP 1
                O.NumOC AS FolioOC,
                O.NumInterOC AS NumInterOC,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(R.Solicita)), ''),
                    NULLIF(LTRIM(RTRIM(S.DesSolic)), ''),
                    'Sin requisición'
                ) AS Solicitante,
                R.NumReq AS NumReq,
                R.FEmision AS FechaEmisionReq,
                R.FReq AS FechaRequerida,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(R.CodiCC)), ''),
                    NULLIF(LTRIM(RTRIM(O.CodiCC)), ''),
                    'Sin CC'
                ) AS CentroCosto,
                R.CodEstado AS EstadoReq
            FROM softland.owordencom O
            LEFT JOIN softland.owreqoc Q ON O.NumInterOC = Q.NumInterOC
            LEFT JOIN softland.owrequisicion R ON Q.NumReq = R.NumReq
            LEFT JOIN softland.owsolicitanterq S ON R.CodSolicita = S.CodSolic
            WHERE O.NumOC = ?
            ORDER BY R.NumReq DESC
        """, (folio,))
        cabecera = cursor.fetchone()

        # Detalle de líneas de requisición
        cursor.execute(f"""
            SELECT
                Q.NumReq AS NumReq,
                Q.NumLineaReq AS LineaReq,
                Q.CodProd AS CodigoProducto,
                COALESCE(P.DesProd, 'Sin descripción') AS Descripcion,
                COALESCE(
                    ODx.DetProdEditada,
                    NULLIF(LTRIM(RTRIM(P.Desprod2)), '')
                ) AS DescripcionEditada,
                Q.Cantidad AS Cantidad,
                {linea_cc_expr} AS CentroCostoLinea,
                Q.Partida AS Partida
            FROM softland.owordencom O
            JOIN softland.owreqoc Q ON O.NumInterOC = Q.NumInterOC
            LEFT JOIN softland.IW_vsnpProductos P ON Q.CodProd = P.CodProd
            OUTER APPLY (
                SELECT TOP 1
                    NULLIF(LTRIM(RTRIM(CAST(OD.DetProd AS NVARCHAR(4000)))), '') AS DetProdEditada
                FROM softland.owordendet OD
                WHERE OD.NumInterOC = O.NumInterOC
                  AND OD.CodProd = Q.CodProd
            ) ODx
            WHERE O.NumOC = ?
            ORDER BY Q.NumReq DESC, Q.NumLineaReq
        """, (folio,))
        detalles = cursor.fetchall()

        if not cabecera or (cabecera[3] is None and not detalles):
            flash('La orden no tiene requisición asociada en Softland.', 'warning')
            return redirect(url_for('frontend.index'))

        return render_template(
            'requisicion_detalle.html',
            folio=folio,
            cabecera=cabecera,
            detalles=detalles,
            next_url=_sanitize_next_url(request.args.get('next') or '')
        )

    except Exception as e:
        logger.error(f"Error en detalle_requisicion ({folio}): {e}", exc_info=True)
        flash('No se pudo cargar el detalle de requisición', 'danger')
        return redirect(url_for('frontend.index'))
    finally:
        conn.close()


@bp.route('/requisicion/buscar', methods=['GET'])
@login_required(roles=roles_for('view_requisiciones'))
def buscar_requisicion():
    """Busca una requisición y devuelve las OCs relacionadas."""
    num_req = (request.args.get('num_req') or '').strip()
    modo = (request.args.get('modo') or 'contiene').strip().lower()
    if modo not in ('exacto', 'contiene'):
        modo = 'contiene'
    resultados = []
    if not num_req:
        return render_template('requisicion_busqueda.html', num_req='', resultados=[], modo='contiene')


    conn = None
    try:
        conn = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
        cursor = conn.cursor()
        if modo == 'exacto':
            filtro_sql = "CAST(Q.NumReq AS NVARCHAR(50)) = ?"
            filtro_param = num_req
        else:
            filtro_sql = "CAST(Q.NumReq AS NVARCHAR(50)) LIKE ?"
            filtro_param = f"%{num_req}%"

        query = f"""
            SELECT
                Q.NumReq AS NumeroRequisicion,
                O.NumOC AS FolioOC,
                O.FechaOC AS FechaOC,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(O.CodiCC)), ''),
                    'Sin CC'
                ) AS CentroCosto
            FROM softland.owreqoc Q
            JOIN softland.owordencom O ON Q.NumInterOC = O.NumInterOC
            WHERE {filtro_sql}
            ORDER BY O.NumOC DESC
        """
        cursor.execute(query, (filtro_param,))
        resultados = cursor.fetchall()
    except Exception as e:
        logger.error(f"Error buscando requisición {num_req}: {e}", exc_info=True)
        flash('No se pudo consultar la requisición en Softland.', 'danger')
    finally:
        if conn:
            conn.close()

    if not resultados:
        flash(f'No se encontraron órdenes de compra para la requisición {num_req}.', 'warning')

    return render_template('requisicion_busqueda.html', num_req=num_req, resultados=resultados, modo=modo)
