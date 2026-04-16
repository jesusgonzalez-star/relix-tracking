"""Rutas de administración – gestión de usuarios, tracking completo y reportes."""

import logging
from datetime import datetime

from flask import (
    render_template, request, redirect, url_for, flash,
    session, current_app,
)
import pyodbc

from utils.auth import (
    login_required, has_any_role, hash_password,
    sanitize_input, validate_password_strength,
)
from utils.permissions import roles_for, ALL_ROLES, ROLE_DESCRIPTIONS
from utils.db_legacy import DatabaseConnection
from config import SoftlandConfig
from routes.frontend import bp
from routes.frontend._helpers import (
    _ensure_business_roles,
    _ensure_faena_cc_column,
    _ensure_local_tracking_table,
    _normalize_cc_assignments,
    _form_cc_assignments_from_request,
    _fetch_softland_centros_costo_opciones,
    _resolve_softland_column,
    _state_in,
    _normalize_state_value,
    _sanitize_next_url,
    _erp_scopes_softland_by_aux,
    _canonical_tracking_state,
    _get_softland_fecha_column,
    logger,
)
from services.softland_service import SoftlandService


@bp.route('/superadmin/usuarios', methods=['GET', 'POST'])
@login_required(roles=roles_for('manage_users'))
def gestionar_usuarios():
    """Gestión de usuarios para superadmin."""
    conn = DatabaseConnection.get_connection()
    if not conn:
        flash('Error de conexión', 'danger')
        return redirect(url_for('frontend.index'))

    roles_creables = ALL_ROLES

    try:
        cursor = conn.cursor()
        _ensure_business_roles(cursor)
        _ensure_faena_cc_column(cursor)
        conn.commit()

        if request.method == 'POST':
            action = (request.form.get('action') or 'create').strip().lower()
            try:
                if action == 'delete':
                    # Eliminación exclusiva para SUPERADMIN.
                    if (session.get('rol') or '').upper() != 'SUPERADMIN':
                        flash('Solo SUPERADMIN puede eliminar usuarios.', 'danger')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    usuario_id = request.form.get('usuario_id', type=int)
                    if not usuario_id:
                        flash('Usuario inválido para eliminación.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    if usuario_id == session.get('user_id'):
                        flash('No puede eliminar su propio usuario en sesión.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    cursor.execute("""
                        SELECT U.Usuario, R.Nombre
                        FROM UsuariosSistema U
                        JOIN Roles R ON U.RolId = R.Id
                        WHERE U.Id = ?
                    """, (usuario_id,))
                    target = cursor.fetchone()
                    if not target:
                        flash('El usuario ya no existe.', 'info')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    if (target[0] or '').lower() == 'superadmin':
                        flash('No se puede eliminar la cuenta superadmin base.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    actor_id = session.get('user_id')

                    # Reasignar llaves foráneas de forma dinámica hacia el superadmin logueado.
                    cursor.execute("""
                        SELECT
                            OBJECT_NAME(fkc.parent_object_id) AS table_name,
                            c_parent.name AS column_name
                        FROM sys.foreign_key_columns fkc
                        JOIN sys.columns c_parent
                            ON c_parent.object_id = fkc.parent_object_id
                           AND c_parent.column_id = fkc.parent_column_id
                        JOIN sys.columns c_ref
                            ON c_ref.object_id = fkc.referenced_object_id
                           AND c_ref.column_id = fkc.referenced_column_id
                        WHERE OBJECT_NAME(fkc.referenced_object_id) = 'UsuariosSistema'
                          AND c_ref.name = 'Id'
                    """)
                    fk_columns = cursor.fetchall()
                    for table_name, column_name in fk_columns:
                        cursor.execute(
                            f"UPDATE [{table_name}] SET [{column_name}] = ? WHERE [{column_name}] = ?",
                            (actor_id, usuario_id),
                        )

                    cursor.execute("DELETE FROM UsuariosSistema WHERE Id = ?", (usuario_id,))
                    conn.commit()
                    flash(f'Usuario {target[0]} eliminado correctamente.', 'success')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                if action == 'change_password':
                    usuario_id = request.form.get('usuario_id', type=int)
                    new_password = request.form.get('new_password', '') or ''
                    confirm_password = request.form.get('confirm_password', '') or ''

                    if not usuario_id:
                        flash('Usuario inválido para cambio de contraseña.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    if new_password != confirm_password:
                        flash('Las contraseñas no coinciden.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    is_valid, pwd_error = validate_password_strength(new_password)
                    if not is_valid:
                        flash(pwd_error, 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    cursor.execute("""
                        SELECT Id, Usuario, Activo
                        FROM UsuariosSistema
                        WHERE Id = ?
                    """, (usuario_id,))
                    target = cursor.fetchone()
                    if not target:
                        flash('El usuario no existe o ya fue eliminado.', 'info')
                        return redirect(url_for('frontend.gestionar_usuarios'))
                    if not target[2]:
                        flash('No se puede cambiar la contraseña de un usuario inactivo.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))

                    cursor.execute("""
                        UPDATE UsuariosSistema
                        SET PasswordHash = ?
                        WHERE Id = ?
                    """, (hash_password(new_password), usuario_id))
                    conn.commit()
                    logger.info(f"Contraseña actualizada por SUPERADMIN para usuario {target[1]} (ID {usuario_id})")
                    flash(f'Contraseña actualizada correctamente para {target[1]}.', 'success')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                if action == 'update_cc':
                    usuario_id = request.form.get('usuario_id', type=int)
                    cc_asignados_raw = _form_cc_assignments_from_request()
                    cc_normalized = _normalize_cc_assignments(cc_asignados_raw)
                    cc_to_save = ", ".join(cc_normalized) if cc_normalized else None
                    if not usuario_id:
                        flash('Usuario inválido para actualizar centros de costo.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))
                    cursor.execute("""
                        SELECT R.Nombre
                        FROM UsuariosSistema U
                        JOIN Roles R ON U.RolId = R.Id
                        WHERE U.Id = ?
                    """, (usuario_id,))
                    rol_target = cursor.fetchone()
                    if not rol_target or (rol_target[0] or '').upper() != 'FAENA':
                        flash('Los centros de costo solo se asignan a usuarios con rol FAENA.', 'warning')
                        return redirect(url_for('frontend.gestionar_usuarios'))
                    cursor.execute("""
                        UPDATE UsuariosSistema
                        SET CentrosCostoAsignados = ?
                        WHERE Id = ?
                    """, (cc_to_save, usuario_id))
                    conn.commit()
                    flash('Centros de costo actualizados correctamente.', 'success')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                # Acción create (default)
                usuario = sanitize_input(request.form.get('usuario', ''), 'usuario')
                nombre = sanitize_input(request.form.get('nombre', ''), 'texto')
                email = sanitize_input(request.form.get('email', ''), 'email')
                password = request.form.get('password', '')
                rol_nombre = sanitize_input(request.form.get('rol', ''), 'texto')
                cc_asignados_raw = _form_cc_assignments_from_request()

                if not all([usuario, nombre, email, password, rol_nombre]):
                    flash('Debe completar todos los campos del usuario.', 'warning')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                if rol_nombre not in roles_creables:
                    flash('Rol inválido para creación.', 'danger')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                is_valid, pwd_error = validate_password_strength(password)
                if not is_valid:
                    flash(pwd_error, 'warning')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                cursor.execute("SELECT 1 FROM UsuariosSistema WHERE Usuario = ? OR Email = ?", (usuario, email))
                if cursor.fetchone():
                    flash('Usuario o email ya existen.', 'warning')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                cursor.execute("SELECT Id FROM Roles WHERE Nombre = ?", (rol_nombre,))
                rol_row = cursor.fetchone()
                if not rol_row:
                    flash('Rol no existe en la base.', 'danger')
                    return redirect(url_for('frontend.gestionar_usuarios'))

                cursor.execute("""
                    INSERT INTO UsuariosSistema (Usuario, NombreCompleto, RolId, Email, PasswordHash, Activo, CentrosCostoAsignados)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                """, (
                    usuario,
                    nombre,
                    rol_row[0],
                    email,
                    hash_password(password),
                    ", ".join(_normalize_cc_assignments(cc_asignados_raw)) or None,
                ))
                conn.commit()
                flash(f'Usuario {usuario} creado como {rol_nombre}.', 'success')
                return redirect(url_for('frontend.gestionar_usuarios'))

            except Exception as e:
                conn.rollback()
                logger.error(f"Error creando usuario: {e}", exc_info=True)
                flash('No se pudo crear el usuario.', 'danger')

        cursor.execute("""
            SELECT U.Id, U.Usuario, U.NombreCompleto, U.Email, R.Nombre AS Rol, U.Activo, U.CentrosCostoAsignados
            FROM UsuariosSistema U
            JOIN Roles R ON U.RolId = R.Id
            ORDER BY U.Id DESC
        """)
        usuarios = cursor.fetchall()

        faena_cc_por_usuario = {}
        for u in usuarios:
            if len(u) > 6 and (u[4] or '').upper() == 'FAENA':
                faena_cc_por_usuario[u[0]] = _normalize_cc_assignments(u[6] or '')

        centros_costo_opciones = _fetch_softland_centros_costo_opciones(usuarios)

        return render_template(
            'superadmin_usuarios.html',
            usuarios=usuarios,
            roles_creables=roles_creables,
            can_delete_users=((session.get('rol') or '').upper() == 'SUPERADMIN'),
            admin_nav_mode='usuarios',
            centros_costo_opciones=centros_costo_opciones,
            faena_cc_por_usuario=faena_cc_por_usuario,
        )

    finally:
        conn.close()


@bp.route('/admin/tracking_completo')
@login_required(roles=roles_for('view_tracking_full'))
def tracking_completo():
    """Vista completa de tracking (solo visualizador)."""
    try:
        conn = DatabaseConnection.get_connection()
        if not conn:
            flash('Error de conexión', 'danger')
            return redirect(url_for('frontend.index'))

        try:
            cursor = conn.cursor()

            user_role = session.get('rol')
            user_id = session.get('user_id')

            # Perfil extendido RBAC
            cursor.execute("SELECT aux_id_softland FROM UsuariosSistema WHERE Id = ?", user_id)
            user_data = cursor.fetchone()
            aux_id_softland = user_data[0] if user_data else None

            # Parámetros de paginación
            page = request.args.get('page', 1, type=int)
            per_page = 20

            # 1. Fetch Master from ERP (solo órdenes del año en curso)
            conn_softland = pyodbc.connect(SoftlandConfig.get_connection_string(), timeout=SoftlandConfig.DB_TIMEOUT)
            cursor_s = conn_softland.cursor()

            where_softland = """
                WHERE COALESCE(
                    YEAR(TRY_CONVERT(date, FechaOC, 103)),
                    YEAR(TRY_CONVERT(date, FechaOC))
                ) = YEAR(GETDATE())
            """
            where_params = []
            if _erp_scopes_softland_by_aux(user_role) and aux_id_softland:
                where_softland += " AND NumOc IN (SELECT numoc FROM softland.NW_OW_VsnpSaldoDetalleOC WHERE Codaux = ?)"
                where_params.append(aux_id_softland)

            softland_query = f"""
                SELECT
                    TOP 500
                    NumOc AS FolioOC,
                    COALESCE(NomAux, 'Sin Proveedor') AS NomProv,
                    0 AS TieneGuia
                FROM softland.OW_vsnpTraeEncabezadoOCompra
                {where_softland}
                ORDER BY FolioOC DESC
            """
            cursor_s.execute(softland_query, tuple(where_params))
            master_data = cursor_s.fetchall()
            conn_softland.close()

            # 2. Fetch Tracking Local
            if has_any_role(user_role, ['FAENA']):
                cursor.execute("""
                    SELECT
                        D.NumOc, D.Estado, D.FechaHoraSalida, D.Transportista, D.GuiaDespacho,
                        D.UrlFotoEvidencia, NULL as Geolocalizacion, U.NombreCompleto as RecibidoPor
                    FROM DespachosTracking D
                    LEFT JOIN UsuariosSistema U ON D.RegistradoPor = U.Id
                    WHERE D.transportista_asignado_id = ?
                      AND UPPER(LTRIM(RTRIM(REPLACE(D.Estado, '_', ' ')))) = 'EN RUTA'
                    ORDER BY D.Id ASC
                """, (user_id,))
            else:
                cursor.execute("""
                    SELECT
                        D.NumOc, D.Estado, D.FechaHoraSalida, D.Transportista, D.GuiaDespacho,
                        D.UrlFotoEvidencia, NULL as Geolocalizacion, U.NombreCompleto as RecibidoPor
                    FROM DespachosTracking D
                    LEFT JOIN UsuariosSistema U ON D.RegistradoPor = U.Id
                    ORDER BY D.Id ASC
                """)
            tracking_local = {row[0]: row for row in cursor.fetchall()}

            # 3. Merging con Aislamiento Total
            all_tracking = []
            for row in master_data:
                folio = row[0]
                trk = tracking_local.get(folio)
                tiene_guia = row[2]

                estado_local = _canonical_tracking_state(trk[1]) if trk else None
                if estado_local:
                    estado_general = estado_local
                elif tiene_guia:
                    estado_general = 'EN_BODEGA'
                else:
                    estado_general = 'PENDIENTE_EN_SOFTLAND'

                # Aplicar Filtros RBAC Aislamiento Total
                if has_any_role(user_role, ['FAENA']) and not trk:
                    continue


                # Formato esperado: (FolioOC, EstadoGeneral, FechaRecepcionBodega, FechaDespacho, FechaEntregaCliente, RecibidoPor, Transportista, GuiaDespacho, FotoEvidencia, Geolocalizacion, Folio, NomProv)
                # indices: 0=FolioOC, 1=Estado, 2=Recepcion, 3=Despacho, 4=Entrega, 5=RecibidoPor, 6=Transportista, 7=Guia, 8=Foto, 9=Geo, 10=Folio, 11=NomProv
                fecha_despacho = trk[2] if trk else None
                fecha_entrega = fecha_despacho if _state_in(estado_general, ('Entregado',)) else None
                recibido_por = trk[7] if trk else None

                all_tracking.append((
                    folio,
                    estado_general,
                    None,
                    fecha_despacho,
                    fecha_entrega,
                    recibido_por,
                    trk[3] if trk and trk[3] else '',
                    trk[4] if trk and trk[4] else '',
                    trk[5] if trk and trk[5] else '',
                    trk[6] if trk and trk[6] else '',
                    folio,
                    row[1] or 'Sin Proveedor'
                ))

            # Paginación en Memoria
            total = len(all_tracking)
            total_pages = (total + per_page - 1) // per_page
            offset = (page - 1) * per_page

            tracking = all_tracking[offset : offset + per_page]

            logger.info(f"Tracking completo vista - Página {page}")

            return render_template(
                'admin_tracking.html',
                tracking=tracking,
                page=page,
                total_pages=total_pages,
                total=total,
                admin_nav_mode='viz',
            )

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error en tracking_completo: {str(e)}", exc_info=True)
        flash('Error al cargar tracking', 'danger')
        return redirect(url_for('frontend.index'))


@bp.route('/admin/reportes')
@login_required(roles=roles_for('view_reports'))
def reportes():
    """Genera reportes del sistema"""
    try:
        conn = DatabaseConnection.get_connection()
        if not conn:
            flash('Error de conexión', 'danger')
            return redirect(url_for('frontend.index'))

        try:
            cursor = conn.cursor()

            # Estadísticas generales
            fecha_col = _get_softland_fecha_column(cursor)
            cursor.execute(f"""
                WITH EstadoOC AS (
                    SELECT
                        OC.NumOc,
                        MAX(G.Orden) AS TieneGuia,
                        MAX(D.Estado) AS EstadoDespachoLocal
                    FROM softland.OW_vsnpTraeEncabezadoOCompra OC
                    LEFT JOIN softland.IW_vsnpGuiasEntradaxOC G ON OC.NumOc = G.Orden
                    LEFT JOIN DespachosTracking D ON OC.NumOc = D.NumOc
                    WHERE COALESCE(
                        TRY_CONVERT(date, OC.{fecha_col}, 103),
                        TRY_CONVERT(date, OC.{fecha_col})
                    ) >= DATEADD(month, -1, GETDATE())
                    GROUP BY OC.NumOc
                ),
                Tracking AS (
                    SELECT
                        CASE
                            WHEN EstadoDespachoLocal IS NOT NULL
                                 AND LTRIM(RTRIM(COALESCE(EstadoDespachoLocal, ''))) <> ''
                                THEN UPPER(LTRIM(RTRIM(REPLACE(EstadoDespachoLocal, '_', ' '))))
                            WHEN TieneGuia IS NOT NULL THEN 'EN BODEGA'
                            ELSE 'PENDIENTE_EN_SOFTLAND'
                        END AS EstNorm
                    FROM EstadoOC
                )
                SELECT
                    COUNT(*) as TotalOrdenes,
                    COUNT(CASE WHEN EstNorm IN ('EN BODEGA', 'INGRESADO', 'DISPONIBLE EN BODEGA') THEN 1 END) as EnBodega,
                    COUNT(CASE WHEN EstNorm = 'EN RUTA' THEN 1 END) as Despachados,
                    COUNT(CASE WHEN EstNorm = 'ENTREGADO' THEN 1 END) as Entregados,
                    COUNT(CASE WHEN EstNorm = 'PENDIENTE_EN_SOFTLAND' THEN 1 END) as Pendientes
                FROM Tracking
            """)

            stats = cursor.fetchone()

            # Rendimiento por usuario
            cursor.execute("""
                SELECT
                    U.NombreCompleto,
                    COUNT(D.NumOc) as OrdenesProcesadas,
                    COUNT(CASE
                        WHEN UPPER(LTRIM(RTRIM(REPLACE(COALESCE(D.Estado, ''), '_', ' ')))) = 'ENTREGADO'
                        THEN 1 END) as Entregadas
                FROM DespachosTracking D
                LEFT JOIN UsuariosSistema U ON D.RegistradoPor = U.Id
                WHERE D.FechaHoraSalida >= DATEADD(month, -1, GETDATE())
                GROUP BY U.Id, U.NombreCompleto
                ORDER BY OrdenesProcesadas DESC
            """)

            rendimiento = cursor.fetchall()

            return render_template(
                'admin_reportes.html',
                stats=stats,
                rendimiento=rendimiento,
                admin_nav_mode='viz',
            )

        finally:
            conn.close()

    except Exception as e:
        logger.error(f"Error en reportes: {str(e)}", exc_info=True)
        flash('Error al generar reportes', 'danger')
        return redirect(url_for('frontend.index'))
