"""
Authentication & session routes – login, registro, logout, before_request
and protected evidence file delivery.

Extracted from the monolithic ``frontend_routes.py`` so that each domain
lives in its own module while every route stays registered on the shared
``frontend`` Blueprint.
"""

import hmac
import io
import logging
import os
import secrets

from flask import (
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from PIL import Image, ImageDraw
from werkzeug.utils import secure_filename

from extensions import limiter
from routes.frontend import bp
from routes.frontend._helpers import (
    _ensure_business_roles,
    _canonical_session_role,
    _sanitize_next_url,
    _get_csrf_token,
    _get_evidence_upload_dir,
    _extract_folio_from_evidence_filename,
    _latest_evidence_filename_for_folio,
    allowed_file,
    _CSRF_PROTECTED_ENDPOINTS,
    _ensure_local_tracking_table,
)
from utils.auth import (
    hash_password,
    verify_password,
    sanitize_input,
    login_required,
    has_any_role,
    validate_password_strength,
)
from utils.db_legacy import DatabaseConnection
from utils.permissions import roles_for

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evidence file delivery
# ---------------------------------------------------------------------------

@bp.route('/evidencias/<path:filename>')
@login_required()
def get_evidencia(filename):
    """Entrega archivos de evidencia con validación de permisos por rol/fila."""
    filename = secure_filename(os.path.basename((filename or '').replace('\\', '/')))
    if not filename:
        abort(404)
    user_role = session.get('rol')
    user_id = session.get('user_id')
    conn = DatabaseConnection.get_connection()
    if not conn:
        abort(500)
    try:
        cursor = conn.cursor()
        row = None
        try:
            cursor.execute("""
                SELECT TOP 1 E.NumOc, E.transportista_asignado_id
                FROM DespachosEnvio E
                WHERE E.UrlFotoEvidencia LIKE ?
                   OR E.UrlFotoEvidencia LIKE ?
                   OR E.UrlFotoEvidencia LIKE ?
                ORDER BY E.Id DESC
            """, (f"%/evidencias/{filename}", f"%\\evidencias\\{filename}", f"%{filename}"))
            row = cursor.fetchone()
        except Exception:
            row = None
        if not row:
            cursor.execute("""
                SELECT TOP 1 NumOc, transportista_asignado_id
                FROM DespachosTracking
                WHERE UrlFotoEvidencia LIKE ?
                   OR UrlFotoEvidencia LIKE ?
                   OR UrlFotoEvidencia LIKE ?
                ORDER BY Id DESC
            """, (f"%/evidencias/{filename}", f"%\\evidencias\\{filename}", f"%{filename}"))
            row = cursor.fetchone()
        if not row:
            # Fallback robusto para evidencias guardadas en formato JSON/legacy
            # cuando el LIKE por UrlFotoEvidencia no encuentra coincidencia exacta.
            folio_guess = _extract_folio_from_evidence_filename(filename)
            if folio_guess is not None:
                cursor.execute(
                    """
                    SELECT TOP 1 E.NumOc, E.transportista_asignado_id
                    FROM DespachosEnvio E
                    WHERE E.NumOc = ?
                    ORDER BY E.Id DESC
                    """,
                    (folio_guess,),
                )
                row = cursor.fetchone()
                if not row:
                    cursor.execute(
                        """
                        SELECT TOP 1 NumOc, transportista_asignado_id
                        FROM DespachosTracking
                        WHERE NumOc = ?
                        ORDER BY Id DESC
                        """,
                        (folio_guess,),
                    )
                    row = cursor.fetchone()
        if not row:
            abort(404)

        if has_any_role(user_role, ['FAENA']) and not has_any_role(user_role, ['SUPERADMIN']):
            if row[1] != user_id:
                abort(403)

        upload_dir = _get_evidence_upload_dir()
        file_path = os.path.join(upload_dir, filename)
        if os.path.isfile(file_path):
            return send_from_directory(upload_dir, filename)

        fallback_name = _latest_evidence_filename_for_folio(row[0])
        if fallback_name:
            return send_from_directory(upload_dir, fallback_name)
        # Evita error duro en UI cuando la evidencia histórica no está en disco.
        placeholder = Image.new('RGB', (900, 520), color=(245, 247, 250))
        draw = ImageDraw.Draw(placeholder)
        msg1 = f"Evidencia no disponible para OC {row[0]}"
        msg2 = "El archivo ya no existe en storage/evidencias."
        draw.text((40, 220), msg1, fill=(40, 55, 75))
        draw.text((40, 255), msg2, fill=(110, 120, 135))
        buffer = io.BytesIO()
        placeholder.save(buffer, format='PNG')
        buffer.seek(0)
        return send_file(buffer, mimetype='image/png')
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(
    lambda: (current_app.config.get('RATELIMIT_LOGIN') or '10 per minute'),
    exempt_when=lambda: (
        (not current_app.config.get('RATELIMIT_ENABLED', True))
        or (not current_app.config.get('LOGIN_RATE_LIMIT_ENABLED', False))
    ),
)
def login():
    """Ruta de login con validación mejorada y protección contra ataques"""
    if request.method == 'POST':
        try:
            # Sanitizar entrada
            usuario = sanitize_input(request.form.get('usuario', ''), 'usuario')
            password = request.form.get('password', '')

            if not usuario or not password:
                flash('Usuario y contraseña son requeridos', 'danger')
                return render_template('login.html')

            # Conexión a BD
            conn = DatabaseConnection.get_connection()
            if not conn:
                flash('Error de conexión a la base de datos', 'danger')
                logger.error("Fallo de conexión en login")
                return render_template('login.html')

            try:
                cursor = conn.cursor()
                _ensure_business_roles(cursor)
                conn.commit()

                # Usar parámetros para prevenir SQL injection
                cursor.execute("""
                    SELECT u.Id, u.Usuario, u.NombreCompleto, r.Nombre as Rol,
                           u.Email, u.PasswordHash, u.Activo
                    FROM UsuariosSistema u
                    JOIN Roles r ON u.RolId = r.Id
                    WHERE u.Usuario = ? AND u.Activo = 1
                """, (usuario,))

                user = cursor.fetchone()

                if user and verify_password(user[5], password):
                    # Contraseña correcta
                    canonical_role = _canonical_session_role(user[3])
                    session.permanent = True
                    session['user_id'] = user[0]
                    session['username'] = user[1]
                    session['nombre'] = user[2]
                    session['rol'] = canonical_role
                    session['email'] = user[4]

                    # Cargar notificaciones de bodega si el usuario tiene rol BODEGA
                    if canonical_role == 'BODEGA':
                        conn_local = None
                        try:
                            conn_local = DatabaseConnection.get_connection()
                            if conn_local:
                                cursor_local = conn_local.cursor()
                                _ensure_local_tracking_table(cursor_local, conn_local)

                                # Consultar notificaciones sin leer
                                try:
                                    cursor_local.execute("""
                                        SELECT Id, GuiaDespacho, NumOc, CodProd, DescProd,
                                               CantEnviada, CantRecibida, MotivoRechazo,
                                               EstadoLinea, RecibidoPor, FechaRecepcion
                                        FROM NotificacionesBodega
                                        WHERE Leida = 0
                                        ORDER BY FechaCreacion DESC
                                    """)
                                    notif_rows = cursor_local.fetchall()

                                    if notif_rows:
                                        # Convertir a lista de dicts
                                        notifs = []
                                        for row in notif_rows:
                                            notifs.append({
                                                'Id': row[0],
                                                'GuiaDespacho': row[1],
                                                'NumOc': row[2],
                                                'CodProd': row[3],
                                                'DescProd': row[4],
                                                'CantEnviada': row[5],
                                                'CantRecibida': row[6],
                                                'MotivoRechazo': row[7],
                                                'EstadoLinea': row[8],
                                                'RecibidoPor': row[9],
                                                'FechaRecepcion': row[10]
                                            })
                                        session['notificaciones_bodega'] = notifs

                                        # Marcar todas como leídas
                                        ids = [r[0] for r in notif_rows]
                                        if ids:
                                            placeholders = ','.join(['?' for _ in ids])
                                            cursor_local.execute(
                                                f"UPDATE NotificacionesBodega SET Leida=1 WHERE Id IN ({placeholders})",
                                                tuple(ids)
                                            )
                                    conn_local.commit()
                                except Exception as e:
                                    logger.warning(f"Error al consultar/marcar notificaciones bodega: {str(e)}", exc_info=True)
                                    # Intentar rollback silenciosamente
                                    try:
                                        conn_local.rollback()
                                    except Exception:
                                        pass
                        except Exception as e:
                            logger.warning(f"Error general en notificaciones bodega: {str(e)}", exc_info=True)
                        finally:
                            if conn_local:
                                try:
                                    conn_local.close()
                                except Exception:
                                    pass

                    logger.info(f"Login exitoso: {user[1]} ({user[3]} -> {canonical_role})")
                    flash(f'¡Bienvenido {user[2]}!', 'success')
                    return redirect(url_for('frontend.index'))
                else:
                    # Log de intento fallido
                    logger.warning(f"Intento de login fallido para usuario: {usuario}")
                    flash('Usuario o contraseña incorrectos', 'danger')

            finally:
                conn.close()

        except ValueError as e:
            logger.warning(f"Error de validación en login: {str(e)}")
            flash(f'Error: {str(e)}', 'danger')
        except Exception as e:
            logger.error(f"Error en login: {str(e)}", exc_info=True)
            flash('Ocurrió un error inesperado', 'danger')

    return render_template(
        'login.html',
        show_demo_credentials=(not current_app.config.get('HIDE_DEMO_CREDENTIALS', True)),
    )


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------

@bp.route('/registro', methods=['GET', 'POST'])
def registro():
    """Ruta de registro para nuevos clientes"""
    if request.method == 'POST':
        try:
            # Sanitizar entrada
            usuario = sanitize_input(request.form.get('usuario', ''), 'usuario')
            password = request.form.get('password', '')
            nombre = sanitize_input(request.form.get('nombre', ''), 'texto')
            email = sanitize_input(request.form.get('email', ''), 'email')
            rut = sanitize_input(request.form.get('rut', ''), 'texto')
            telefono = sanitize_input(request.form.get('telefono', ''), 'texto')
            direccion = sanitize_input(request.form.get('direccion', ''), 'texto')

            if not usuario or not password or not nombre or not email:
                flash('Todos los campos obligatorios (*) deben ser completados', 'danger')
                return render_template('registro.html')

            # Conexión a BD
            conn = DatabaseConnection.get_connection()
            if not conn:
                flash('Error de conexión a la base de datos', 'danger')
                return render_template('registro.html')

            try:
                cursor = conn.cursor()
                _ensure_business_roles(cursor)
                conn.commit()

                # Verificar si el usuario o email ya existe
                cursor.execute("SELECT Id FROM UsuariosSistema WHERE Usuario = ? OR Email = ?", (usuario, email))
                if cursor.fetchone():
                    flash('El usuario o el email ya están registrados', 'warning')
                    return render_template('registro.html')

                # Crear hash
                pwd_hash = hash_password(password)

                # Insertar nuevo usuario con perfil VISUALIZADOR por defecto
                cursor.execute("SELECT Id FROM Roles WHERE Nombre = 'VISUALIZADOR'")
                rol_default = cursor.fetchone()
                if not rol_default:
                    flash('No existe el rol por defecto para registro.', 'danger')
                    return render_template('registro.html')

                cursor.execute("""
                    INSERT INTO UsuariosSistema (Usuario, NombreCompleto, RolId, Email, PasswordHash, Activo)
                    OUTPUT INSERTED.Id
                    VALUES (?, ?, ?, ?, ?, 1)
                """, (usuario, nombre, rol_default[0], email, pwd_hash))

                new_user_id = cursor.fetchone()[0]

                conn.commit()
                logger.info("Nuevo usuario registrado: %s (ID: %s)", usuario, new_user_id)
                flash('Registro exitoso. ¡Ahora puedes iniciar sesión!', 'success')
                return redirect(url_for('frontend.login'))

            except Exception as e:
                conn.rollback()
                logger.error("Error en registro BD: %s", e, exc_info=True)
                flash('Error al procesar el registro en la base de datos', 'danger')
            finally:
                conn.close()

        except ValueError as e:
            flash(str(e), 'danger')
        except Exception as e:
            logger.error(f"Error general en registro: {str(e)}", exc_info=True)
            flash('Ocurrió un error inesperado al registrar', 'danger')

    return render_template('registro.html')


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@bp.route('/logout')
@login_required()
def logout():
    """Cierra sesión de forma segura"""
    usuario = session.get('username', 'desconocido')
    session.clear()
    logger.info(f"Logout: {usuario}")
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('frontend.login'))


# ---------------------------------------------------------------------------
# Before-request middleware
# ---------------------------------------------------------------------------

@bp.before_request
def before_request():
    """Middleware para validaciones generales"""
    # Validar tamaño de request
    max_length = current_app.config.get('MAX_CONTENT_LENGTH') or (16 * 1024 * 1024)
    if request.content_length and request.content_length > max_length:
        logger.warning(f"Request demasiado grande desde {request.remote_addr}")
        return jsonify({'error': 'Archivo demasiado grande'}), 413
    if (
        request.method == 'POST'
        and current_app.config.get('CSRF_ENABLED', False)
        and request.endpoint in _CSRF_PROTECTED_ENDPOINTS
    ):
        expected_token = session.get('_csrf_token')
        submitted_token = (request.form.get('_csrf_token') or '').strip()
        if not expected_token or not submitted_token or not hmac.compare_digest(expected_token, submitted_token):
            logger.warning("CSRF token inválido en %s", request.endpoint)
            flash('Formulario inválido o sesión expirada. Intente nuevamente.', 'warning')
            return redirect(request.referrer or url_for('frontend.login'))
