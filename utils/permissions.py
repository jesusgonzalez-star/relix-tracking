"""
Matriz centralizada de permisos y definición de roles.

Para agregar un nuevo perfil al sistema:
  1. Añadir el nombre del rol a ALL_ROLES y ROLE_DESCRIPTIONS.
  2. Incluirlo en las entradas de ROLE_PERMISSIONS que correspondan.
  3. (Opcional) Agregar un alias en ROLE_ALIASES de utils/auth.py si
     existe un nombre legacy que deba resolverse al nuevo rol.

No es necesario tocar rutas, decoradores ni templates: todo se resuelve
desde aquí mediante roles_for('nombre_permiso').
"""

# ── Roles canónicos del sistema ──────────────────────────────────────
ALL_ROLES = ['SUPERADMIN', 'BODEGA', 'VISUALIZADOR', 'FAENA', 'SUPERVISOR_CONTRATO']

ROLE_DESCRIPTIONS = {
    'SUPERADMIN':              'Control total del sistema y gestión de usuarios',
    'BODEGA':                  'Realiza el primer paso: importar y despachar a faena',
    'VISUALIZADOR':            'Solo consulta de información global',
    'FAENA':                   'Recibe envíos asignados y sube evidencia fotográfica',
    'SUPERVISOR_CONTRATO':     'Consulta de requisiciones, órdenes de compra y estado de bodega',
}

# ── Matriz de permisos ───────────────────────────────────────────────
# Cada clave es un nombre de permiso; el valor es el set de roles que
# lo poseen.  SUPERADMIN siempre tiene acceso implícito (ver has_any_role),
# pero se lista explícitamente para claridad.

ROLE_PERMISSIONS = {
    # --- Administración del sistema ---
    'manage_users':           {'SUPERADMIN'},
    'reset_tracking':         {'SUPERADMIN'},

    # --- Operaciones de Bodega ---
    'import_oc':              {'SUPERADMIN', 'BODEGA'},
    'dispatch_bodega':        {'SUPERADMIN', 'BODEGA'},

    # --- Operaciones de Faena ---
    'faena_operations':       {'SUPERADMIN', 'FAENA'},

    # --- Visualización / Reportes ---
    'view_reports':           {'VISUALIZADOR'},
    'view_tracking_full':     {'VISUALIZADOR'},

    # --- Accesos compartidos (multi-rol) ---
    'view_all':               {'SUPERADMIN', 'BODEGA', 'VISUALIZADOR', 'FAENA', 'SUPERVISOR_CONTRATO'},
    'view_recepcion':         {'SUPERADMIN', 'VISUALIZADOR', 'BODEGA', 'FAENA', 'SUPERVISOR_CONTRATO'},
    'view_requisiciones':     {'SUPERADMIN', 'BODEGA', 'VISUALIZADOR', 'FAENA', 'SUPERVISOR_CONTRATO'},
    'verify_qr':              {'SUPERADMIN', 'BODEGA', 'FAENA'},

    # --- Permisos granulares para templates (dashboard) ---
    'can_import':             {'SUPERADMIN', 'BODEGA'},
    'can_dispatch':           {'SUPERADMIN', 'BODEGA'},
    'can_view_global':        {'VISUALIZADOR'},
    'can_view_details':       {'SUPERADMIN', 'VISUALIZADOR', 'BODEGA', 'SUPERVISOR_CONTRATO'},
    'can_receive':            {'FAENA'},
    'can_search_requisicion': {'SUPERADMIN', 'BODEGA', 'VISUALIZADOR', 'FAENA', 'SUPERVISOR_CONTRATO'},
}


def roles_for(permission_name):
    """Retorna la lista de roles que tienen el permiso indicado.

    Uso típico:
        @login_required(roles=roles_for('import_oc'))
        def importar_oc(): ...

        can_import = has_any_role(user_role, roles_for('can_import'))
    """
    return list(ROLE_PERMISSIONS.get(permission_name, set()))
