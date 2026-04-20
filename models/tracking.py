"""
Modelos SQLAlchemy para la base local MariaDB.
Incluye DespachoTracking (estado de despachos) y User (autenticación Flask-Login).
"""
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


_VALID_ESTADOS_SQL = (
    "'INGRESADO','EN_BODEGA','En Ruta','Entregado','CANCELADO','ANULADO',"
    "'PENDIENTE_EN_SOFTLAND','DISPONIBLE EN BODEGA'"
)


class DespachoTracking(db.Model):
    __tablename__ = 'DespachosTracking'
    __table_args__ = (
        db.CheckConstraint(
            f"Estado IN ({_VALID_ESTADOS_SQL})",
            name='ck_despachos_tracking_estado',
        ),
        db.Index('ix_despachos_tracking_numoc_id', 'NumOc', 'Id'),
        db.Index('ix_despachos_tracking_created_at', 'CreatedAt'),  # Para queries de rango
        db.Index('ix_despachos_tracking_estado', 'Estado'),  # Para filtros de estado
        db.Index('ix_despachos_tracking_transportista_id', 'transportista_asignado_id'),  # Para dashboard
    )

    id = db.Column('Id', db.Integer, primary_key=True, autoincrement=True)
    num_oc = db.Column('NumOc', db.Integer, nullable=False, index=True)
    estado = db.Column('Estado', db.String(50), nullable=False, default='INGRESADO')
    fecha_hora_salida = db.Column('FechaHoraSalida', db.DateTime, nullable=True)
    fecha_hora_entrega = db.Column('FechaHoraEntrega', db.DateTime, nullable=True)
    foto_evidencia_url = db.Column('UrlFotoEvidencia', db.Text, nullable=True)
    codigo_qr_data = db.Column('CodigoQR', db.Text, nullable=True)
    registrado_por = db.Column('RegistradoPor', db.Integer, nullable=True)
    transportista = db.Column('Transportista', db.String(100), nullable=True)
    guia_despacho = db.Column('GuiaDespacho', db.String(50), nullable=True)
    observaciones = db.Column('Observaciones', db.Text, nullable=True)
    transportista_asignado_id = db.Column('transportista_asignado_id', db.Integer, nullable=True, index=True)
    api_idempotency_key = db.Column('ApiIdempotencyKey', db.String(64), nullable=True, unique=True, index=True)
    created_at = db.Column(
        'CreatedAt', db.DateTime, nullable=True,
        default=lambda: datetime.now(timezone.utc),
        index=True,  # Para queries de rango (dashboard)
    )
    updated_at = db.Column(
        'UpdatedAt', db.DateTime, nullable=True,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f'<DespachoTracking OC:{self.num_oc} Estado:{self.estado!r}>'


class Role(db.Model):
    """Roles del sistema (SUPERADMIN, BODEGA, FAENA, etc.)."""
    __tablename__ = 'Roles'

    id = db.Column('Id', db.Integer, primary_key=True, autoincrement=True)
    nombre = db.Column('Nombre', db.String(50), nullable=False, unique=True)
    descripcion = db.Column('Descripcion', db.String(200), nullable=True)

    usuarios = db.relationship('User', backref='role', lazy=True)

    def __repr__(self):
        return f'<Role {self.nombre}>'


class User(UserMixin, db.Model):
    """Usuarios del sistema con autenticación local (Flask-Login + hash bcrypt/scrypt)."""
    __tablename__ = 'UsuariosSistema'

    id = db.Column('Id', db.Integer, primary_key=True, autoincrement=True)
    usuario = db.Column('Usuario', db.String(80), nullable=False, unique=True, index=True)
    nombre_completo = db.Column('NombreCompleto', db.String(200), nullable=True)
    rol_id = db.Column('RolId', db.Integer, db.ForeignKey('Roles.Id'), nullable=False)
    email = db.Column('Email', db.String(200), nullable=True, unique=True)
    password_hash = db.Column('PasswordHash', db.String(256), nullable=False)
    activo = db.Column('Activo', db.Integer, nullable=False, default=1)
    aux_id_softland = db.Column('aux_id_softland', db.String(50), nullable=True)
    centros_costo_asignados = db.Column('CentrosCostoAsignados', db.String(500), nullable=True)

    @property
    def is_active(self):
        return self.activo == 1

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.usuario}>'


class AuditLog(db.Model):
    """Registro de auditoría de cambios críticos en el sistema."""
    __tablename__ = 'AuditLog'

    id = db.Column('Id', db.Integer, primary_key=True, autoincrement=True)
    usuario = db.Column('Usuario', db.String(80), nullable=True, index=True)
    tabla = db.Column('Tabla', db.String(50), nullable=False, index=True)
    accion = db.Column('Accion', db.String(20), nullable=False)
    registro_id = db.Column('RegistroId', db.Integer, nullable=True)
    valores_antes = db.Column('ValoresAntes', db.Text, nullable=True)
    valores_despues = db.Column('ValoresDespues', db.Text, nullable=True)
    detalles = db.Column('Detalles', db.Text, nullable=True)
    created_at = db.Column(
        'CreatedAt', db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )

    def __repr__(self):
        return f'<AuditLog {self.tabla}:{self.accion} by {self.usuario}>'


class IdempotentLog(db.Model):
    """Registro de operaciones idempotentes para evitar duplicación en transacciones distribuidas."""
    __tablename__ = 'IdempotentLog'

    id = db.Column('Id', db.Integer, primary_key=True, autoincrement=True)
    idempotency_key = db.Column('IdempotencyKey', db.String(128), nullable=False, unique=True, index=True)
    operacion = db.Column('Operacion', db.String(100), nullable=False)
    estado = db.Column('Estado', db.String(20), nullable=False, default='INICIADO')
    resultado = db.Column('Resultado', db.Text, nullable=True)
    error = db.Column('Error', db.Text, nullable=True)
    created_at = db.Column(
        'CreatedAt', db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True
    )
    updated_at = db.Column(
        'UpdatedAt', db.DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self):
        return f'<IdempotentLog {self.operacion}:{self.estado}>'
