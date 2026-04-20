"""Shared private helpers for the *frontend* blueprint package.

Every function, constant and import that lived **above** the first
``@bp.route`` decorator in the original monolithic ``frontend_routes.py``
is collected here so that the individual route modules can simply do::

    from routes.frontend._helpers import <name>

Nothing in this module registers routes or filters -- that wiring lives
in ``routes/frontend/__init__.py``.
"""

import os
import io
import re
import json
import uuid
import time
import hmac
import secrets
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from PIL import Image, ImageDraw
import urllib.parse

from flask import render_template, request, redirect, url_for, flash, session, send_file, send_from_directory, current_app, jsonify, abort
import logging
from werkzeug.utils import secure_filename

from utils.auth import (
    hash_password,
    verify_password,
    sanitize_input,
    login_required,
    has_any_role,
    validate_password_strength,
)
from utils.db_legacy import DatabaseConnection
from utils.despacho_form import (
    consume_despacho_form_token,
    mint_despacho_form_token,
    verify_despacho_form_token,
)
from utils.recepcion_form import (
    consume_recepcion_form_token,
    mint_recepcion_form_token,
    verify_recepcion_form_token,
)
from extensions import limiter
from repositories.local_db import local_db_transaction
from services.softland_sql_fragments import SOFTLAND_OC_SALDO_AGG_APPLY
from services.softland_service import SoftlandService
from config import SoftlandConfig
from utils.sql_helpers import (
    norm_estado, norm_estado_linea, where_active_envio,
    EXCLUDED_STATES, softland_connection, softland_cursor,
)
from utils.cc_helpers import (
    normalize_cc_assignments as _normalize_cc_assignments,
    build_softland_cc_match_clause as _build_softland_cc_match_clause,
    ensure_faena_cc_column as _ensure_faena_cc_column,
    get_faena_cc_assignments as _get_faena_cc_assignments,
    get_folios_by_centros_costo as _get_folios_by_centros_costo,
    folio_matches_centros_costo_tokens as _folio_matches_centros_costo_tokens,
    faena_user_has_cc_access_to_folio as _faena_user_has_cc_access_to_folio,
    form_cc_assignments_from_request as _form_cc_assignments_from_request,
    fetch_softland_centros_costo_opciones as _fetch_softland_centros_costo_opciones,
    dashboard_centros_costo_opciones as _dashboard_centros_costo_opciones,
    dashboard_centros_costo_opciones_faena as _dashboard_centros_costo_opciones_faena,
)
import pyodbc
from utils.permissions import roles_for

def allowed_file(file_storage):
    """Valida imágenes para PC y móviles (incluye formatos modernos)."""
    allowed_extensions = {'png', 'jpg', 'jpeg', 'webp', 'heic', 'heif'}
    filename = (getattr(file_storage, 'filename', '') or '').strip()
    mimetype = (getattr(file_storage, 'mimetype', '') or '').lower()

    if filename and '.' in filename:
        ext = filename.rsplit('.', 1)[1].lower()
        if ext in allowed_extensions:
            return True

    # Fallback por mimetype para casos móviles sin extensión clara.
    # Solo tipos seguros (excluye image/svg+xml que permite XSS).
    allowed_mimetypes = {'image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic', 'image/heif'}
    return mimetype in allowed_mimetypes

logger = logging.getLogger(__name__)

# ── Precisión numérica ──────────────────────────────────────────────
_QTY_TOLERANCE = Decimal('0.0001')   # tolerancia para comparaciones de cantidad


def _safe_decimal(value, default=Decimal('0')):
    """Convierte valor a Decimal de forma segura, tolerando None/float/str."""
    if value is None:
        return default
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return default


_LOCAL_TRACKING_SCHEMA_READY = False
_SOFTLAND_DASHBOARD_CACHE = {}
_SOFTLAND_CACHE_TTL_SECONDS = 120
_DASHBOARD_PAGE_SIZE = 30
_DASHBOARD_FILTER_IDS_CAP = 4000

# ── Constantes canónicas de estado (fuente única: utils.states) ──────
from utils.states import (                         # noqa: E402
    ST_INGRESADO, ST_EN_BODEGA, ST_EN_RUTA, ST_ENTREGADO,
    ST_CANCELADO, ST_ANULADO, ST_PENDIENTE_SOFTLAND, ST_DISPONIBLE_BODEGA,
    LST_EN_RUTA, LST_ENTREGADO, LST_PARCIAL, LST_RECHAZADO,
    STORAGE_STATE_MAP as _STORAGE_STATE_MAP,
)

_CSRF_PROTECTED_ENDPOINTS = {
    'frontend.despacho_bodega',
    'frontend.recibir_producto_envio',
    'frontend.recibir_producto_folio_legacy',
    'frontend.gestionar_usuarios',
    'frontend.reset_local_tracking_data',
    'frontend.importar_oc',
    # 'frontend.verificar_qr' — consumido por cliente móvil por JSON;
    # hasta que el móvil envíe X-CSRF-Token se mantiene fuera de la lista.
    'frontend.login',
    'frontend.registro',
    'frontend.invalidar_cache_dashboard',
}


def _get_csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def _faena_softland_req_labels_map(cursor_sf, num_inter_values):
    """
    Mapa NumInterOC -> texto de requisición (mismo enfoque por lotes que el dashboard bodega).
    Evita subconsultas correlacionadas que suelen fallar o agotar tiempo en SQL Server.
    """
    nums = []
    seen = set()
    for v in num_inter_values:
        if v is None:
            continue
        try:
            i = int(v)
        except (TypeError, ValueError):
            continue
        if i not in seen:
            seen.add(i)
            nums.append(i)
    if not nums:
        return {}
    placeholders = ",".join(["?"] * len(nums))
    cursor_sf.execute(
        f"""
        SELECT
            Q.NumInterOC,
            COALESCE(
                NULLIF(LTRIM(RTRIM(CAST(MAX(R.NumReq) AS NVARCHAR(80)))), ''),
                MAX(NULLIF(LTRIM(RTRIM(R.Solicita)), '')),
                MAX(NULLIF(LTRIM(RTRIM(S.DesSolic)), ''))
            ) AS ReqLabel
        FROM softland.owreqoc Q WITH (NOLOCK)
        LEFT JOIN softland.owrequisicion R WITH (NOLOCK) ON Q.NumReq = R.NumReq
        LEFT JOIN softland.owsolicitanterq S WITH (NOLOCK) ON R.CodSolicita = S.CodSolic
        WHERE Q.NumInterOC IN ({placeholders})
        GROUP BY Q.NumInterOC """,
        tuple(nums),
    )
    out = {}
    for row in cursor_sf.fetchall():
        key = row[0]
        try:
            key = int(key)
        except (TypeError, ValueError):
            continue
        lab = (row[1] or "").strip() if row[1] is not None else ""
        out[key] = lab if lab else "Sin requisición"
    return out



