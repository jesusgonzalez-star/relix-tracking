import re
from functools import wraps
from flask import session, redirect, url_for, flash, request
from werkzeug.security import generate_password_hash, check_password_hash

from utils.permissions import roles_for, ALL_ROLES, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS  # noqa: F401  – re-export

ROLE_ALIASES = {
    'SUPERADMIN': {'SUPERADMIN'},
    'BODEGA': {'BODEGA'},
    'VISUALIZADOR': {'VISUALIZADOR'},
    'FAENA': {'FAENA'},
    'SUPERVISOR_CONTRATO': {'SUPERVISOR_CONTRATO'},
    # Compatibilidad con perfiles legacy.
    'ADMIN': {'SUPERADMIN'},
    'ADMINISTRADOR': {'SUPERADMIN'},
    'USUARIO': {'VISUALIZADOR'},
    'CLIENTE': {'VISUALIZADOR'},
    'TRANSPORTISTA': {'FAENA'},
}

def hash_password(password):
    """Hashea una contraseña usando PBKDF2:SHA256 para mayor seguridad"""
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

def verify_password(stored_hash, provided_password):
    """Verifica si la contraseña provista coincide con el hash almacenado"""
    return check_password_hash(stored_hash, provided_password)

def validate_password_strength(password):
    """
    Valida una política mínima compatible con contraseñas actuales:
    - Largo mínimo de 8 caracteres
    - Al menos una letra
    - Al menos un número
    """
    pwd = (password or '').strip()
    if len(pwd) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres."
    if not re.search(r'[A-Za-z]', pwd):
        return False, "La contraseña debe incluir al menos una letra."
    if not re.search(r'\d', pwd):
        return False, "La contraseña debe incluir al menos un número."
    return True, ""

def sanitize_input(text, input_type=None):
    """
    Limpia entradas de formulario.
    - 'usuario': solo permite letras, números, puntos, guiones y guiones bajos.
    - Otros tipos: elimina únicamente caracteres que rompen SQL sin ser parte de
      queries parametrizadas (las queries siempre usan parámetros ?).
      Se preservan caracteres válidos en nombres, emails y textos libres.
    """
    if not text:
        return text
    text = str(text)
    if input_type == 'usuario':
        # Usernames: solo alfanuméricos + . - _
        return re.sub(r'[^\w.\-]', '', text)
    # Para texto libre y email: solo eliminamos ; que podría confundir parsers HTML;
    # las comillas y paréntesis son válidos en nombres y direcciones.
    return re.sub(r'[;]', '', text)

def has_any_role(current_role, allowed_roles):
    """Evalua roles con equivalencias y jerarquía de superadmin."""
    if not current_role:
        return False
    current_role = str(current_role).strip().upper()
    if 'SUPERADMIN' in ROLE_ALIASES.get(current_role, {current_role}):
        return True

    normalized_allowed = set()
    for role in allowed_roles or []:
        role_key = str(role).strip().upper()
        normalized_allowed.update(ROLE_ALIASES.get(role_key, {role_key}))

    current_candidates = ROLE_ALIASES.get(current_role, {current_role})
    return any(role in normalized_allowed for role in current_candidates)

def login_required(roles=None):
    """
    Decorador para proteger rutas.
    Verifica que la sesión exista y que el usuario tenga un rol permitido.
    """
    if roles is None:
        roles = []
        
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Por favor inicie sesión para acceder a esta página.', 'warning')
                return redirect(url_for('frontend.login', next=request.path))
                
            if roles and not has_any_role(session.get('rol'), roles):
                flash('No tiene permisos para acceder a esta sección.', 'danger')
                # En un blueprint unificado usaremos frontend.index
                return redirect(url_for('frontend.index'))
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator
