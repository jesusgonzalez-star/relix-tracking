"""
Helpers de Centros de Costo (CC) para perfiles FAENA.
Extraído de frontend_routes.py para reducir el monolito.
"""
import re
import logging

from flask import request

from utils.db_legacy import DatabaseConnection
from utils.sql_helpers import softland_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------

def normalize_cc_assignments(raw_value):
    """Normaliza lista de CC (csv/;), sin duplicados, para FAENA."""
    parts = re.split(r"[;,]", (raw_value or ""))
    normalized = []
    seen = set()
    for part in parts:
        token = " ".join((part or "").strip().upper().split())
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def build_softland_cc_match_clause(alias, token_count):
    """
    Cláusula SQL para matchear CC contra DescCC y CodiCC.
    Retorna (clause_sql, [ph, ph]) — el caller debe pasar los tokens duplicados como params.
    """
    if token_count <= 0:
        return "1=0", []
    ph = ",".join(["?"] * token_count)
    clause = f"""(
        UPPER(LTRIM(RTRIM(COALESCE(NULLIF({alias}.DescCC, ''), 'SIN CC')))) IN ({ph})
        OR UPPER(LTRIM(RTRIM(COALESCE(NULLIF({alias}.CodiCC, ''), 'SIN CC')))) IN ({ph})
    )"""
    return clause, [ph, ph]


# ---------------------------------------------------------------------------
# Columna CC en BD local
# ---------------------------------------------------------------------------

def ensure_faena_cc_column(cursor):
    """Asegura columna de centros de costo asignados por usuario."""
    cursor.execute("""
        IF COL_LENGTH('UsuariosSistema', 'CentrosCostoAsignados') IS NULL
            ALTER TABLE UsuariosSistema ADD CentrosCostoAsignados NVARCHAR(500) NULL;
    """)


# ---------------------------------------------------------------------------
# Consultas CC
# ---------------------------------------------------------------------------

def get_faena_cc_assignments(cursor_local, user_id):
    ensure_faena_cc_column(cursor_local)
    cursor_local.execute("SELECT CentrosCostoAsignados FROM UsuariosSistema WHERE Id = ?", (user_id,))
    row = cursor_local.fetchone()
    return normalize_cc_assignments(row[0] if row else "")


def get_folios_by_centros_costo(cc_tokens):
    if not cc_tokens:
        return set()
    folios = set()
    try:
        with softland_cursor() as c:
            cc_match_sql, _ = build_softland_cc_match_clause('OC', len(cc_tokens))
            c.execute(
                f"""
                SELECT OC.NumOc
                FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                WHERE {cc_match_sql}
                """,
                tuple(list(cc_tokens) + list(cc_tokens)),
            )
            folios = {int(r[0]) for r in c.fetchall() if r and r[0] is not None}
    except Exception as exc:
        logger.warning("No fue posible cargar folios por CC FAENA: %s", exc)
    return folios


def folio_matches_centros_costo_tokens(folio, cc_tokens):
    """True si la OC pertenece a alguno de los centros de costo dados (vista Softland)."""
    if not cc_tokens:
        return False
    try:
        fo = int(folio)
    except (TypeError, ValueError):
        return False
    try:
        with softland_cursor() as cc_c:
            cc_match_sql, _ = build_softland_cc_match_clause('OC', len(cc_tokens))
            cc_c.execute(
                f"""
                SELECT 1 FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                WHERE OC.NumOc = ?
                  AND {cc_match_sql}
                """,
                tuple([fo] + list(cc_tokens) + list(cc_tokens)),
            )
            return cc_c.fetchone() is not None
    except Exception as exc:
        logger.warning("No fue posible validar folio %s vs CC: %s", folio, exc)
        return False


def faena_user_has_cc_access_to_folio(user_id, folio):
    conn_u = DatabaseConnection.get_connection()
    if not conn_u:
        return False
    try:
        cu = conn_u.cursor()
        cc_tokens = get_faena_cc_assignments(cu, user_id)
    finally:
        conn_u.close()
    if not cc_tokens:
        return False
    return folio_matches_centros_costo_tokens(folio, cc_tokens)


def form_cc_assignments_from_request():
    """Lee centros de costo desde <select multiple name='cc_asignados'> o texto."""
    vals = [x.strip() for x in request.form.getlist('cc_asignados') if x and str(x).strip()]
    if vals:
        return ', '.join(vals)
    return (request.form.get('cc_asignados') or '').strip()


# ---------------------------------------------------------------------------
# Opciones para dropdowns
# ---------------------------------------------------------------------------

def fetch_softland_centros_costo_opciones(usuarios_rows=None):
    """Lista ordenada de CC para desplegables (ERP + CC ya asignados a FAENA)."""
    opciones = []
    try:
        with softland_cursor() as c:
            c.execute(
                """
                SELECT DISTINCT
                    UPPER(LTRIM(RTRIM(COALESCE(NULLIF(OC.DescCC, ''), NULLIF(OC.CodiCC, ''), 'SIN CC')))) AS CC
                FROM softland.OW_vsnpTraeEncabezadoOCompra OC WITH (NOLOCK)
                WHERE COALESCE(NULLIF(LTRIM(RTRIM(OC.DescCC)), ''), NULLIF(LTRIM(RTRIM(OC.CodiCC)), ''), '') <> ''
                ORDER BY CC
                """
            )
            opciones = [
                r[0]
                for r in c.fetchall()
                if r and r[0] and str(r[0]).strip().upper() not in ('', 'SIN CC')
            ]
    except Exception as exc:
        logger.warning('No se pudieron cargar centros de costo desde Softland: %s', exc)

    seen = set(opciones)
    if usuarios_rows:
        for u in usuarios_rows:
            if len(u) > 6 and (u[4] or '').upper() == 'FAENA' and u[6]:
                for t in normalize_cc_assignments(u[6]):
                    if t not in seen:
                        seen.add(t)
                        opciones.append(t)
    opciones.sort()
    return opciones


def dashboard_centros_costo_opciones(ordenes):
    """CC para filtro bodega: ERP + CC presentes en la página."""
    base = fetch_softland_centros_costo_opciones(None)
    seen = set(base)
    for ord in ordenes or []:
        if len(ord) > 13 and ord[13]:
            for t in normalize_cc_assignments(str(ord[13])):
                if t not in seen:
                    seen.add(t)
                    base.append(t)
    base.sort()
    return base


def dashboard_centros_costo_opciones_faena(ordenes, cc_asignados):
    """Dropdown de CC para FAENA: solo CCs asignados (filtrables server-side)."""
    assigned = set(normalize_cc_assignments(", ".join(cc_asignados or [])))
    opciones = sorted([x for x in assigned if x and x not in ('SIN CC',)])
    return opciones