def _to_date(value):
    """Normaliza datetime/date/str/obj con ymd (pyodbc/SQL) a date para dashboard y badges."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = (value or '').strip()
        if not raw:
            return None
        s = raw.split()[0][:10]
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y'):
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None
    if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day'):
        try:
            return date(int(value.year), int(value.month), int(value.day))
        except (TypeError, ValueError):
            return None
    return None


def _filter_dash_date(value):
    """Formato dd-mm-YYYY para celdas del dashboard (evita fallos si el tipo varía)."""
    d = _to_date(value)
    return d.strftime('%d-%m-%Y') if d else 'N/A'


def _filter_dash_date_key(value):
    """Clave YYYY-MM-DD para comparar en plantilla (entrega vs ETA)."""
    d = _to_date(value)
    return d.strftime('%Y-%m-%d') if d else ''

def _build_eta_badge(fecha_eta, estado_tracking, fecha_entrega=None):
    """
    Retorna etiqueta/clase de ETA:
    - En entregados: Entregado a tiempo vs Entregado con atraso.
    - En no entregados: A tiempo/Proxima/Urgente segun cercania de ETA.
    """
    eta_date = _to_date(fecha_eta)
    entrega_date = _to_date(fecha_entrega)

    if _state_in(estado_tracking, ('Entregado',)):
        if eta_date and entrega_date and entrega_date > eta_date:
            return ('Entregado con atraso', 'bg-danger')
        if eta_date and entrega_date and entrega_date <= eta_date:
            return ('Entregado a tiempo', 'bg-success')
        return ('Entregado', 'bg-success')

    if not eta_date:
        return ('Sin ETA', 'bg-secondary')

    dias_eta = (eta_date - date.today()).days
    if dias_eta > 7:
        return ('A tiempo', 'bg-success')
    if dias_eta > 2:
        return ('Proxima', 'bg-warning text-dark')
    return ('Urgente', 'bg-danger')

def _parse_iso_date(value):
    """Parsea fechas estrictas YYYY-MM-DD (mes y día en dos cifras); retorna None si es inválida."""
    raw = (value or '').strip()
    if not raw:
        return None
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _erp_scopes_softland_by_aux(user_role):
    """
    El filtro por CodAux en Softland aplica solo a VISUALIZADOR (y aliases).
    has_any_role(SUPERADMIN, ['VISUALIZADOR']) devuelve True para permisos, pero no debe
    acotar el ERP: un superadmin con aux_id_softland cargado dejaba el dashboard casi vacío.
    """
    r = str(user_role or '').strip().upper()
    if r in ('SUPERADMIN', 'ADMIN', 'ADMINISTRADOR'):
        return False
    return has_any_role(user_role, ['VISUALIZADOR'])


def _canonical_session_role(role_name):
    """Normaliza roles legacy para mantener permisos consistentes en UI y backend."""
    if has_any_role(role_name, ['SUPERADMIN']):
        return 'SUPERADMIN'
    if has_any_role(role_name, ['BODEGA']):
        return 'BODEGA'
    if has_any_role(role_name, ['FAENA']):
        return 'FAENA'
    if has_any_role(role_name, ['VISUALIZADOR']):
        return 'VISUALIZADOR'
    return (role_name or '').strip().upper()


def _label_fecha_tipo_bodega(fecha_tipo):
    """Etiqueta para el panel: qué significa el rango Desde/Hasta."""
    key = (fecha_tipo or 'emision').strip().lower()
    return {
        'emision': 'Fecha OC (emisión)',
        'eta': 'Fecha ETA / entrega estimada (ERP)',
        'entrega_faena': 'Entrega en faena (fecha real, local)',
    }.get(key, 'Fecha OC (emisión)')


def _folios_entrega_faena_por_rango(
    cursor_local,
    filtro_desde_date,
    filtro_hasta_date,
    filtro_desde_raw,
    filtro_hasta_raw,
    num_req_filtro_raw=None,
):
    """NumOc cuya última cabecera de tracking tiene FechaHoraEntrega en el rango (BD local).

    Sin Desde/Hasta, por defecto solo el año en curso. Si hay filtro de requisición y sin rango,
    no se aplica ese límite de año (la requisición puede corresponder a una entrega de otro ejercicio).
    """
    sql = """
        SELECT U.NumOc
        FROM (
            SELECT
                NumOc,
                FechaHoraEntrega,
                ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
            FROM DespachosTracking
        ) U
        WHERE U.rn = 1
          AND U.FechaHoraEntrega IS NOT NULL
    """
    params = []
    if filtro_desde_date:
        sql += " AND date(U.FechaHoraEntrega) >= ?"
        params.append(filtro_desde_raw)
    if filtro_hasta_date:
        sql += " AND date(U.FechaHoraEntrega) <= ?"
        params.append(filtro_hasta_raw)
    if not filtro_desde_date and not filtro_hasta_date:
        nr = (num_req_filtro_raw or "").strip()
        if not nr:
            sql += " AND YEAR(U.FechaHoraEntrega) = YEAR(NOW())"
    cursor_local.execute(sql, tuple(params))
    out = []
    for row in cursor_local.fetchall():
        if row and row[0] is not None:
            try:
                out.append(int(row[0]))
            except (TypeError, ValueError):
                continue
    return out


def _softland_year_predicate_bodega(fecha_tipo):
    if fecha_tipo == 'eta':
        return (
            "COALESCE(TRY_CONVERT(date, OC.FecFinalOC, 103), TRY_CONVERT(date, OC.FecFinalOC)) IS NOT NULL "
            "AND COALESCE(YEAR(TRY_CONVERT(date, OC.FecFinalOC, 103)), YEAR(TRY_CONVERT(date, OC.FecFinalOC))) = YEAR(GETDATE())"
        )
    return (
        "COALESCE(YEAR(TRY_CONVERT(date, OC.FechaOC, 103)), YEAR(TRY_CONVERT(date, OC.FechaOC))) = YEAR(GETDATE())"
    )


def _softland_date_expr_bodega(fecha_tipo):
    if fecha_tipo == 'eta':
        return "COALESCE(TRY_CONVERT(date, OC.FecFinalOC, 103), TRY_CONVERT(date, OC.FecFinalOC))"
    return "COALESCE(TRY_CONVERT(date, OC.FechaOC, 103), TRY_CONVERT(date, OC.FechaOC))"


def _build_bodega_fecha_where_prefix(
    fecha_tipo_raw,
    filtro_desde_date,
    filtro_hasta_date,
    filtro_desde_raw,
    filtro_hasta_raw,
    cursor_local,
    num_req_filtro_raw=None,
    cursor_softland=None,
    num_oc_filtro_raw=None,
    cc_filter_token=None,
    skip_year_predicate=False,
):
    """Prefijo WHERE común (año + rango) para consultas OW_vsnpTraeEncabezadoOCompra en panel bodega/consulta."""
    cc_token = (cc_filter_token or '').strip()
    cc_predicate = (
        "UPPER(LTRIM(RTRIM(COALESCE(NULLIF(LTRIM(RTRIM(OC.DescCC)), ''),"
        " NULLIF(LTRIM(RTRIM(OC.CodiCC)), ''), 'Sin CC')))) = ?"
    ) if cc_token else None
    if fecha_tipo_raw == 'entrega_faena':
        folios_ef = _folios_entrega_faena_por_rango(
            cursor_local,
            filtro_desde_date,
            filtro_hasta_date,
            filtro_desde_raw,
            filtro_hasta_raw,
            num_req_filtro_raw=num_req_filtro_raw,
        )
        nr_ef = (num_req_filtro_raw or "").strip()
        folios_req = []
        if nr_ef and cursor_softland is not None:
            folios_req = _folios_num_oc_por_requisicion_softland(cursor_softland, num_req_filtro_raw)
            req_ok = set(folios_req)
            folios_ef = [f for f in folios_ef if f in req_ok]
        if not folios_ef and nr_ef and folios_req:
            # Tracking local no cruza con la req (p. ej. sin FechaHoraEntrega en la última cabecera);
            # aun así mostrar el maestro ERP de esa requisición en lugar de devolver cero filas.
            folios_ef = list(folios_req)
        noc_s = (num_oc_filtro_raw or "").strip()
        if noc_s.isdigit():
            try:
                n_oc = int(noc_s)
                folios_ef = [f for f in folios_ef if f == n_oc]
                if not folios_ef:
                    folios_ef = [n_oc]
            except ValueError:
                pass
        if not folios_ef:
            return (["1=0"], [])
        in_sql, in_params = _sql_where_column_in_ints("OC.NumOc", folios_ef)
        parts = [in_sql]
        params = list(in_params)
        if cc_predicate:
            parts.append(cc_predicate)
            params.append(cc_token)
        return (parts, params)
    nr = (num_req_filtro_raw or '').strip()
    noc_skip = (num_oc_filtro_raw or "").strip().isdigit()
    if nr or noc_skip:
        # Requisición y/o N° OC: no limitar al año corriente del panel (OC de otro ejercicio).
        parts = []
        params = []
        col = _softland_date_expr_bodega(fecha_tipo_raw)
        if filtro_desde_date:
            parts.append(f"{col} >= ?")
            params.append(filtro_desde_raw)
        if filtro_hasta_date:
            parts.append(f"{col} <= ?")
            params.append(filtro_hasta_raw)
        if cc_predicate:
            parts.append(cc_predicate)
            params.append(cc_token)
        if not parts:
            return (["1=1"], [])
        return (parts, params)
    parts = []
    if not skip_year_predicate:
        parts.append(_softland_year_predicate_bodega(fecha_tipo_raw))
    params = []
    col = _softland_date_expr_bodega(fecha_tipo_raw)
    if filtro_desde_date:
        parts.append(f"{col} >= ?")
        params.append(filtro_desde_raw)
    if filtro_hasta_date:
        parts.append(f"{col} <= ?")
        params.append(filtro_hasta_raw)
    if cc_predicate:
        parts.append(cc_predicate)
        params.append(cc_token)
    if not parts:
        return (["1=1"], [])
    return (parts, params)


def _append_req_filter_to_parts(where_parts, where_params, num_req_raw):
    """Restringe OC a las que tienen línea en owreqoc con NumReq coincidente (exacto si es numérico, LIKE si no).

    Se enlaza por softland.owordencom.NumOC = OC.NumOc para no depender de NumInterOC en la vista maestra
    (puede ser NULL o inconsistente frente a owordencom).
    """
    nr = (num_req_raw or '').strip()
    if not nr or len(nr) > 80:
        return
    join_oc = (
        "EXISTS (SELECT 1 FROM softland.owreqoc Q WITH (NOLOCK) "
        "INNER JOIN softland.owordencom O WITH (NOLOCK) ON Q.NumInterOC = O.NumInterOC "
        "WHERE O.NumOC = OC.NumOc AND {cond})"
    )
    if nr.isdigit():
        where_parts.append(
            join_oc.format(
                cond="LTRIM(RTRIM(CAST(Q.NumReq AS NVARCHAR(100)))) = LTRIM(RTRIM(?))"
            )
        )
        where_params.append(nr)
    else:
        where_parts.append(
            join_oc.format(cond="CAST(Q.NumReq AS NVARCHAR(100)) LIKE ?")
        )
        where_params.append(f"%{nr}%")


def _append_num_oc_filter_to_parts(where_parts, where_params, num_oc_raw):
    """Restringe a una OC concreta por número de folio (NumOc)."""
    s = (num_oc_raw or "").strip()
    if not s or not s.isdigit():
        return
    try:
        n = int(s)
    except ValueError:
        return
    where_parts.append("OC.NumOc = ?")
    where_params.append(n)


def _folios_num_oc_por_requisicion_softland(cursor_s, num_req_raw):
    """Lista de NumOC en Softland vinculados a la requisición (misma lógica que el filtro EXISTS)."""
    nr = (num_req_raw or "").strip()
    if not nr or len(nr) > 80:
        return []
    if nr.isdigit():
        cursor_s.execute(
            """
            SELECT DISTINCT O.NumOC
            FROM softland.owreqoc Q WITH (NOLOCK)
            INNER JOIN softland.owordencom O WITH (NOLOCK) ON Q.NumInterOC = O.NumInterOC
            WHERE LTRIM(RTRIM(CAST(Q.NumReq AS NVARCHAR(100)))) = LTRIM(RTRIM(?))
            """,
            (nr,),
        )
    else:
        cursor_s.execute(
            """
            SELECT DISTINCT O.NumOC
            FROM softland.owreqoc Q WITH (NOLOCK)
            INNER JOIN softland.owordencom O WITH (NOLOCK) ON Q.NumInterOC = O.NumInterOC
            WHERE CAST(Q.NumReq AS NVARCHAR(100)) LIKE ?
            """,
            (f"%{nr}%",),
        )
    out = []
    for row in cursor_s.fetchall():
        if row and row[0] is not None:
            try:
                out.append(int(row[0]))
            except (TypeError, ValueError):
                continue
    return out


def _ensure_business_roles(cursor):
    """Crea/asegura roles de negocio y bootstrap mínimo de superadmin."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Roles (
            Id INT AUTO_INCREMENT PRIMARY KEY,
            Nombre VARCHAR(64) NOT NULL UNIQUE,
            Descripcion TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS UsuariosSistema (
            Id INT AUTO_INCREMENT PRIMARY KEY,
            Usuario VARCHAR(64) NOT NULL UNIQUE,
            NombreCompleto VARCHAR(255),
            RolId INT NOT NULL,
            Email VARCHAR(255) UNIQUE,
            PasswordHash VARCHAR(255) NOT NULL,
            Activo TINYINT NOT NULL DEFAULT 1,
            FOREIGN KEY (RolId) REFERENCES Roles(Id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    roles = [
        ('SUPERADMIN', 'Control total del sistema y gestión de usuarios'),
        ('BODEGA', 'Realiza el primer paso: importar y despachar a faena'),
        ('VISUALIZADOR', 'Solo consulta de información global'),
        ('FAENA', 'Recibe envíos asignados y sube evidencia fotográfica'),
        ('SUPERVISOR_CONTRATO', 'Consulta de requisiciones, órdenes de compra y estado de bodega'),
    ]
    for nombre, desc in roles:
        cursor.execute(
            "INSERT IGNORE INTO Roles (Nombre, Descripcion) VALUES (?, ?)",
            (nombre, desc),
        )

    # Bootstrap: si no existe ningún superadmin, promote cuenta 'admin'.
    cursor.execute("""
        SELECT 1 FROM UsuariosSistema U
        JOIN Roles R ON U.RolId = R.Id
        WHERE R.Nombre = 'SUPERADMIN'
    """)
    if not cursor.fetchone():
        cursor.execute("SELECT Id FROM UsuariosSistema WHERE Usuario = 'admin'")
        admin_row = cursor.fetchone()
        if admin_row:
            cursor.execute("SELECT Id FROM Roles WHERE Nombre = 'SUPERADMIN'")
            sa_role = cursor.fetchone()
            if sa_role:
                cursor.execute(
                    "UPDATE UsuariosSistema SET RolId = ? WHERE Usuario = 'admin'",
                    (sa_role[0],),
                )

def _migrate_legacy_to_envios(cursor, conn):
    """
    Migra DespachosTrackingDetalle + cabeceras En Ruta/Entregado hacia DespachosEnvio.
    Idempotente: no hace nada si DespachosEnvio ya tiene filas.
    """
    try:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'DespachosEnvio'"
        )
        if not cursor.fetchone():
            return
        cursor.execute("SELECT COUNT(*) FROM DespachosEnvio")
        if int(cursor.fetchone()[0] or 0) > 0:
            return
        cursor.execute("SELECT COUNT(*) FROM DespachosTrackingDetalle")
        if int(cursor.fetchone()[0] or 0) == 0:
            return

        cursor.execute("SELECT DISTINCT NumOc FROM DespachosTrackingDetalle")
        folios = [int(r[0]) for r in cursor.fetchall() if r and r[0] is not None]
        for num_oc in folios:
            cursor.execute("""
                SELECT Estado, GuiaDespacho, FechaHoraSalida, FechaHoraEntrega, UrlFotoEvidencia,
                       Transportista, Observaciones, RegistradoPor, transportista_asignado_id
                FROM DespachosTracking WHERE NumOc = ? ORDER BY Id DESC LIMIT 1
            """, (num_oc,))
            t = cursor.fetchone()
            if not t:
                continue
            estado_hdr = t[0] or 'En Ruta'
            if not _state_in(estado_hdr, ('En Ruta', 'Entregado')):
                estado_hdr = 'En Ruta'
            cursor.execute("""
                INSERT INTO DespachosEnvio (
                    NumOc, Estado, GuiaDespacho, FechaHoraSalida, FechaHoraEntrega, UrlFotoEvidencia,
                    Transportista, PatenteVehiculo, Observaciones, RegistradoPor, transportista_asignado_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                num_oc, estado_hdr, t[1], t[2], t[3], t[4], t[5], None, t[6], t[7], t[8],
            ))
            envio_id = cursor.lastrowid
            if not envio_id:
                continue
            cursor.execute("""
                INSERT INTO DespachosEnvioDetalle (
                    EnvioId, NumOc, GuiaDespacho, NumInterOC, NumLineaOc, CodProd, DescripcionProd,
                    CantidadSolicitada, CantidadEnviada, CantidadDisponibleBodega, EstadoLinea, FechaRegistro, FechaRecepcion, RecibidoPor
                )
                SELECT ?, NumOc, GuiaDespacho, NumInterOC, NumLineaOc, CodProd, DescripcionProd,
                       CantidadSolicitada, CantidadEnviada,
                       CantidadDisponibleBodega,
                       EstadoLinea, FechaRegistro, FechaRecepcion, RecibidoPor
                FROM DespachosTrackingDetalle WHERE NumOc = ?
            """, (envio_id, num_oc))
            cursor.execute("DELETE FROM DespachosTrackingDetalle WHERE NumOc = ?", (num_oc,))
        conn.commit()
        logger.info("Migración legacy DespachosTrackingDetalle -> DespachosEnvio completada.")
    except Exception as exc:
        logger.error(f"Migración a DespachosEnvio falló: {exc}", exc_info=True)
        conn.rollback()


def _normalize_oc_linea_num(val):
    """Unifica int/Decimal/float/str para que coincida la clave con el formulario (pyodbc)."""
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _bodega_envio_line_key(num_linea, codprod):
    """Misma clave que _sum_enviado_por_linea tras normalizar número de línea."""
    return (_normalize_oc_linea_num(num_linea), (str(codprod) if codprod is not None else '').strip() or 'N/A')


def _aggregate_softland_oc_items_by_line(items):
    """
    owordendet se consulta en modo agregado para evitar filas duplicadas por Codaux.
    Sin agregar, `ingresada` queda partida por fila: tras despachar el total recibido, cada sub-fila
    calcula pendiente mal y bloquea nuevos camiones el mismo día aunque haya más ingresado o saldo real.
    """
    if not items:
        return []
    buckets = {}
    key_order = []
    for it in items:
        k = _bodega_envio_line_key(it.get('num_linea'), it.get('codprod'))
        if k not in buckets:
            key_order.append(k)
            buckets[k] = dict(it)
            buckets[k]['qty_ingresada'] = float(it.get('qty_ingresada') or 0)
            buckets[k]['qty_solicitada'] = float(it.get('qty_solicitada') or 0)
        else:
            buckets[k]['qty_ingresada'] = float(buckets[k].get('qty_ingresada') or 0) + float(
                it.get('qty_ingresada') or 0
            )
            buckets[k]['qty_solicitada'] = max(
                float(buckets[k].get('qty_solicitada') or 0),
                float(it.get('qty_solicitada') or 0),
            )
    out = []
    for i, k in enumerate(key_order):
        v = buckets[k]
        v['idx'] = i
        qty_sol = float(v.get('qty_solicitada') or 0)
        qty_in = float(v.get('qty_ingresada') or 0)
        qsug = max(qty_sol - qty_in, 0.0)
        v['qty_sugerida'] = qsug if qsug > 1e-9 else qty_sol
        out.append(v)
    return out


def _sql_case_linea_despacho_parcial_bodega(alias):
    """1 si el envío bodega→faena no fue 'entero' en esa línea."""
    a = alias
    st = f"UPPER(REPLACE(COALESCE({a}.EstadoLinea, ''), '_', ' '))"
    return f"""(
            TRIM({st}) = 'PARCIAL'
            OR (
              {a}.CantidadSolicitada IS NOT NULL
              AND CAST({a}.CantidadEnviada AS DOUBLE) + 0.0001
                  < CAST({a}.CantidadSolicitada AS DOUBLE)
            )
            OR (
              {a}.CantidadDisponibleBodega IS NOT NULL
              AND CAST({a}.CantidadEnviada AS DOUBLE) + 0.0001
                  < CAST({a}.CantidadDisponibleBodega AS DOUBLE)
            )
          )"""


def _sum_enviado(cursor, num_oc, by_codprod=False, lock=False):
    """Suma CantidadEnviada en envíos no anulados.

    Si by_codprod=True agrupa por (linea, cod), si no solo por linea.
    Si lock=True agrega ``FOR UPDATE`` (MariaDB) para serializar escrituras
    concurrentes: requiere estar dentro de una transacción abierta.
    """
    lock_sql = " FOR UPDATE" if lock else ""
    if by_codprod:
        cursor.execute(f"""
            SELECT D.NumLineaOc, LTRIM(RTRIM(COALESCE(D.CodProd, ''))) AS CodProd,
                   SUM(CAST(D.CantidadEnviada AS DOUBLE)) AS Qty
            FROM DespachosEnvioDetalle D
            INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
            WHERE D.NumOc = ?
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
            GROUP BY D.NumLineaOc, LTRIM(RTRIM(COALESCE(D.CodProd, ''))){lock_sql}
        """, (num_oc,))
        sums = {}
        for row in cursor.fetchall():
            linea = _normalize_oc_linea_num(row[0])
            cod = (row[1] or '').strip() or 'N/A'
            sums[(linea, cod)] = sums.get((linea, cod), 0.0) + float(row[2] or 0)
        return sums
    cursor.execute(f"""
        SELECT D.NumLineaOc, SUM(CAST(D.CantidadEnviada AS DOUBLE)) AS Qty
        FROM DespachosEnvioDetalle D
        INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
        WHERE D.NumOc = ?
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
        GROUP BY D.NumLineaOc{lock_sql}
    """, (num_oc,))
    sums = {}
    for row in cursor.fetchall():
        linea = _normalize_oc_linea_num(row[0])
        if linea is not None:
            sums[linea] = sums.get(linea, 0.0) + float(row[1] or 0)
    return sums

def _sum_enviado_por_linea(cursor, num_oc, lock=False):
    return _sum_enviado(cursor, num_oc, by_codprod=True, lock=lock)

def _sum_enviado_por_numlinea(cursor, num_oc, lock=False):
    return _sum_enviado(cursor, num_oc, by_codprod=False, lock=lock)


def _compute_entrega_parcial_bodega_envio(despacho_items_softland, sent_map_before, selected_items, sent_map_line=None):
    """
    True si esta guía no agota la OC hacia faena: falta al menos una línea con saldo en bodega
    o alguna línea envía menos de lo disponible o menos de lo solicitado en OC.
    """
    def _prev_sent(num_linea, codprod):
        linea = _normalize_oc_linea_num(num_linea)
        if sent_map_line is not None and linea is not None:
            return _safe_decimal(sent_map_line.get(linea, 0))
        k = _bodega_envio_line_key(num_linea, codprod)
        return _safe_decimal(sent_map_before.get(k, 0))

    selected_keys = set()
    for item in selected_items or []:
        selected_keys.add(_bodega_envio_line_key(item[1], item[2]))
    for it in despacho_items_softland or []:
        qty_in = _safe_decimal(it.get('qty_ingresada'))
        if qty_in <= _QTY_TOLERANCE:
            continue
        k = _bodega_envio_line_key(it.get('num_linea'), it.get('codprod'))
        prev = _prev_sent(it.get('num_linea'), it.get('codprod'))
        pend = max(qty_in - prev, Decimal('0'))
        if pend <= _QTY_TOLERANCE:
            continue
        if k not in selected_keys:
            return True
    for item in selected_items or []:
        qty_in = _safe_decimal(item[5])
        prev = _prev_sent(item[1], item[2])
        pend = max(qty_in - prev, Decimal('0'))
        qty_send = _safe_decimal(item[6])
        qty_sol = _safe_decimal(item[4])
        if qty_send + _QTY_TOLERANCE < pend or qty_send + _QTY_TOLERANCE < qty_sol:
            return True
    return False


def _oc_has_pending_bodega_dispatch(cursor, num_oc, despacho_items_softland):
    """True si en Softland queda cantidad ingresada sin despachar en envíos registrados."""
    if not despacho_items_softland:
        return False
    sent_line = _sum_enviado_por_numlinea(cursor, num_oc)
    for item in despacho_items_softland:
        qty_in = _safe_decimal(item.get('qty_ingresada'))
        if qty_in <= 0:
            continue
        linea = _normalize_oc_linea_num(item.get('num_linea'))
        already = _safe_decimal(sent_line.get(linea, 0)) if linea is not None else Decimal('0')
        if qty_in - already > _QTY_TOLERANCE:
            return True
    return False


def _load_pending_bodega_dispatch_by_folio(cursor, folios):
    """Por OC: queda material recepcionado en bodega (Softland) aún no enviado en guías locales."""
    out = {}
    for raw in folios or []:
        try:
            fid = int(raw)
        except (TypeError, ValueError):
            continue
        try:
            items = _load_softland_oc_items(fid)
            out[fid] = _oc_has_pending_bodega_dispatch(cursor, fid, items)
        except Exception as exc:
            logger.warning("pending_bodega_dispatch OC %s: %s", fid, exc)
            out[fid] = False
    return out


def _oc_has_pending_warehouse_reception(despacho_items_softland):
    """
    True si en Softland la OC aún no está totalmente recepcionada en bodega:
    alguna línea con cantidad solicitada > ingresada (falta mercadería por llegar).
    """
    for item in despacho_items_softland or []:
        qty_in = _safe_decimal(item.get('qty_ingresada'))
        qty_sol = _safe_decimal(item.get('qty_solicitada'))
        if qty_sol <= _QTY_TOLERANCE:
            continue
        if qty_in + _QTY_TOLERANCE < qty_sol:
            return True
    return False


def _sync_despachos_tracking_header(cursor, conn, num_oc, despacho_items_softland=None):
    """
    Alinea DespachosTracking (una fila por OC) con el estado agregado de envíos:
    - Si hay al menos un envío En Ruta: refleja el más reciente (puede haber varios en ruta a la vez).
    - Si no hay En Ruta y queda material por despachar (vs Softland) o recepción de bodega
      incompleta (ingresada < solicitada en alguna línea): EN_BODEGA.
    - Si no hay En Ruta, recepción completa y no queda nada por despachar: Entregado.
    """
    items = despacho_items_softland
    if items is None:
        items = _load_softland_oc_items(num_oc)
    if not items:
        return

    cursor.execute("SELECT Id, ApiIdempotencyKey FROM DespachosTracking WHERE NumOc = ? ORDER BY Id DESC LIMIT 1", (num_oc,))
    trk = cursor.fetchone()
    if not trk:
        return

    trk_id = int(trk[0])

    # No sobreescribir filas creadas por la API externa (tienen idempotency key).
    if trk[1]:
        return
    cursor.execute("""
        SELECT Id, Estado, GuiaDespacho, FechaHoraSalida, FechaHoraEntrega, UrlFotoEvidencia,
               Transportista, Observaciones, transportista_asignado_id
        FROM DespachosEnvio
        WHERE NumOc = ? AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Estado, ''), '_', ' ')))) = 'EN RUTA'
        ORDER BY Id DESC
        LIMIT 1
    """, (num_oc,))
    en_ruta = cursor.fetchone()
    if en_ruta:
        cursor.execute("""
            UPDATE DespachosTracking SET
                Estado = ?,
                GuiaDespacho = ?,
                FechaHoraSalida = ?,
                FechaHoraEntrega = NULL,
                UrlFotoEvidencia = ?,
                Transportista = ?,
                Observaciones = ?,
                transportista_asignado_id = ?
            WHERE Id = ? AND ApiIdempotencyKey IS NULL
        """, (ST_EN_RUTA, en_ruta[2], en_ruta[3], en_ruta[5], en_ruta[6], en_ruta[7], en_ruta[8], trk_id))
        conn.commit()
        return

    pending_dispatch = _oc_has_pending_bodega_dispatch(cursor, num_oc, items)
    pending_reception = _oc_has_pending_warehouse_reception(items)

    # Verificar si algún envío entregado tuvo recepción parcial o rechazo en faena,
    # lo que indica mercadería que no llegó completa y podría requerir re-despacho.
    cursor.execute("""
        SELECT COUNT(1) FROM DespachosEnvio
        WHERE NumOc = ?
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Estado, ''), '_', ' ')))) = 'ENTREGADO'
          AND RecepcionParcialFaena = 1
    """, (num_oc,))
    has_partial_faena = int(cursor.fetchone()[0] or 0) > 0

    needs_bodega = pending_dispatch or pending_reception or (has_partial_faena and pending_dispatch)

    if needs_bodega:
        cursor.execute("""
            UPDATE DespachosTracking SET
                Estado = ?,
                GuiaDespacho = NULL,
                FechaHoraSalida = NULL,
                Transportista = NULL,
                transportista_asignado_id = NULL,
                UrlFotoEvidencia = NULL
            WHERE Id = ? AND ApiIdempotencyKey IS NULL
        """, (ST_EN_BODEGA, trk_id,))
    else:
        cursor.execute("""
            SELECT COUNT(1) FROM DespachosEnvio
            WHERE NumOc = ?
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
        """, (num_oc,))
        if int(cursor.fetchone()[0] or 0) == 0:
            # Sin envíos registrados: no marcar Entregado (p. ej. OC importada y sin llegada Softland).
            return
        cursor.execute("""
            SELECT MAX(FechaHoraEntrega), MAX(FechaHoraSalida)
            FROM DespachosEnvio
            WHERE NumOc = ? AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Estado, ''), '_', ' ')))) = 'ENTREGADO'
        """, (num_oc,))
        fe = cursor.fetchone()
        fecha_ent = fe[0] if fe else None
        fecha_sal = fe[1] if fe else None
        cursor.execute("""
            UPDATE DespachosTracking SET
                Estado = ?,
                FechaHoraEntrega = ?,
                FechaHoraSalida = COALESCE(?, FechaHoraSalida)
            WHERE Id = ?
        """, (ST_ENTREGADO, fecha_ent, fecha_sal, trk_id))
    conn.commit()


def _load_active_envio_id_by_folio(cursor, folios):
    """Último envío En Ruta por OC (para enlaces en dashboard)."""
    normalized = [int(f) for f in folios if f is not None]
    if not normalized:
        return {}
    placeholders = ",".join(["?"] * len(normalized))
    cursor.execute(
        f"""
        SELECT E.NumOc, MAX(E.Id) AS EnvioId
        FROM DespachosEnvio E
        WHERE E.NumOc IN ({placeholders})
          AND UPPER(LTRIM(RTRIM(REPLACE(E.Estado, '_', ' ')))) = 'EN RUTA'
        GROUP BY E.NumOc
        """,
        tuple(normalized),
    )
    return {int(r[0]): int(r[1]) for r in cursor.fetchall() if r and r[0] is not None and r[1] is not None}


def _add_column_if_missing(cursor, table, column, col_type):
    """Agrega columna si no existe (idempotente, MariaDB)."""
    from utils.dialect_sql import quote_ident
    _ALLOWED_TABLES = {
        'DespachosTracking', 'DespachosEnvio', 'DespachosEnvioDetalle',
        'DespachosTrackingDetalle', 'UsuariosSistema', 'Roles',
        'NotificacionesBodega', 'AuditLog',
    }
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Tabla no permitida: {table}")
    if not column.isidentifier():
        raise ValueError(f"Nombre de columna inválido: {column}")
    if not col_type or not all(c.isalnum() or c in '() ' for c in col_type):
        raise ValueError(f"Tipo de columna inválido: {col_type}")

    cursor.execute(
        "SELECT COLUMN_NAME FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND TABLE_NAME = ?",
        (table,),
    )
    existing = {row[0] for row in cursor.fetchall()}
    if column not in existing:
        sql = f"ALTER TABLE {quote_ident(table)} ADD COLUMN {quote_ident(column)} {col_type}"
        cursor.execute(sql)


def _ensure_id_autoincrement(cursor, table):
    """Si el PK ``Id`` de una tabla local fue creado sin AUTO_INCREMENT (instalaciones
    previas donde el schema se creó manualmente), aplica MODIFY COLUMN para habilitarlo.
    Sin esto, los INSERT sin Id explícito fallan con `Field 'Id' doesn't have a default value`.
    """
    try:
        cursor.execute(
            "SELECT EXTRA FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND TABLE_NAME = ? AND COLUMN_NAME = 'Id'",
            (table,),
        )
        row = cursor.fetchone()
        if row and 'auto_increment' not in (row[0] or '').lower():
            cursor.execute(
                f"ALTER TABLE {quote_ident(table)} MODIFY COLUMN Id INT NOT NULL AUTO_INCREMENT"
            )
            logger.info("Migración: %s.Id marcada como AUTO_INCREMENT", table)
    except Exception as exc:
        logger.warning("No se pudo habilitar AUTO_INCREMENT en %s.Id: %s", table, exc)


def _ensure_local_tracking_table(cursor, conn=None):
    """Asegura las tablas de tracking local (MariaDB)."""
    global _LOCAL_TRACKING_SCHEMA_READY
    if _LOCAL_TRACKING_SCHEMA_READY:
        return

    # ── DespachosTracking ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DespachosTracking (
            Id INT AUTO_INCREMENT PRIMARY KEY,
            NumOc INT NOT NULL,
            Estado VARCHAR(32) NOT NULL DEFAULT 'INGRESADO',
            FechaHoraSalida DATETIME,
            FechaHoraEntrega DATETIME,
            UrlFotoEvidencia TEXT,
            CodigoQR TEXT,
            RegistradoPor INT,
            Transportista VARCHAR(255),
            GuiaDespacho VARCHAR(64),
            Observaciones TEXT,
            transportista_asignado_id INT,
            ApiIdempotencyKey VARCHAR(128) UNIQUE,
            CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
            UpdatedAt DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosTracking_NumOc ON DespachosTracking(NumOc)")
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosTracking_Estado ON DespachosTracking(Estado)")

    # Columnas que pueden faltar en instalaciones previas
    for col, ctype in [
        ('RegistradoPor', 'INT'), ('Transportista', 'VARCHAR(255)'), ('GuiaDespacho', 'VARCHAR(64)'),
        ('Observaciones', 'TEXT'), ('FechaHoraSalida', 'DATETIME'), ('FechaHoraEntrega', 'DATETIME'),
        ('transportista_asignado_id', 'INT'), ('UrlFotoEvidencia', 'TEXT'),
        ('ApiIdempotencyKey', 'VARCHAR(128)'),
        ('CreatedAt', 'DATETIME'), ('UpdatedAt', 'DATETIME'),
    ]:
        _add_column_if_missing(cursor, 'DespachosTracking', col, ctype)
    _ensure_id_autoincrement(cursor, 'DespachosTracking')

    # ── DespachosTrackingDetalle ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DespachosTrackingDetalle (
            Id INT AUTO_INCREMENT PRIMARY KEY,
            NumOc INT NOT NULL,
            GuiaDespacho VARCHAR(64),
            NumInterOC INT,
            NumLineaOc INT,
            CodProd VARCHAR(64),
            DescripcionProd TEXT,
            CantidadSolicitada DOUBLE,
            CantidadEnviada DOUBLE NOT NULL DEFAULT 0,
            CantidadDisponibleBodega DOUBLE,
            EstadoLinea VARCHAR(32) NOT NULL DEFAULT 'EN_RUTA',
            FechaRegistro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FechaRecepcion DATETIME,
            RecibidoPor INT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosTrackingDetalle_NumOc ON DespachosTrackingDetalle(NumOc)")
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosTrackingDetalle_Estado ON DespachosTrackingDetalle(EstadoLinea)")
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosTrackingDetalle_Guia ON DespachosTrackingDetalle(GuiaDespacho)")

    for col, ctype in [
        ('GuiaDespacho', 'VARCHAR(64)'), ('NumInterOC', 'INT'), ('NumLineaOc', 'INT'),
        ('CodProd', 'VARCHAR(64)'), ('DescripcionProd', 'TEXT'), ('CantidadSolicitada', 'DOUBLE'),
        ('CantidadEnviada', 'DOUBLE'), ('EstadoLinea', 'VARCHAR(32)'), ('FechaRegistro', 'DATETIME'),
        ('FechaRecepcion', 'DATETIME'), ('RecibidoPor', 'INT'), ('CantidadDisponibleBodega', 'DOUBLE'),
    ]:
        _add_column_if_missing(cursor, 'DespachosTrackingDetalle', col, ctype)

    # ── DespachosEnvio ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DespachosEnvio (
            Id INT AUTO_INCREMENT PRIMARY KEY,
            NumOc INT NOT NULL,
            Estado VARCHAR(32) NOT NULL DEFAULT 'En Ruta',
            FechaHoraSalida DATETIME,
            FechaHoraEntrega DATETIME,
            UrlFotoEvidencia TEXT,
            RegistradoPor INT,
            Transportista VARCHAR(255),
            PatenteVehiculo VARCHAR(16),
            GuiaDespacho VARCHAR(64),
            Observaciones TEXT,
            transportista_asignado_id INT,
            FechaRegistro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            EntregaParcialBodega TINYINT NOT NULL DEFAULT 0,
            RecepcionParcialFaena TINYINT NOT NULL DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosEnvio_NumOc ON DespachosEnvio(NumOc)")
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosEnvio_Estado ON DespachosEnvio(Estado)")

    for col, ctype in [
        ('EntregaParcialBodega', 'TINYINT NOT NULL DEFAULT 0'),
        ('PatenteVehiculo', 'VARCHAR(16)'),
        ('RecepcionParcialFaena', 'TINYINT NOT NULL DEFAULT 0'),
    ]:
        _add_column_if_missing(cursor, 'DespachosEnvio', col, ctype)

    # ── DespachosEnvioDetalle ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DespachosEnvioDetalle (
            Id INT AUTO_INCREMENT PRIMARY KEY,
            EnvioId INT NOT NULL,
            NumOc INT NOT NULL,
            GuiaDespacho VARCHAR(64),
            NumInterOC INT,
            NumLineaOc INT,
            CodProd VARCHAR(64),
            DescripcionProd TEXT,
            CantidadSolicitada DOUBLE,
            CantidadEnviada DOUBLE NOT NULL DEFAULT 0,
            CantidadDisponibleBodega DOUBLE,
            EstadoLinea VARCHAR(32) NOT NULL DEFAULT 'EN_RUTA',
            FechaRegistro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FechaRecepcion DATETIME,
            RecibidoPor INT,
            CantidadRecibida DOUBLE,
            MotivoRechazo TEXT,
            FOREIGN KEY (EnvioId) REFERENCES DespachosEnvio(Id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosEnvioDetalle_EnvioId ON DespachosEnvioDetalle(EnvioId)")
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_DespachosEnvioDetalle_NumOc ON DespachosEnvioDetalle(NumOc)")

    for col, ctype in [
        ('CantidadDisponibleBodega', 'DOUBLE'), ('CantidadRecibida', 'DOUBLE'),
        ('MotivoRechazo', 'TEXT'),
    ]:
        _add_column_if_missing(cursor, 'DespachosEnvioDetalle', col, ctype)

    # ── Marcar EntregaParcialBodega en envíos existentes ──
    cursor.execute("""
        UPDATE DespachosEnvio
        SET EntregaParcialBodega = 1
        WHERE EntregaParcialBodega = 0
          AND UPPER(REPLACE(COALESCE(Estado, ''), '_', ' ')) NOT IN ('ANULADO', 'CANCELADO')
          AND EXISTS (
              SELECT 1 FROM DespachosEnvioDetalle D
              WHERE D.EnvioId = DespachosEnvio.Id
                AND (
                    UPPER(REPLACE(COALESCE(D.EstadoLinea, ''), '_', ' ')) = 'PARCIAL'
                    OR (
                        D.CantidadSolicitada IS NOT NULL
                        AND CAST(D.CantidadEnviada AS DOUBLE) + 0.0001 < CAST(D.CantidadSolicitada AS DOUBLE)
                    )
                )
          )
    """)
    cursor.execute("""
        UPDATE DespachosEnvio
        SET EntregaParcialBodega = 1
        WHERE EntregaParcialBodega = 0
          AND UPPER(REPLACE(COALESCE(Estado, ''), '_', ' ')) NOT IN ('ANULADO', 'CANCELADO')
          AND NumOc IN (
              SELECT E2.NumOc FROM DespachosEnvio E2
              WHERE UPPER(REPLACE(COALESCE(E2.Estado, ''), '_', ' ')) NOT IN ('ANULADO', 'CANCELADO')
              GROUP BY E2.NumOc HAVING COUNT(1) > 1
          )
    """)

    if conn:
        _migrate_legacy_to_envios(cursor, conn)

    # ── NotificacionesBodega ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS NotificacionesBodega (
            Id INT AUTO_INCREMENT PRIMARY KEY,
            EnvioId INT NOT NULL,
            GuiaDespacho VARCHAR(64),
            NumOc INT,
            CodProd VARCHAR(64),
            DescProd TEXT,
            CantEnviada DOUBLE,
            CantRecibida DOUBLE,
            MotivoRechazo TEXT,
            EstadoLinea VARCHAR(32),
            RecibidoPor VARCHAR(128),
            FechaRecepcion DATETIME,
            Leida TINYINT DEFAULT 0,
            FechaCreacion DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_NotificacionesBodega_Leida ON NotificacionesBodega(Leida)")
    cursor.execute("CREATE INDEX IF NOT EXISTS IX_NotificacionesBodega_EnvioId ON NotificacionesBodega(EnvioId)")

    _LOCAL_TRACKING_SCHEMA_READY = True


def _crear_notificaciones_bodega(conn, envio_id, guia, lineas_problema):
    """
    Crea notificaciones en la tabla NotificacionesBodega para líneas con discrepancias.

    Args:
        conn: Conexión a la base de datos
        envio_id: ID del envío (DespachosEnvio)
        guia: Número de guía de despacho
        lineas_problema: Lista de dicts con keys:
            - num_oc: Número OC
            - cod_prod: Código producto
            - desc_prod: Descripción producto
            - cant_enviada: Cantidad enviada
            - cant_recibida: Cantidad recibida
            - motivo: Motivo del rechazo/parcial
            - estado_linea: Estado de la línea (PARCIAL o RECHAZADO)
            - recibido_por: Usuario que recibió
    """
    if not lineas_problema:
        return

    try:
        cursor = conn.cursor()
        for linea in lineas_problema:
            cursor.execute("""
                INSERT INTO NotificacionesBodega
                (EnvioId, GuiaDespacho, NumOc, CodProd, DescProd,
                 CantEnviada, CantRecibida, MotivoRechazo, EstadoLinea,
                 RecibidoPor, FechaRecepcion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, UTC_TIMESTAMP())
            """, (
                envio_id,
                guia,
                linea.get('num_oc'),
                linea.get('cod_prod'),
                linea.get('desc_prod'),
                linea.get('cant_enviada'),
                linea.get('cant_recibida'),
                linea.get('motivo'),
                linea.get('estado_linea'),
                linea.get('recibido_por')
            ))
    except Exception as e:
        logger.warning(f"Error al crear notificación bodega: {str(e)}", exc_info=True)
        # No lanzamos excepción para no romper el flujo principal


def _get_softland_dashboard_cache(cache_key):
    cached = _SOFTLAND_DASHBOARD_CACHE.get(cache_key)
    if not cached:
        return None
    if cached['expires_at'] < time.time():
        _SOFTLAND_DASHBOARD_CACHE.pop(cache_key, None)
        return None
    return cached

def _set_softland_dashboard_cache(
    cache_key, rows, has_more=False, total_count=None, en_bodega_entrega_total=None
):
    _SOFTLAND_DASHBOARD_CACHE[cache_key] = {
        'rows': rows,
        'has_more': bool(has_more),
        'total_count': total_count,
        'en_bodega_entrega_total': en_bodega_entrega_total,
        'expires_at': time.time() + _SOFTLAND_CACHE_TTL_SECONDS,
    }

def _invalidate_softland_dashboard_cache(cache_key=None):
    """Invalida caché de dashboard. Si cache_key=None, limpia todo."""
    if cache_key:
        _SOFTLAND_DASHBOARD_CACHE.pop(cache_key, None)
    else:
        _SOFTLAND_DASHBOARD_CACHE.clear()

def _sanitize_next_url(next_url):
    """Evita anidar `next` y redirecciones externas."""
    if not next_url:
        return ''
    parsed = urllib.parse.urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return ''
    path = (parsed.path or '').strip()
    if not path.startswith('/'):
        return ''
    query_items = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query_items = [(k, v) for (k, v) in query_items if (k or '').lower() != 'next']
    query = urllib.parse.urlencode(query_items, doseq=True)
    return f"{path}?{query}" if query else path

def _normalize_patente(value):
    """Normaliza patente a formato estable (mayúsculas, sin espacios)."""
    raw = (value or "").strip().upper()
    if not raw:
        return ""
    compact = re.sub(r"\s+", "", raw)
    compact = compact.replace(".", "")
    compact = compact.replace("_", "-")
    compact = re.sub(r"[^A-Z0-9-]", "", compact)
    if len(compact) == 6 and "-" not in compact:
        compact = f"{compact[:4]}-{compact[4:]}"
    return compact


def _is_valid_patente(value):
    """Valida patente: 5-8 chars alfanuméricos, al menos 1 letra y 1 número, sin guiones dobles."""
    pat = _normalize_patente(value)
    if not pat or "--" in pat:
        return False
    return bool(re.fullmatch(r'[A-Z0-9-]{5,8}', pat) and re.search(r'[A-Z]', pat) and re.search(r'[0-9]', pat))

def _normalize_state_value(state_value):
    text = (state_value or '').strip().replace('_', ' ').upper()
    return " ".join(text.split())

def _canonical_tracking_state(state_value):
    normalized = _normalize_state_value(state_value)
    return _STORAGE_STATE_MAP.get(normalized, (state_value or '').strip())

def _state_in(state_value, accepted_states):
    normalized_state = _normalize_state_value(state_value)
    normalized_allowed = {_normalize_state_value(s) for s in accepted_states}
    return normalized_state in normalized_allowed

def _get_softland_fecha_column(cursor):
    """Resuelve compatibilidad entre esquemas (FechaOC vs Fecha)."""
    cursor.execute("""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'softland'
          AND TABLE_NAME = 'OW_vsnpTraeEncabezadoOCompra'
          AND COLUMN_NAME IN ('FechaOC', 'Fecha')
    """)
    cols = {row[0] for row in cursor.fetchall()}
    if 'FechaOC' in cols:
        return 'FechaOC'
    if 'Fecha' in cols:
        return 'Fecha'
    # Fallback defensivo
    return 'FechaOC'

def _resolve_softland_column(cursor, table_name, candidates):
    """Retorna la primera columna existente de una tabla Softland (si aplica)."""
    if not candidates:
        return None
    placeholders = ",".join(["?"] * len(candidates))
    cursor.execute(
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'softland'
          AND TABLE_NAME = ?
          AND COLUMN_NAME IN ({placeholders})
        """,
        tuple([table_name] + list(candidates)),
    )
    cols = {row[0] for row in cursor.fetchall()}
    for candidate in candidates:
        if candidate in cols:
            return candidate
    return None

