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
    Valida política de contraseña robusta:
    - Largo mínimo de 8 caracteres
    - Al menos una letra mayúscula
    - Al menos una letra minúscula
    - Al menos un número
    - Al menos un símbolo especial (!@#$%^&*)
    """
    pwd = (password or '').strip()
    if len(pwd) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres."
    if not re.search(r'[A-Z]', pwd):
        return False, "La contraseña debe incluir al menos una mayúscula."
    if not re.search(r'[a-z]', pwd):
        return False, "La contraseña debe incluir al menos una minúscula."
    if not re.search(r'\d', pwd):
        return False, "La contraseña debe incluir al menos un número."
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:\'",.<>?/\\|`~]', pwd):
        return False, "La contraseña debe incluir al menos un símbolo especial (!@#$%^&*)."
    return True, ""

def sanitize_input(text, input_type=None):
    """
    Limpia entradas de formulario.
    - 'usuario': solo permite letras, números, puntos, guiones y guiones bajos.
    - 'email': valida formato básico de email
    - 'html': escapa caracteres HTML peligrosos (< > " ')
    - Otros tipos: elimina únicamente caracteres peligrosos para SQL/HTML sin romper datos válidos
    """
    if not text:
        return text
    text = str(text)

    if input_type == 'usuario':
        # Usernames: solo alfanuméricos + . - _
        return re.sub(r'[^\w.\-]', '', text)

    if input_type == 'email':
        # Email: validación básica RFC 5322-ish
        email = text.lower().strip()
        # Parte local acepta letras, dígitos, . _ % + -
        if not re.match(r'^[A-Za-z0-9._%+\-_]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$', email, re.ASCII):
            return ''  # Retornar vacío si no es válido
        return email

    if input_type == 'html' or input_type == 'observaciones':
        from markupsafe import escape
        # Usa markupsafe para escapado robusto
        text = escape(text)
        # Elimina caracteres de control
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        return text

    # Para texto libre estándar: elimina ; y caracteres de control
    text = re.sub(r'[;]', '', text)
    text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
    return text

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