def _get_evidence_upload_dir():
    upload_dir = current_app.config.get('EVIDENCE_UPLOAD_DIR')
    if not upload_dir:
        upload_dir = os.path.join(current_app.root_path, 'storage', 'evidencias')
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir

def _extract_evidence_filename(evidence_value):
    """Obtiene el nombre de archivo desde URL/ruta legacy de evidencia."""
    raw = (evidence_value or '').strip()
    if not raw:
        return None
    normalized = raw.replace('\\', '/')
    if '/evidencias/' in normalized:
        normalized = normalized.split('/evidencias/', 1)[1]
    filename = os.path.basename(normalized)
    filename = secure_filename(filename)
    return filename or None


def _extract_folio_from_evidence_filename(filename):
    """Obtiene folio desde nombres tipo despacho_<folio>_* o entrega_<folio>_*."""
    m = re.match(r"^(?:despacho|entrega)_(\d+)_", (filename or "").strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_evidencia_urls_field(evidence_value):
    """Una URL o lista JSON de URLs guardada en UrlFotoEvidencia."""
    raw = (evidence_value or '').strip()
    if not raw:
        return []
    if raw.startswith('['):
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except Exception:
            pass
    return [raw]


def _resolve_evidence_url_for_part(evidence_part):
    """Resuelve una sola URL/ruta de evidencia a /evidencias/<file> si el archivo existe."""
    filename = _extract_evidence_filename(evidence_part)
    if not filename:
        return None
    file_path = os.path.join(_get_evidence_upload_dir(), filename)
    if os.path.isfile(file_path):
        return url_for('frontend.get_evidencia', filename=filename)
    return None


def _faena_recepcion_evidence_urls(evidence_value):
    """
    Solo fotos subidas en recepción Faena (prefijo entrega_<folio>_).
    Excluye evidencia de despacho bodega (despacho_*) para no mostrarla como entrega.
    """
    out = []
    seen = set()
    for part in _parse_evidencia_urls_field(evidence_value):
        fn = (_extract_evidence_filename(part) or '').lower()
        if not fn.startswith('entrega_'):
            continue
        u = _resolve_evidence_url_for_part(part)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _load_faena_recepcion_evidence_urls_por_oc(cursor, num_oc):
    """Todas las URLs de evidencia de recepción Faena ya registradas para la OC (envíos Entregado)."""
    accumulated = []
    seen = set()
    try:
        cursor.execute(
            """
            SELECT UrlFotoEvidencia
            FROM DespachosEnvio
            WHERE NumOc = ?
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Estado, ''), '_', ' ')))) = 'ENTREGADO'
              AND UrlFotoEvidencia IS NOT NULL
              AND LTRIM(RTRIM(UrlFotoEvidencia)) <> ''
            ORDER BY Id ASC
            """,
            (int(num_oc),),
        )
        for row in cursor.fetchall():
            for u in _faena_recepcion_evidence_urls(row[0]):
                if u not in seen:
                    seen.add(u)
                    accumulated.append(u)
    except Exception:
        pass
    return accumulated


def _resolve_evidence_urls_all(cursor, folio, evidence_value, envio_id=None):
    """Todas las evidencias resueltas (p. ej. varias fotos por guía)."""
    out = []
    for part in _parse_evidencia_urls_field(evidence_value):
        u = _resolve_evidence_url_for_part(part)
        if u:
            out.append(u)
    if out:
        return out
    legacy = _resolve_evidence_url(cursor, folio, evidence_value, envio_id=envio_id)
    return [legacy] if legacy else []


def _pendiente_bodega(ing, sent):
    """Resta ingresado − enviado con Decimal para evitar residuos float."""
    p = max(Decimal(str(ing or 0)) - Decimal(str(sent or 0)), Decimal('0'))
    return float(p.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP))

def _latest_evidence_filename_for_folio(folio):
    """Busca la evidencia más reciente en disco para un folio."""
    try:
        folio = int(folio)
    except Exception:
        return None
    upload_dir = _get_evidence_upload_dir()
    if not os.path.isdir(upload_dir):
        return None

    prefixes = (f"entrega_{folio}_", f"despacho_{folio}_")
    candidates = []
    for name in os.listdir(upload_dir):
        if name.startswith(prefixes):
            full_path = os.path.join(upload_dir, name)
            if os.path.isfile(full_path):
                try:
                    mtime = os.path.getmtime(full_path)
                except OSError:
                    mtime = 0
                candidates.append((mtime, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]

def _resolve_evidence_url(cursor, folio=None, evidence_value=None, envio_id=None):
    """
    Devuelve URL funcional /evidencias/<file> priorizando:
    1) valor guardado en BD si existe en disco (una o varias URLs en JSON),
    2) historial BD del mismo folio,
    3) fallback por patrón de nombre en disco.
    """
    for part in _parse_evidencia_urls_field(evidence_value):
        hit = _resolve_evidence_url_for_part(part)
        if hit:
            return hit

    try:
        folio_int = int(folio) if folio is not None else None
    except Exception:
        folio_int = None

    if cursor is not None and envio_id is not None:
        try:
            cursor.execute(
                """
                SELECT UrlFotoEvidencia
                FROM DespachosEnvio
                WHERE Id = ?
                LIMIT 1
                """,
                (int(envio_id),),
            )
            row = cursor.fetchone()
            if row and row[0]:
                for part in _parse_evidencia_urls_field(row[0]):
                    hit = _resolve_evidence_url_for_part(part)
                    if hit:
                        return hit
        except Exception:
            pass

    if cursor is not None and folio_int is not None:
        cursor.execute("""
            SELECT UrlFotoEvidencia
            FROM DespachosTracking
            WHERE NumOc = ?
              AND UrlFotoEvidencia IS NOT NULL
            ORDER BY Id DESC
            LIMIT 10
        """, (folio_int,))
        for row in cursor.fetchall():
            for part in _parse_evidencia_urls_field(row[0]):
                candidate_name = _extract_evidence_filename(part)
                if not candidate_name:
                    continue
                candidate_path = os.path.join(_get_evidence_upload_dir(), candidate_name)
                if os.path.isfile(candidate_path):
                    return url_for('frontend.get_evidencia', filename=candidate_name)

    latest_name = _latest_evidence_filename_for_folio(folio_int) if folio_int is not None else None
    if latest_name:
        return url_for('frontend.get_evidencia', filename=latest_name)
    return None

def _load_softland_oc_items(folio):
    """Obtiene líneas de OC en Softland para checklist de despacho parcial/total."""

    conn = None
    try:
        conn = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
        cursor = conn.cursor()
        od_cc_col = _resolve_softland_column(cursor, 'owordendet', ('CodiCC', 'CodCC', 'CentroCosto'))
        o_cc_col = _resolve_softland_column(cursor, 'owordencom', ('CodiCC', 'CodCC', 'CentroCosto'))
        od_cc_expr = f"NULLIF(LTRIM(RTRIM(CAST(OD.[{od_cc_col}] AS NVARCHAR(120)))), '')" if od_cc_col else "NULL"
        o_cc_expr = f"NULLIF(LTRIM(RTRIM(CAST(O.[{o_cc_col}] AS NVARCHAR(120)))), '')" if o_cc_col else "NULL"
        cc_line_expr = f"COALESCE({od_cc_expr}, {o_cc_expr}, 'Sin CC')"

        sql_by_line = f"""
            SELECT
                O.NumInterOC,
                OD.NumLinea,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(OD.CodProd)), ''),
                    NULLIF(LTRIM(RTRIM(P.CodProd)), '')
                ) AS CodProd,
                COALESCE(
                    NULLIF(LTRIM(RTRIM(CAST(OD.DetProd AS NVARCHAR(4000)))), ''),
                    NULLIF(LTRIM(RTRIM(P.DesProd)), ''),
                    'Sin descripción'
                ) AS DescripcionProd,
                TRY_CONVERT(DECIMAL(18,4), COALESCE(OD.Cantidad, 0)) AS CantidadSolicitada,
                TRY_CONVERT(DECIMAL(18,4), COALESCE(OD.Recibido, 0)) AS CantidadIngresada,
                {cc_line_expr} AS CentroCostoLinea
            FROM softland.owordencom O
            LEFT JOIN softland.owordendet OD
                ON OD.NumInterOC = O.NumInterOC
            LEFT JOIN softland.IW_vsnpProductos P
                ON P.CodProd = NULLIF(LTRIM(RTRIM(OD.CodProd)), '')
            WHERE O.NumOC = ?
            ORDER BY OD.NumLinea, CodProd
        """
        cursor.execute(sql_by_line, (folio,))
        rows = cursor.fetchall()
        items = []
        for idx, row in enumerate(rows):
            num_inter = int(row[0]) if row[0] is not None else None
            num_linea = int(row[1]) if row[1] is not None else None
            codprod = (row[2] or '').strip()
            descripcion = (row[3] or '').strip() or 'Sin descripción'
            qty_solicitada = float(row[4] or 0)
            qty_ingresada = float(row[5] or 0)
            centro_costo_linea = (row[6] or '').strip() or 'Sin CC'
            qty_sugerida = max(qty_solicitada - qty_ingresada, 0.0)
            if num_linea is None and not codprod:
                continue
            items.append({
                'idx': idx,
                'num_interoc': num_inter,
                'num_linea': num_linea,
                'codprod': codprod or 'N/A',
                'descripcion': descripcion,
                'qty_solicitada': qty_solicitada,
                'qty_ingresada': qty_ingresada,
                'qty_sugerida': qty_sugerida if qty_sugerida > 0 else qty_solicitada,
                'centro_costo_linea': centro_costo_linea,
            })
        return _aggregate_softland_oc_items_by_line(items)
    except Exception as exc:
        logger.warning(f"No fue posible cargar items Softland para OC {folio}: {exc}")
        return []
    finally:
        if conn:
            conn.close()

def _summarize_softland_arrival(despacho_items):
    """Resume cantidades solicitadas/ingresadas para habilitar despacho."""
    total_solicitada = 0.0
    total_ingresada = 0.0
    for item in (despacho_items or []):
        try:
            total_solicitada += float(item.get('qty_solicitada') or 0)
        except Exception:
            pass
        try:
            total_ingresada += float(item.get('qty_ingresada') or 0)
        except Exception:
            pass
    return {
        'total_solicitada': total_solicitada,
        'total_ingresada': total_ingresada,
        'has_any_arrival': total_ingresada > 0,
    }

def _load_partial_flags_by_folio(cursor, folios):
    """Retorna bandera de envío parcial (bodega→faena) por OC para vistas operativas."""
    normalized = [int(f) for f in folios if f is not None]
    if not normalized:
        return {}
    placeholders = ",".join(["?"] * len(normalized))
    line_parcial = _sql_case_linea_despacho_parcial_bodega("X")
    cursor.execute(
        f"""
        SELECT T.NumOc, MAX(T.Flg) AS TieneParcial
        FROM (
            SELECT X.NumOc, MAX(CASE WHEN {line_parcial} THEN 1 ELSE 0 END) AS Flg
            FROM (
                SELECT D.NumOc, D.EstadoLinea, D.CantidadEnviada, D.CantidadSolicitada, D.CantidadDisponibleBodega
                FROM DespachosEnvioDetalle D
                INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
                WHERE D.NumOc IN ({placeholders})
                  AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
                UNION ALL
                SELECT LD.NumOc, LD.EstadoLinea, LD.CantidadEnviada, LD.CantidadSolicitada, LD.CantidadDisponibleBodega
                FROM DespachosTrackingDetalle LD
                WHERE LD.NumOc IN ({placeholders})
                  AND NOT EXISTS (SELECT 1 FROM DespachosEnvioDetalle D2 WHERE D2.NumOc = LD.NumOc)
            ) AS X
            GROUP BY X.NumOc
            UNION ALL
            SELECT E.NumOc, 1 AS Flg
            FROM DespachosEnvio E
            WHERE E.NumOc IN ({placeholders})
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
              AND E.EntregaParcialBodega = 1
        ) AS T
        GROUP BY T.NumOc
        """,
        tuple(normalized + normalized + normalized),
    )
    return {int(r[0]): int(r[1] or 0) for r in cursor.fetchall()}


def _load_sent_totals_by_folio(cursor, folios):
    """Suma enviada por OC (solo envíos vigentes) para decidir si aún se puede despachar."""
    normalized = [int(f) for f in (folios or []) if f is not None]
    if not normalized:
        return {}
    placeholders = ",".join(["?"] * len(normalized))
    cursor.execute(
        f"""
        SELECT E.NumOc, SUM(COALESCE(D.CantidadEnviada, 0)) AS QtyEnviada
        FROM DespachosEnvio E
        INNER JOIN DespachosEnvioDetalle D ON D.EnvioId = E.Id
        WHERE E.NumOc IN ({placeholders})
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
        GROUP BY E.NumOc
        """,
        tuple(normalized),
    )
    return {int(r[0]): float(r[1] or 0.0) for r in cursor.fetchall()}

def _folios_linea_parcial_despacho_bodega(cursor):
    """Folios con envío parcial bodega→faena (cabecera marcada o líneas de detalle)."""
    line_cond_d = _sql_case_linea_despacho_parcial_bodega("D").strip()
    line_cond_ld = _sql_case_linea_despacho_parcial_bodega("LD").strip()
    cursor.execute(
        f"""
        SELECT DISTINCT E.NumOc
        FROM DespachosEnvio E
        WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
          AND E.EntregaParcialBodega = 1
        UNION
        SELECT DISTINCT D.NumOc
        FROM DespachosEnvioDetalle D
        INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
        WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
          AND ({line_cond_d})
        UNION
        SELECT DISTINCT LD.NumOc
        FROM DespachosTrackingDetalle LD
        WHERE NOT EXISTS (SELECT 1 FROM DespachosEnvioDetalle D2 WHERE D2.NumOc = LD.NumOc)
          AND ({line_cond_ld})
        UNION
        SELECT M.NumOc
        FROM (
            SELECT E2.NumOc
            FROM DespachosEnvio E2
            WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E2.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
            GROUP BY E2.NumOc
            HAVING COUNT(1) > 1
        ) M
        """
    )
    out = []
    for r in cursor.fetchall():
        if r and r[0] is not None:
            try:
                out.append(int(r[0]))
            except (TypeError, ValueError):
                pass
    return sorted(set(out))


def _folios_entrega_parcial_bodega_safe(cursor):
    """Lista de folios para el filtro; si la consulta enriquecida falla (esquema antiguo), usa consulta mínima."""
    try:
        return _folios_linea_parcial_despacho_bodega(cursor)
    except Exception as exc:
        logger.warning(
            "Folios entrega parcial bodega→faena: consulta completa falló (%s); usando resumen por cabecera.",
            exc,
        )
        try:
            cursor.execute(
                """
                SELECT DISTINCT E.NumOc
                FROM DespachosEnvio E
                WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
                  AND E.EntregaParcialBodega = 1
                UNION
                SELECT M.NumOc
                FROM (
                    SELECT E2.NumOc
                    FROM DespachosEnvio E2
                    WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E2.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
                    GROUP BY E2.NumOc
                    HAVING COUNT(1) > 1
                ) M
                """
            )
            out = []
            for r in cursor.fetchall():
                if r and r[0] is not None:
                    try:
                        out.append(int(r[0]))
                    except (TypeError, ValueError):
                        pass
            return sorted(set(out))
        except Exception as exc2:
            logger.warning("Folios entrega parcial (resumen): %s", exc2)
            return []


def _master_data_entrega_parcial_sin_softland(folios_envio_parcial, row_offset, page_size):
    """Solo lectura local: filas mínimas cuando no hay conexión o falla la consulta a Softland."""
    ids_all = sorted({int(x) for x in (folios_envio_parcial or []) if x is not None}, reverse=True)
    total = len(ids_all)
    if not total:
        return [], False, 0
    win = ids_all[row_offset : row_offset + page_size + 1]
    has_more = len(win) > page_size
    page_folios = win[:page_size]
    master_data = []
    for fid in page_folios:
        master_data.append(
            (
                int(fid),
                None,
                None,
                'Sin datos ERP (solo local)',
                'Sin requisición',
                'Sin CC',
                0,
                0,
                0,
                0.0,
                0.0,
            )
        )
    return master_data, has_more, total


def _reference_dates_entrega_parcial_local(cursor, folios):
    """
    Fecha máxima local (envío o tracking) por OC, para acotar stubs del filtro
    entrega_parcial_faena cuando hay Desde/Hasta y el ERP no devuelve la cabecera.
    """
    if not cursor or not folios:
        return {}
    in_e, pe = _sql_where_column_in_ints("E.NumOc", folios)
    in_d, pd = _sql_where_column_in_ints("D.NumOc", folios)
    cancel = (
        "UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) "
        "NOT IN ('ANULADO', 'CANCELADO')"
    )
    cursor.execute(
        f"""
        SELECT X.NumOc, MAX(X.Fd) FROM (
            SELECT E.NumOc, date(COALESCE(E.FechaHoraSalida, E.FechaRegistro)) AS Fd
            FROM DespachosEnvio E
            WHERE {in_e}
              AND {cancel}
            UNION ALL
            SELECT D.NumOc, date(COALESCE(D.FechaHoraSalida, D.FechaHoraEntrega)) AS Fd
            FROM DespachosTracking D
            WHERE {in_d}
        ) X
        GROUP BY X.NumOc
        """,
        tuple(pe + pd),
    )
    out = {}
    for row in cursor.fetchall():
        if not row or row[0] is None or row[1] is None:
            continue
        fd = row[1]
        if isinstance(fd, datetime):
            fd = fd.date()
        elif isinstance(fd, str):
            fd = _parse_iso_date(str(fd)[:10])
            if fd is None:
                continue
        elif not isinstance(fd, date):
            continue
        try:
            out[int(row[0])] = fd
        except (TypeError, ValueError):
            pass
    return out


def _fetch_latest_tracking_rows_by_folio(cursor, folios):
    """Una fila por OC: la más reciente por Id (evita estado mezclado con histórico)."""
    normalized = []
    for f in folios or []:
        if f is None:
            continue
        try:
            normalized.append(int(f))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return {}
    placeholders = ",".join(["?"] * len(normalized))
    cursor.execute(
        f"""
        SELECT NumOc, Estado, FechaHoraSalida, FechaHoraEntrega, transportista_asignado_id
        FROM (
            SELECT
                NumOc, Estado, FechaHoraSalida, FechaHoraEntrega, transportista_asignado_id,
                ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
            FROM DespachosTracking
            WHERE NumOc IN ({placeholders})
        ) X
        WHERE X.rn = 1
        """,
        tuple(normalized),
    )
    out = {}
    for row in cursor.fetchall():
        if row and row[0] is not None:
            try:
                out[int(row[0])] = row
            except (TypeError, ValueError):
                continue
    return out


def _folios_tracking_en_ruta(cursor, filtro_desde_date, filtro_hasta_date, filtro_desde_raw, filtro_hasta_raw):
    """
    OCs cuya cabecera de tracking vigente (última por Id) está EN RUTA (definición alineada con sync).
    Desde/Hasta opcionales sobre fecha de salida desde bodega.
    """
    cap = int(_DASHBOARD_FILTER_IDS_CAP)
    sql = f"""
        WITH Ultimo AS (
            SELECT
                NumOc,
                Estado,
                FechaHoraSalida,
                ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
            FROM DespachosTracking
        )
        SELECT NumOc
        FROM Ultimo
        WHERE rn = 1
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Estado, ''), '_', ' ')))) = 'EN RUTA'
    """
    params = []
    if filtro_desde_date:
        sql += " AND (FechaHoraSalida IS NULL OR date(FechaHoraSalida) >= ?)"
        params.append(filtro_desde_raw)
    if filtro_hasta_date:
        sql += " AND (FechaHoraSalida IS NULL OR date(FechaHoraSalida) <= ?)"
        params.append(filtro_hasta_raw)
    sql += f" ORDER BY FechaHoraSalida DESC, NumOc DESC LIMIT {cap}"
    cursor.execute(sql, tuple(params))
    out = []
    for row in cursor.fetchall():
        if row and row[0] is not None:
            try:
                out.append(int(row[0]))
            except (TypeError, ValueError):
                continue
    return out


def _folios_tracking_entregado(
    cursor, filtro_desde_date, filtro_hasta_date, filtro_desde_raw, filtro_hasta_raw
):
    """
    OCs cuya cabecera de tracking vigente (última por Id) está ENTREGADO.
    Rango Desde/Hasta sobre fecha de entrega en faena (o salida si no hay entrega).
    """
    cap = int(_DASHBOARD_FILTER_IDS_CAP)
    sql = f"""
        WITH Ultimo AS (
            SELECT
                NumOc,
                Estado,
                FechaHoraEntrega,
                FechaHoraSalida,
                ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
            FROM DespachosTracking
        )
        SELECT NumOc
        FROM Ultimo
        WHERE rn = 1
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Estado, ''), '_', ' ')))) = 'ENTREGADO'
    """
    params = []
    if filtro_desde_date:
        sql += (
            " AND (COALESCE(FechaHoraEntrega, FechaHoraSalida) IS NULL "
            "OR date(COALESCE(FechaHoraEntrega, FechaHoraSalida)) >= ?)"
        )
        params.append(filtro_desde_raw)
    if filtro_hasta_date:
        sql += (
            " AND (COALESCE(FechaHoraEntrega, FechaHoraSalida) IS NULL "
            "OR date(COALESCE(FechaHoraEntrega, FechaHoraSalida)) <= ?)"
        )
        params.append(filtro_hasta_raw)
    sql += f" ORDER BY COALESCE(FechaHoraEntrega, FechaHoraSalida) DESC, NumOc DESC LIMIT {cap}"
    cursor.execute(sql, tuple(params))
    out = []
    for row in cursor.fetchall():
        if row and row[0] is not None:
            try:
                out.append(int(row[0]))
            except (TypeError, ValueError):
                continue
    return out


def _load_master_data_entrega_parcial_faena(
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
    cursor_local=None,
    num_req_filtro_raw=None,
    num_oc_filtro_raw=None,
    cc_filter_token=None,
):
    """
    Pagina por folios con despacho parcial en BD local (no solo por OFFSET en Softland).
    Si la OC no aparece en OW_vsnpTraeEncabezadoOCompra, igual muestra una fila mínima
    para que el filtro no quede vacío cuando el maestro ERP no trae esa OC.
    """
    ids_all = sorted({int(x) for x in (folios_envio_parcial or []) if x is not None}, reverse=True)
    total = len(ids_all)
    if not total:
        return [], False, 0
    win = ids_all[row_offset : row_offset + page_size + 1]
    has_more = len(win) > page_size
    page_folios = win[:page_size]
    where_parts = ["1=1"]
    wp = []
    if filtro_desde_date:
        where_parts.append(
            "COALESCE(TRY_CONVERT(date, OC.FechaOC, 103), TRY_CONVERT(date, OC.FechaOC)) >= ?"
        )
        wp.append(filtro_desde_raw)
    if filtro_hasta_date:
        where_parts.append(
            "COALESCE(TRY_CONVERT(date, OC.FechaOC, 103), TRY_CONVERT(date, OC.FechaOC)) <= ?"
        )
        wp.append(filtro_hasta_raw)
    if _erp_scopes_softland_by_aux(user_role) and aux_id_softland:
        where_parts.append(
            "EXISTS (SELECT 1 FROM softland.owordencom OH WITH (NOLOCK) WHERE OH.NumInterOC = OC.NumInterOc AND OH.CodAux = ?)"
        )
        wp.append(aux_id_softland)
    if num_req_filtro_raw:
        _append_req_filter_to_parts(where_parts, wp, num_req_filtro_raw)
    _append_num_oc_filter_to_parts(where_parts, wp, num_oc_filtro_raw)
    cc_token_norm = (cc_filter_token or '').strip()
    if cc_token_norm:
        where_parts.append(
            "UPPER(LTRIM(RTRIM(COALESCE(NULLIF(LTRIM(RTRIM(OC.DescCC)), ''),"
            " NULLIF(LTRIM(RTRIM(OC.CodiCC)), ''), 'Sin CC')))) = ?"
        )
        wp.append(cc_token_norm)
    in_sql, in_p = _sql_where_column_in_ints("OC.NumOc", page_folios)
    where_parts.append(in_sql)
    wp.extend(in_p)
    where_sql = " WHERE " + " AND ".join(where_parts)
    q = f"""
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
        {where_sql}
        ORDER BY OC.NumOc DESC
    """
    cursor_s.execute(q, tuple(wp))
    fetched = cursor_s.fetchall()
    by_f = {}
    for r in fetched:
        if r and r[0] is not None:
            by_f[int(r[0])] = r
    date_filtered = bool(filtro_desde_date or filtro_hasta_date)
    local_ref_dates = {}
    if cursor_local and page_folios:
        local_ref_dates = _reference_dates_entrega_parcial_local(cursor_local, page_folios)
    ordered = []
    for f in page_folios:
        fid = int(f)
        if fid in by_f:
            ordered.append(by_f[fid])
        else:
            # Cabecera no devuelta por ERP (alcance Codaux, fechas sobre FechaOC, caché, etc.):
            # igual mostrar fila mínima; antes se omitía para usuarios con alcance ERP y el listado quedaba vacío.
            if date_filtered:
                dref = local_ref_dates.get(fid)
                if dref is not None:
                    if filtro_desde_date and dref < filtro_desde_date:
                        continue
                    if filtro_hasta_date and dref > filtro_hasta_date:
                        continue
            if cc_token_norm and cc_token_norm != 'SIN CC':
                # Fila mínima sin CC conocido; si el usuario filtró por un CC específico, ocultarla.
                continue
            ordered.append(
                (
                    fid,
                    None,
                    None,
                    'OC no en vista ERP',
                    'Sin CC',
                    0,
                    None,
                    0,
                    0,
                    0.0,
                    0.0,
                )
            )
    num_inter_values = [r[6] for r in ordered if len(r) > 6 and r[6] is not None]
    req_map = {}
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
    for oc in ordered:
        num_inter = oc[6]
        master_data.append(
            (
                oc[0],
                oc[1],
                oc[2],
                oc[3] or 'Sin Proveedor',
                req_map.get(num_inter, 'Sin requisición'),
                oc[4] or 'Sin CC',
                oc[5],
                oc[7],
                oc[8],
                oc[9],
                oc[10],
            )
        )
    return master_data, has_more, total


def _sql_where_column_in_ints(column_expr, ids, chunk_size=400):
    """Fragmento SQL `col IN (?,?,...)` en bloques para no exceder límites de parámetros."""
    id_set = sorted({int(x) for x in (ids or []) if x is not None})
    if not id_set:
        return "0=1", []
    parts = []
    params = []
    for i in range(0, len(id_set), chunk_size):
        block = id_set[i : i + chunk_size]
        ph = ",".join(["?"] * len(block))
        parts.append(f"{column_expr} IN ({ph})")
        params.extend(block)
    if len(parts) == 1:
        return parts[0], params
    return "(" + " OR ".join(parts) + ")", params


def _reception_status_label_from_qty(need_rec, got_rec, has_open_transit):
    """
    need_rec: suma por línea del total OC hacia faena (CantidadSolicitada al despachar).
    got_rec: cantidades ya marcadas ENTREGADO en detalle.
    has_open_transit: aún hay guía o tracking (legacy) EN RUTA.
    """
    need = float(need_rec or 0)
    got = float(got_rec or 0)
    if need <= 1e-9 and got <= 1e-9:
        return 'No recepcionado'
    if got <= 1e-9:
        return 'No recepcionado'
    if has_open_transit or got + 1e-6 < need:
        return 'Recepcionado parcial'
    return 'Recepcionado completo'


def _resumen_indica_recepcion_parcial_faena(rec):
    """
    Parcial en faena si: falta cantidad vs tope OC, o bodega envió en olas / guía marcada parcial
    (ítems 3–4 hoy, 1–2 después) aunque esta guía quede recepcionada al100 %.
    """
    if not isinstance(rec, dict):
        return False
    got = float(rec.get('got_qty') or 0)
    need = float(rec.get('need_qty') or 0)
    erp_need = float(rec.get('erp_need_qty') or 0)
    if got <= 1e-9:
        return False
    lb = (rec.get('status_label') or '').strip()
    if lb == 'Recepcionado parcial':
        return True
    if erp_need > 1e-9 and got + 1e-6 >= erp_need:
        return False
    if need > 1e-9 and got + 1e-6 < need:
        return True
    if rec.get('trace_parcial_envio_bodega'):
        return True
    return False


def _open_transit_folios(cursor, folios):
    """OCs con envío o tracking (solo legacy) aún EN RUTA."""
    if not folios:
        return set()
    placeholders = ",".join(["?"] * len(folios))
    t = tuple(int(x) for x in folios)
    open_set = set()
    cursor.execute(
        f"""
        SELECT DISTINCT E.NumOc
        FROM DespachosEnvio E
        WHERE E.NumOc IN ({placeholders})
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) = 'EN RUTA'
        """,
        t,
    )
    for r in cursor.fetchall():
        if r and r[0] is not None:
            try:
                open_set.add(int(r[0]))
            except (TypeError, ValueError):
                pass
    cursor.execute(
        f"""
        SELECT T.NumOc
        FROM (
            SELECT
                NumOc,
                Estado,
                ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
            FROM DespachosTracking
            WHERE NumOc IN ({placeholders})
        ) T
        WHERE T.rn = 1
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(T.Estado, ''), '_', ' ')))) = 'EN RUTA'
          AND NOT EXISTS (SELECT 1 FROM DespachosEnvio E2 WHERE E2.NumOc = T.NumOc)
        """,
        t,
    )
    for r in cursor.fetchall():
        if r and r[0] is not None:
            try:
                open_set.add(int(r[0]))
            except (TypeError, ValueError):
                pass
    return open_set


def _softland_oc_qty_solicitada_total_map(folios):
    """
    NumOc -> suma de Cantidad (owordendet), mismo criterio que el dashboard.
    Sirve para que la recepción en faena siga «parcial» mientras falte cantidad de la OC en ERP,
    aunque la primera guía ya esté recepcionada al 100 %.
    """
    ids = sorted({int(x) for x in (folios or []) if x is not None})
    if not ids:
        return {}

    out = {}
    try:
        conn = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
        try:
            cur = conn.cursor()
            for i in range(0, len(ids), 400):
                chunk = ids[i : i + 400]
                ph = ",".join(["?"] * len(chunk))
                cur.execute(
                    f"""
                    SELECT OH.NumOC,
                           SUM(TRY_CONVERT(DECIMAL(18,4), COALESCE(D.Cantidad, 0)))
                    FROM softland.owordencom OH WITH (NOLOCK)
                    INNER JOIN softland.owordendet D WITH (NOLOCK)
                        ON D.NumInterOC = OH.NumInterOC
                    WHERE OH.NumOC IN ({ph})
                    GROUP BY OH.NumOC
                    """,
                    tuple(chunk),
                )
                for row in cur.fetchall():
                    if row and row[0] is not None:
                        try:
                            out[int(row[0])] = float(row[1] or 0)
                        except (TypeError, ValueError):
                            continue
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Softland cantidad OC (resumen recepción faena): %s", exc)
        return {}
    return out


def _bodega_envio_parcial_trace_by_folio(cursor, folios):
    """
    True si la OC tuvo (o tiene) programa de envío en varias tandas desde bodega:
    cabecera EntregaParcialBodega o más de una guía no anulada.
    """
    normalized = sorted({int(f) for f in (folios or []) if f is not None})
    if not normalized:
        return {}
    placeholders = ",".join(["?"] * len(normalized))
    t = tuple(normalized)
    out = {}
    cursor.execute(
        f"""
        SELECT E.NumOc,
               MAX(CASE WHEN E.EntregaParcialBodega = 1 THEN 1 ELSE 0 END) AS FlgParcial,
               COUNT(1) AS NGuia
        FROM DespachosEnvio E
        WHERE E.NumOc IN ({placeholders})
          AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' '))))
              NOT IN ('ANULADO', 'CANCELADO')
        GROUP BY E.NumOc
        """,
        t,
    )
    for row in cursor.fetchall():
        if not row or row[0] is None:
            continue
        try:
            fo = int(row[0])
            flg = int(row[1] or 0)
            n = int(row[2] or 0)
            out[fo] = bool(flg == 1 or n > 1)
        except (TypeError, ValueError):
            continue
    return out


def _load_reception_summary_by_folio(cursor, folios):
    """
    Resume recepción por OC (no/parcial/completa) según detalle local.
    Usa cantidades por línea (CantidadSolicitada = total línea OC al despachar) para que
    un envío parcial recibido siga en «Recepcionado parcial» hasta cubrir el total en faena.
    """
    normalized = [int(f) for f in folios if f is not None]
    if not normalized:
        return {}
    placeholders = ",".join(["?"] * len(normalized))
    params = tuple(normalized)
    open_transit = _open_transit_folios(cursor, normalized)
    summary = {}

    cursor.execute(
        f"""
        WITH L AS (
            SELECT
                D.NumOc,
                D.NumLineaOc,
                LTRIM(RTRIM(COALESCE(D.CodProd, ''))) AS CP,
                COALESCE(
                    NULLIF(MAX(CAST(D.CantidadSolicitada AS DOUBLE)), 0),
                    SUM(CAST(D.CantidadEnviada AS DOUBLE))
                ) AS LineTgt,
                SUM(CASE WHEN UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) IN ('ENTREGADO', 'PARCIAL')
                    THEN COALESCE(CAST(D.CantidadRecibida AS DOUBLE),
                                  CAST(D.CantidadEnviada AS DOUBLE), 0)
                    ELSE 0 END) AS QtyRec,
                MAX(CASE WHEN UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) = 'RECHAZADO' THEN 1 ELSE 0 END) AS HasRejected
            FROM DespachosEnvioDetalle D
            INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
            WHERE D.NumOc IN ({placeholders})
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' '))))
                  NOT IN ('ANULADO', 'CANCELADO')
            GROUP BY D.NumOc, D.NumLineaOc, LTRIM(RTRIM(COALESCE(D.CodProd, '')))
        ),
        O AS (
            SELECT NumOc, SUM(LineTgt) AS NeedRec, SUM(QtyRec) AS GotRec, MAX(HasRejected) AS HasRejected
            FROM L
            GROUP BY NumOc
        )
        SELECT NumOc, NeedRec, GotRec, HasRejected FROM O
        """,
        params,
    )
    for row in cursor.fetchall():
        if not row or row[0] is None:
            continue
        fo = int(row[0])
        need = float(row[1] or 0)
        got = float(row[2] or 0)
        has_rejected = bool(row[3]) if len(row) > 3 else False
        label = _reception_status_label_from_qty(need, got, fo in open_transit)
        summary[fo] = {
            'total_lineas': None,
            'lineas_entregadas': None,
            'need_qty': need,
            'got_qty': got,
            'status_label': label,
            'erp_need_qty': 0.0,
            'trace_parcial_envio_bodega': False,
            'has_rejected': has_rejected,
        }

    remaining = [f for f in normalized if f not in summary]
    if remaining:
        ph2 = ",".join(["?"] * len(remaining))
        t2 = tuple(remaining)
        cursor.execute(
            f"""
            WITH L AS (
                SELECT
                    LD.NumOc,
                    LD.NumLineaOc,
                    LTRIM(RTRIM(COALESCE(LD.CodProd, ''))) AS CP,
                    COALESCE(
                        NULLIF(MAX(CAST(LD.CantidadSolicitada AS DOUBLE)), 0),
                        SUM(CAST(LD.CantidadEnviada AS DOUBLE))
                    ) AS LineTgt,
                    SUM(CASE WHEN UPPER(LTRIM(RTRIM(COALESCE(LD.EstadoLinea, '')))) = 'ENTREGADO'
                        THEN CAST(LD.CantidadEnviada AS DOUBLE) ELSE 0 END) AS QtyRec
                FROM DespachosTrackingDetalle LD
                WHERE LD.NumOc IN ({ph2})
                  AND NOT EXISTS (SELECT 1 FROM DespachosEnvioDetalle D2 WHERE D2.NumOc = LD.NumOc)
                GROUP BY LD.NumOc, LD.NumLineaOc, LTRIM(RTRIM(COALESCE(LD.CodProd, '')))
            ),
            O AS (
                SELECT NumOc, SUM(LineTgt) AS NeedRec, SUM(QtyRec) AS GotRec
                FROM L
                GROUP BY NumOc
            )
            SELECT NumOc, NeedRec, GotRec FROM O
            """,
            t2,
        )
        for row in cursor.fetchall():
            if not row or row[0] is None:
                continue
            fo = int(row[0])
            need = float(row[1] or 0)
            got = float(row[2] or 0)
            label = _reception_status_label_from_qty(need, got, fo in open_transit)
            summary[fo] = {
                'total_lineas': None,
                'lineas_entregadas': None,
                'need_qty': need,
                'got_qty': got,
                'status_label': label,
                'erp_need_qty': 0.0,
                'trace_parcial_envio_bodega': False,
            }

    for f in normalized:
        if f not in summary:
            summary[f] = {
                'total_lineas': 0,
                'lineas_entregadas': 0,
                'need_qty': 0.0,
                'got_qty': 0.0,
                'status_label': 'No recepcionado',
                'erp_need_qty': 0.0,
                'trace_parcial_envio_bodega': False,
            }

    erp_need_by_folio = _softland_oc_qty_solicitada_total_map(normalized)
    trace_bodega = _bodega_envio_parcial_trace_by_folio(cursor, normalized)
    for f in normalized:
        rec = summary.get(f)
        if not rec:
            continue
        erp_need = float(erp_need_by_folio.get(f) or 0)
        rec['erp_need_qty'] = erp_need
        rec['trace_parcial_envio_bodega'] = bool(trace_bodega.get(f))
        if erp_need > 1e-9:
            rec['need_qty'] = max(float(rec.get('need_qty') or 0), erp_need)
        got = float(rec.get('got_qty') or 0)
        need = float(rec.get('need_qty') or 0)
        if rec['trace_parcial_envio_bodega'] and got > 1e-9 and erp_need <= 1e-9:
            rec['status_label'] = 'Recepcionado parcial'
        else:
            rec['status_label'] = _reception_status_label_from_qty(
                need, got, f in open_transit
            )
    return summary


def _folios_local_recepcion_parcial(cursor, num_oc_filtro_raw=None):
    """
    OCs con recepción parcial en faena (cantidad recibida < total líneas OC en guías),
    para trazabilidad multi-envío (p. ej. 2 ítems hoy, 2 después).
    """
    params = []
    raw = (num_oc_filtro_raw or "").strip()
    cap = int(_DASHBOARD_FILTER_IDS_CAP)
    fetch_cap = min(max(cap * 2, cap), 8000)

    if raw.isdigit():
        cands_sql = "SELECT ? AS NumOc"
        params.append(int(raw))
    else:
        # Por fecha de recepción real (no solo NumOc alto): histórico de parciales no se pierde.
        cands_sql = f"""
            SELECT X.NumOc FROM (
                SELECT
                    D.NumOc,
                    MAX(COALESCE(D.FechaRecepcion, D.FechaRegistro, E.FechaHoraEntrega, E.FechaHoraSalida)) AS LastEvt
                FROM DespachosEnvioDetalle D
                INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
                WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
                  AND UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) = 'ENTREGADO'
                  AND COALESCE(CAST(D.CantidadEnviada AS DOUBLE), 0) > 0
                GROUP BY D.NumOc
            ) X
            ORDER BY X.LastEvt DESC
            LIMIT {fetch_cap}
        """

    cursor.execute(
        f"""
        WITH Cands AS (
            {cands_sql}
        ),
        L AS (
            SELECT
                D.NumOc,
                D.NumLineaOc,
                LTRIM(RTRIM(COALESCE(D.CodProd, ''))) AS CP,
                COALESCE(
                    NULLIF(MAX(CAST(D.CantidadSolicitada AS DOUBLE)), 0),
                    SUM(CAST(D.CantidadEnviada AS DOUBLE))
                ) AS LineTgt,
                SUM(CASE WHEN UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) IN ('ENTREGADO', 'PARCIAL')
                    THEN COALESCE(CAST(D.CantidadRecibida AS DOUBLE),
                                  CAST(D.CantidadEnviada AS DOUBLE), 0)
                    ELSE 0 END) AS QtyRec
            FROM DespachosEnvioDetalle D
            INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
            INNER JOIN Cands C ON C.NumOc = D.NumOc
            WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' '))))
                  NOT IN ('ANULADO', 'CANCELADO')
            GROUP BY D.NumOc, D.NumLineaOc, LTRIM(RTRIM(COALESCE(D.CodProd, '')))
        ),
        O AS (
            SELECT NumOc, SUM(LineTgt) AS NeedRec, SUM(QtyRec) AS GotRec
            FROM L
            GROUP BY NumOc
        ),
        Op AS (
            SELECT DISTINCT E.NumOc
            FROM DespachosEnvio E
            INNER JOIN Cands C ON C.NumOc = E.NumOc
            WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) = 'EN RUTA'
        ),
        V AS (
            SELECT O.NumOc, O.NeedRec, O.GotRec,
                CASE WHEN Op.NumOc IS NULL THEN 0 ELSE 1 END AS HasOpen
            FROM O
            LEFT JOIN Op ON Op.NumOc = O.NumOc
        )
        SELECT V.NumOc
        FROM V
        WHERE V.GotRec > 0
          AND (
            V.HasOpen = 1
            OR V.GotRec + 0.000001 < V.NeedRec
            OR EXISTS (
                SELECT 1 FROM DespachosEnvio E
                WHERE E.NumOc = V.NumOc
                  AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' '))))
                      NOT IN ('ANULADO', 'CANCELADO')
                  AND E.EntregaParcialBodega = 1
            )
            OR EXISTS (
                SELECT 1 FROM (
                    SELECT E2.NumOc AS N2
                    FROM DespachosEnvio E2
                    WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E2.Estado, ''), '_', ' '))))
                        NOT IN ('ANULADO', 'CANCELADO')
                    GROUP BY E2.NumOc
                    HAVING COUNT(1) > 1
                ) M WHERE M.N2 = V.NumOc
            )
          )
        ORDER BY V.NumOc DESC
        LIMIT {fetch_cap}
        """,
        tuple(params),
    )
    out = []
    seen = set()
    for row in cursor.fetchall():
        if row and row[0] is not None:
            try:
                fo = int(row[0])
                if fo not in seen:
                    seen.add(fo)
                    out.append(fo)
            except (TypeError, ValueError):
                continue

    if not raw.isdigit():
        cursor.execute(
            f"""
            WITH Cands AS (
                SELECT X.NumOc FROM (
                    SELECT
                        LD.NumOc,
                        MAX(COALESCE(LD.FechaRecepcion, LD.FechaRegistro)) AS LastEvt
                    FROM DespachosTrackingDetalle LD
                    WHERE NOT EXISTS (SELECT 1 FROM DespachosEnvioDetalle D2 WHERE D2.NumOc = LD.NumOc)
                      AND UPPER(LTRIM(RTRIM(COALESCE(LD.EstadoLinea, '')))) = 'ENTREGADO'
                      AND COALESCE(CAST(LD.CantidadEnviada AS DOUBLE), 0) > 0
                    GROUP BY LD.NumOc
                ) X
                ORDER BY X.LastEvt DESC
                LIMIT {fetch_cap}
            ),
            L AS (
                SELECT
                    LD.NumOc,
                    LD.NumLineaOc,
                    LTRIM(RTRIM(COALESCE(LD.CodProd, ''))) AS CP,
                    COALESCE(
                        NULLIF(MAX(CAST(LD.CantidadSolicitada AS DOUBLE)), 0),
                        SUM(CAST(LD.CantidadEnviada AS DOUBLE))
                    ) AS LineTgt,
                    SUM(CASE WHEN UPPER(LTRIM(RTRIM(COALESCE(LD.EstadoLinea, '')))) = 'ENTREGADO'
                        THEN CAST(LD.CantidadEnviada AS DOUBLE) ELSE 0 END) AS QtyRec
                FROM DespachosTrackingDetalle LD
                INNER JOIN Cands C ON C.NumOc = LD.NumOc
                WHERE NOT EXISTS (SELECT 1 FROM DespachosEnvioDetalle D2 WHERE D2.NumOc = LD.NumOc)
                GROUP BY LD.NumOc, LD.NumLineaOc, LTRIM(RTRIM(COALESCE(LD.CodProd, '')))
            ),
            O AS (
                SELECT NumOc, SUM(LineTgt) AS NeedRec, SUM(QtyRec) AS GotRec FROM L GROUP BY NumOc
            ),
            Op AS (
                SELECT T.NumOc
                FROM (
                    SELECT
                        NumOc,
                        Estado,
                        ROW_NUMBER() OVER (PARTITION BY NumOc ORDER BY Id DESC) AS rn
                    FROM DespachosTracking
                ) T
                INNER JOIN Cands C ON C.NumOc = T.NumOc
                WHERE T.rn = 1
                  AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(T.Estado, ''), '_', ' ')))) = 'EN RUTA'
                  AND NOT EXISTS (SELECT 1 FROM DespachosEnvio E2 WHERE E2.NumOc = T.NumOc)
            ),
            V AS (
                SELECT O.NumOc, O.NeedRec, O.GotRec,
                    CASE WHEN Op.NumOc IS NULL THEN 0 ELSE 1 END AS HasOpen
                FROM O
                LEFT JOIN Op ON Op.NumOc = O.NumOc
            )
            SELECT V.NumOc
            FROM V
            WHERE V.GotRec > 0
              AND (
                V.HasOpen = 1
                OR V.GotRec + 0.000001 < V.NeedRec
                OR EXISTS (
                    SELECT 1 FROM DespachosEnvio E
                    WHERE E.NumOc = V.NumOc
                      AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' '))))
                          NOT IN ('ANULADO', 'CANCELADO')
                      AND E.EntregaParcialBodega = 1
                )
                OR EXISTS (
                    SELECT 1 FROM (
                        SELECT E2.NumOc AS N2
                        FROM DespachosEnvio E2
                        WHERE UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E2.Estado, ''), '_', ' '))))
                            NOT IN ('ANULADO', 'CANCELADO')
                        GROUP BY E2.NumOc
                        HAVING COUNT(1) > 1
                    ) M WHERE M.N2 = V.NumOc
                )
              )
            ORDER BY V.NumOc DESC
            LIMIT {fetch_cap}
            """
        )
        for row in cursor.fetchall():
            if row and row[0] is not None:
                try:
                    fo = int(row[0])
                    if fo not in seen:
                        seen.add(fo)
                        out.append(fo)
                except (TypeError, ValueError):
                    continue

    if not raw.isdigit():
        cursor.execute(
            f"""
            SELECT DISTINCT E.NumOc
            FROM DespachosEnvio E
            WHERE E.EntregaParcialBodega = 1
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' '))))
                  NOT IN ('ANULADO', 'CANCELADO')
              AND EXISTS (
                  SELECT 1
                  FROM DespachosEnvioDetalle D
                  INNER JOIN DespachosEnvio Ex ON Ex.Id = D.EnvioId
                  WHERE D.NumOc = E.NumOc
                    AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(Ex.Estado, ''), '_', ' '))))
                        NOT IN ('ANULADO', 'CANCELADO')
                    AND UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) = 'ENTREGADO'
                    AND COALESCE(CAST(D.CantidadEnviada AS DOUBLE), 0) > 0
              )
            ORDER BY E.NumOc DESC
            LIMIT {fetch_cap}
            """
        )
        for row in cursor.fetchall():
            if row and row[0] is not None:
                try:
                    fo = int(row[0])
                    if fo not in seen:
                        seen.add(fo)
                        out.append(fo)
                except (TypeError, ValueError):
                    continue

    if out:
        sm = _load_reception_summary_by_folio(cursor, out)
        out = [
            f for f in out
            if _resumen_indica_recepcion_parcial_faena(sm.get(f))
        ][:cap]
    return out


def _folios_local_recepcion_rechazada(cursor, num_oc_filtro_raw=None):
    """
    OCs con recepción rechazada en faena (líneas marcadas como RECHAZADO).
    """
    raw = (num_oc_filtro_raw or "").strip()

    if raw.isdigit():
        sql = """
            SELECT DISTINCT D.NumOc
            FROM DespachosEnvioDetalle D
            WHERE D.NumOc = ?
              AND UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) = 'RECHAZADO'
        """
        params = (int(raw),)
    else:
        sql = """
            SELECT DISTINCT D.NumOc
            FROM DespachosEnvioDetalle D
            INNER JOIN DespachosEnvio E ON E.Id = D.EnvioId
            WHERE UPPER(LTRIM(RTRIM(COALESCE(D.EstadoLinea, '')))) = 'RECHAZADO'
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
            ORDER BY D.NumOc DESC
        """
        params = ()

    cursor.execute(sql, params)
    out = []
    for row in cursor.fetchall():
        if row and row[0] is not None:
            try:
                out.append(int(row[0]))
            except (TypeError, ValueError):
                continue
    return out


def _faena_line_key(num_linea_oc, cod_prod):
    """Clave estable (línea OC + código) para cruzar detalle de envío con acumulados."""
    nl = int(num_linea_oc) if num_linea_oc is not None else -999999
    cp = (cod_prod or '').strip().upper()
    return (nl, cp)


def _map_cantidad_recibida_faena_por_linea_oc(cursor, num_oc):
    """
    Cantidad ya recepcionada en faena por línea de OC: suma CantidadEnviada donde
    EstadoLinea = ENTREGADO (todos los envíos de la misma OC). Incluye legacy
    DespachosTrackingDetalle solo si la OC no tiene filas en DespachosEnvioDetalle.
    """
    out = {}
    num_oc = int(num_oc)
    try:
        cursor.execute(
            """
            SELECT
                COALESCE(D.NumLineaOc, -999999) AS NL,
                COALESCE(UPPER(LTRIM(RTRIM(D.CodProd))), '') AS CP,
                SUM(COALESCE(CAST(D.CantidadRecibida AS DOUBLE),
                             CAST(D.CantidadEnviada AS DOUBLE), 0)) AS Q
            FROM DespachosEnvioDetalle D
            WHERE D.NumOc = ?
              AND UPPER(LTRIM(RTRIM(D.EstadoLinea))) IN ('ENTREGADO', 'PARCIAL')
            GROUP BY COALESCE(D.NumLineaOc, -999999), COALESCE(UPPER(LTRIM(RTRIM(D.CodProd))), '')
            """,
            (num_oc,),
        )
        for r in cursor.fetchall():
            nl = int(r[0]) if r[0] is not None else -999999
            cp = (r[1] or '').strip()
            out[(nl, cp)] = float(r[2] or 0)
    except Exception:
        pass
    try:
        cursor.execute(
            """
            SELECT
                COALESCE(LD.NumLineaOc, -999999) AS NL,
                COALESCE(UPPER(LTRIM(RTRIM(LD.CodProd))), '') AS CP,
                SUM(CAST(LD.CantidadEnviada AS DOUBLE)) AS Q
            FROM DespachosTrackingDetalle LD
            WHERE LD.NumOc = ?
              AND UPPER(LTRIM(RTRIM(LD.EstadoLinea))) = 'ENTREGADO'
              AND NOT EXISTS (SELECT 1 FROM DespachosEnvioDetalle D2 WHERE D2.NumOc = LD.NumOc)
            GROUP BY COALESCE(LD.NumLineaOc, -999999), COALESCE(UPPER(LTRIM(RTRIM(LD.CodProd))), '')
            """,
            (num_oc,),
        )
        for r in cursor.fetchall():
            nl = int(r[0]) if r[0] is not None else -999999
            cp = (r[1] or '').strip()
            k = (nl, cp)
            out[k] = out.get(k, 0.0) + float(r[2] or 0)
    except Exception:
        pass
    return out


def _derive_bodega_tracking_status(total_solicitada, total_ingresada, pending_dispatch_faena=False):
    """
    Estado operativo perfil bodega: recepción en bodega según OC (Softland) + despacho hacia faena (guías locales).
    No confundir «recepción OC completa» con «todo lo ingresado ya salió en camión».
    """
    try:
        qty_solicitada = float(total_solicitada or 0)
    except Exception:
        qty_solicitada = 0.0
    try:
        qty_ingresada = float(total_ingresada or 0)
    except Exception:
        qty_ingresada = 0.0

    if qty_ingresada <= 0:
        return 'No entregado'
    if qty_solicitada > 1e-9 and qty_ingresada + 1e-9 < qty_solicitada:
        return 'Recepción parcial'
    if pending_dispatch_faena:
        return 'Pendiente despacho a faena'
    return 'Despacho completo desde bodega'


def _bodega_dashboard_row_label(estado_cabecera, base_label, pend_bodega_faena):
    """
    Una sola lectura operativa: si ya hay envío En Ruta y aún queda por despachar en bodega,
    no mezclar «Pendiente despacho a faena» con un segundo badge «En ruta».
    """
    if pend_bodega_faena and _state_in(estado_cabecera, ('En Ruta',)):
        return 'En ruta — remanente en bodega'
    return base_label


def _bodega_dashboard_estado_passes_filter(
    qty_sol, qty_ing, bodega_label, tracking_filter, reception_summary=None
):
    """Filtro del listado bodega: «entrega_total» = recepción OC completa en ERP (igual que el WHERE Softland), no el texto del badge."""
    tf = (tracking_filter or '').strip().lower()
    if not tf or tf in ('en_ruta', 'entregado', 'entrega_parcial_faena', 'recepcion_rechazada'):
        return True
    try:
        qs = float(qty_sol or 0)
        qi = float(qty_ing or 0)
    except Exception:
        qs, qi = 0.0, 0.0
    recep_ok = qs <= 1e-9 or qi + 1e-9 >= qs
    label = (bodega_label or '').strip()
    rec = reception_summary if isinstance(reception_summary, dict) else {}
    rs = (rec.get('status_label') or '').strip()
    need_rq = float(rec.get('need_qty') or 0)
    got_rq = float(rec.get('got_qty') or 0)
    if tf == 'no_entregado':
        return label == 'No entregado'
    if tf == 'recepcion_parcial':
        return _resumen_indica_recepcion_parcial_faena(
            {
                'got_qty': got_rq,
                'need_qty': need_rq,
                'status_label': rs,
                'erp_need_qty': rec.get('erp_need_qty'),
                'trace_parcial_envio_bodega': rec.get('trace_parcial_envio_bodega'),
            }
        ) or label == 'Recepción parcial'
    if tf == 'entrega_total':
        return qi > 1e-9 and recep_ok
    return True


def _faena_matches_tracking_estado(orden, tracking_filter, recepcion_rechazada_folios=None):
    """Filtro de dashboard FAENA alineado con las mismas claves que bodega (vista operativa en faena)."""
    tf = (tracking_filter or '').strip().lower()
    if not tf:
        return True
    if len(orden) < 19:
        return True
    est = (orden[7] or '').strip()
    bodega_state = (orden[18] or '').strip()
    recep = (orden[15] or '').strip() if len(orden) > 15 else ''
    partial = bool(orden[14]) if len(orden) > 14 else False
    need_qty = float(orden[24] or 0) if len(orden) > 24 else 0.0
    got_qty = float(orden[25] or 0) if len(orden) > 25 else 0.0
    has_arrival = bool(orden[19]) if len(orden) > 19 else False
    if tf == 'en_ruta':
        return est == 'En Ruta'
    if tf == 'entregado':
        return est == 'Entregado'
    if tf == 'no_entregado':
        return recep != 'Recepcionado completo'
    if tf == 'recepcion_rechazada':
        if recepcion_rechazada_folios is not None:
            try:
                return int(orden[0]) in recepcion_rechazada_folios
            except (TypeError, ValueError):
                return False
        return False
    if tf == 'recepcion_parcial':
        erp_n = float(orden[26] or 0) if len(orden) > 26 else 0.0
        tr_pb = bool(orden[27]) if len(orden) > 27 else False
        if _resumen_indica_recepcion_parcial_faena(
            {
                'got_qty': got_qty,
                'need_qty': need_qty,
                'status_label': recep,
                'erp_need_qty': erp_n,
                'trace_parcial_envio_bodega': tr_pb,
            }
        ):
            return True
        if has_arrival and recep != 'Recepcionado completo':
            return True
        if partial and got_qty > 1e-6 and recep != 'Recepcionado completo':
            return True
        if partial and recep not in ('Recepcionado completo', 'No recepcionado'):
            return True
        return False
    if tf == 'recepcion_completa':
        return recep == 'Recepcionado completo' and est == 'Entregado'
    if tf == 'entrega_total':
        return bodega_state == 'Entrega total'
    if tf == 'entrega_parcial_faena':
        return partial
    if tf == 'envio_completo_en_ruta':
        pend_bodega = bool(orden[23]) if len(orden) > 23 else False
        return est == 'En Ruta' and not partial and not pend_bodega
    return True


def _faena_trk_row_passes_dashboard_sql_filters(
    trk_row,
    faena_sql_estado_filter,
    fecha_tipo_raw,
    filtro_desde_date,
    filtro_hasta_date,
    filtro_desde_raw,
    filtro_hasta_raw,
    folio_int=None,
    recepcion_parcial_folios=None,
    recepcion_rechazada_folios=None,
):
    """
    Equivalente operativo a los filtros SQL del listado FAENA (estado de cabecera + rango de fechas)
    para poder incluir OCs del ERP por CC aunque aún no exista fila en DespachosTracking.
    """
    if faena_sql_estado_filter == 'en_ruta':
        if not trk_row:
            return False
        est = _canonical_tracking_state((trk_row[1] if len(trk_row) > 1 else '') or '')
        return _state_in(est, ('En Ruta',))
    if faena_sql_estado_filter == 'entregado':
        if not trk_row:
            return False
        est = _canonical_tracking_state((trk_row[1] if len(trk_row) > 1 else '') or '')
        return _state_in(est, ('Entregado',))

    if fecha_tipo_raw == 'entrega_faena':
        if not (filtro_desde_date or filtro_hasta_date):
            return True
        if not trk_row or len(trk_row) < 4 or trk_row[3] is None:
            return False
        fh = trk_row[3]
        d = fh.date() if hasattr(fh, 'date') else _parse_iso_date(str(fh)[:10])
        if not d:
            return False
        if filtro_desde_date and d < filtro_desde_date:
            return False
        if filtro_hasta_date and d > filtro_hasta_date:
            return False
        return True

    if not (filtro_desde_date or filtro_hasta_date):
        return True
    if (
        recepcion_parcial_folios
        and folio_int is not None
        and int(folio_int) in recepcion_parcial_folios
    ):
        if not trk_row:
            return True
        fh_ent = trk_row[3] if len(trk_row) > 3 else None
        fh_sal = trk_row[2] if len(trk_row) > 2 else None
        ref = fh_ent or fh_sal
        if ref is None:
            return True
        d = ref.date() if hasattr(ref, 'date') else _parse_iso_date(str(ref)[:10])
        if not d:
            return True
        if filtro_desde_date and d < filtro_desde_date:
            return False
        if filtro_hasta_date and d > filtro_hasta_date:
            return False
        return True
    if (
        recepcion_rechazada_folios
        and folio_int is not None
        and int(folio_int) in recepcion_rechazada_folios
    ):
        if not trk_row:
            return True
        fh_ent = trk_row[3] if len(trk_row) > 3 else None
        fh_sal = trk_row[2] if len(trk_row) > 2 else None
        ref = fh_ent or fh_sal
        if ref is None:
            return True
        d = ref.date() if hasattr(ref, 'date') else _parse_iso_date(str(ref)[:10])
        if not d:
            return True
        if filtro_desde_date and d < filtro_desde_date:
            return False
        if filtro_hasta_date and d > filtro_hasta_date:
            return False
        return True
    if not trk_row:
        return False
    fh_ent = trk_row[3] if len(trk_row) > 3 else None
    fh_sal = trk_row[2] if len(trk_row) > 2 else None
    ref = fh_ent or fh_sal
    if ref is None:
        return False
    d = ref.date() if hasattr(ref, 'date') else _parse_iso_date(str(ref)[:10])
    if not d:
        return False
    if filtro_desde_date and d < filtro_desde_date:
        return False
    if filtro_hasta_date and d > filtro_hasta_date:
        return False
    return True


def _load_envios_agrupados_por_guia(cursor, num_oc):
    """Lista de envíos bodega→faena con líneas, para mostrar varias guías por OC."""
    out = []
    try:
        cursor.execute(
            """
            SELECT E.Id, E.GuiaDespacho, E.FechaHoraSalida, E.Estado, E.Transportista, E.PatenteVehiculo, E.UrlFotoEvidencia
            FROM DespachosEnvio E
            WHERE E.NumOc = ?
              AND UPPER(LTRIM(RTRIM(REPLACE(COALESCE(E.Estado, ''), '_', ' ')))) NOT IN ('ANULADO', 'CANCELADO')
            ORDER BY E.FechaHoraSalida DESC, E.Id DESC
            """,
            (num_oc,),
        )
        envios = cursor.fetchall()
        for ev in envios:
            eid = ev[0]
            url_ev = ev[6] if len(ev) > 6 else None
            cursor.execute(
                """
                SELECT
                    NumLineaOc,
                    CodProd,
                    DescripcionProd,
                    COALESCE(CAST(CantidadSolicitada AS DOUBLE), CAST(CantidadEnviada AS DOUBLE)) AS QtyProg,
                    CAST(CantidadEnviada AS DOUBLE) AS QtyEnv,
                    EstadoLinea,
                    MotivoRechazo
                FROM DespachosEnvioDetalle
                WHERE EnvioId = ?
                ORDER BY NumLineaOc, Id
                """,
                (eid,),
            )
            out.append(
                {
                    "envio": ev,
                    "lineas": cursor.fetchall(),
                    "fotos": _resolve_evidence_urls_all(cursor, num_oc, url_ev, envio_id=eid),
                }
            )
    except Exception as exc:
        logger.warning("Envíos por guía OC %s: %s", num_oc, exc)
    return out


