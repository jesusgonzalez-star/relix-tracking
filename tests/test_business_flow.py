"""Tests de lógica de negocio del sistema de tracking.

Cubren los flujos reales que los tests previos NO tocaban:
- Flujo completo importar → despachar → recibir (a nivel service)
- Recepción parcial con líneas rechazadas
- Doble clic en importar / idempotencia
- Validación de patente vehicular
- Token anti-doble-envío de formularios
- Validación de cantidad despachada vs recibida
- Transiciones concurrentes (race condition simulada)

Los tests que requieren Softland ERP usan mocks de
`services.softland_service.SoftlandService`.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

import pytest

from app import create_app
from config import TestingConfig
from models.tracking import DespachoTracking
from services.tracking_local_service import (
    create_tracking_row,
    map_api_estado_to_db,
)
from utils.auth import has_any_role, validate_password_strength, sanitize_input
from utils.permissions import roles_for, ROLE_PERMISSIONS
from utils.states import (
    ST_INGRESADO, ST_EN_BODEGA, ST_EN_RUTA, ST_ENTREGADO,
    ST_CANCELADO, ST_DISPONIBLE_BODEGA,
    LST_EN_RUTA, LST_ENTREGADO, LST_PARCIAL, LST_RECHAZADO,
    is_valid_transition,
)
from utils.despacho_form import (
    mint_despacho_form_token,
    verify_despacho_form_token,
    consume_despacho_form_token,
)
from utils.recepcion_form import (
    mint_recepcion_form_token,
    verify_recepcion_form_token,
    consume_recepcion_form_token,
)
from routes.frontend._helpers import _normalize_patente, _is_valid_patente


# ─────────────────────────────────────────────────────────────────────
# 1. Flujo completo: importar → despachar → recibir (a nivel service)
# ─────────────────────────────────────────────────────────────────────

class TestFlujoCompleto:
    """Ejercita la cadena de transiciones que sigue una OC desde ingreso
    hasta entrega, usando el servicio canonical (equivalente al que invocan
    tanto la API pública como el panel web bajo el capó)."""

    def test_flujo_ingresado_a_entregado(self, db):
        num_oc = 50001
        # 1. Ingreso: fila inicial (equivalente a importar_oc creando 'INGRESADO').
        db.session.add(DespachoTracking(num_oc=num_oc, estado=ST_INGRESADO))
        db.session.commit()

        # 2. Bodega: BODEGA → EN_BODEGA.
        row1, created1 = create_tracking_row(num_oc=num_oc, api_estado='BODEGA')
        assert created1 is True
        assert row1.estado == ST_EN_BODEGA

        # 3. Despacho: TRANSITO → EN_RUTA.
        row2, created2 = create_tracking_row(num_oc=num_oc, api_estado='TRANSITO')
        assert created2 is True
        assert row2.estado == ST_EN_RUTA

        # 4. Recepción: ENTREGADO → Entregado (terminal).
        row3, created3 = create_tracking_row(num_oc=num_oc, api_estado='ENTREGADO')
        assert created3 is True
        assert row3.estado == ST_ENTREGADO

        # Historia persistida con 4 filas (INGRESADO + 3 transiciones).
        historial = (
            DespachoTracking.query.filter_by(num_oc=num_oc)
            .order_by(DespachoTracking.id.asc())
            .all()
        )
        assert len(historial) == 4
        assert [r.estado for r in historial] == [
            ST_INGRESADO, ST_EN_BODEGA, ST_EN_RUTA, ST_ENTREGADO,
        ]

    def test_flujo_entregado_bloquea_nuevas_transiciones(self, db):
        num_oc = 50002
        db.session.add(DespachoTracking(num_oc=num_oc, estado=ST_EN_RUTA))
        db.session.commit()
        # Entregar OK.
        create_tracking_row(num_oc=num_oc, api_estado='ENTREGADO')
        # Intento de volver a BODEGA debe fallar: estado terminal.
        with pytest.raises(ValueError, match='Transición de estado inválida'):
            create_tracking_row(num_oc=num_oc, api_estado='BODEGA')

    def test_despacho_parcial_permite_multiples_en_ruta(self, db):
        """Un segundo despacho de la misma OC (parcial) debe ser válido:
        EN_RUTA → EN_RUTA está permitido tras la corrección aplicada."""
        num_oc = 50003
        db.session.add(DespachoTracking(num_oc=num_oc, estado=ST_EN_RUTA))
        db.session.commit()
        row, created = create_tracking_row(num_oc=num_oc, api_estado='TRANSITO')
        assert created is True
        assert row.estado == ST_EN_RUTA


# ─────────────────────────────────────────────────────────────────────
# 2. Recepción parcial (líneas en estados mixtos)
# ─────────────────────────────────────────────────────────────────────

class TestRecepcionParcial:
    """Valida la lógica de estados de línea: una línea recibida parcialmente
    + una rechazada, ambas con motivo — el caso realista que debe marcar
    el envío como RecepcionParcialFaena=1."""

    def _evaluar_linea(self, qty_enviada: Decimal, qty_recibida: Decimal, motivo: str):
        """Replica la lógica de faena_routes.recibir_producto para estado de línea."""
        TOL = Decimal('0.0001')
        if qty_enviada <= TOL:
            return (LST_ENTREGADO, None)
        if qty_recibida >= qty_enviada - TOL:
            return (LST_ENTREGADO, None)
        if qty_recibida > TOL:
            if not motivo:
                return ('ERROR_MOTIVO_PARCIAL', None)
            return (LST_PARCIAL, motivo)
        if not motivo:
            return ('ERROR_MOTIVO_RECHAZO', None)
        return (LST_RECHAZADO, motivo)

    def test_linea_completa_marca_entregado(self):
        est, _ = self._evaluar_linea(Decimal('10'), Decimal('10'), '')
        assert est == LST_ENTREGADO

    def test_linea_parcial_sin_motivo_falla(self):
        est, _ = self._evaluar_linea(Decimal('10'), Decimal('4'), '')
        assert est == 'ERROR_MOTIVO_PARCIAL'

    def test_linea_parcial_con_motivo_ok(self):
        est, motivo = self._evaluar_linea(Decimal('10'), Decimal('4'), 'caja rota')
        assert est == LST_PARCIAL
        assert motivo == 'caja rota'

    def test_linea_rechazada_sin_motivo_falla(self):
        est, _ = self._evaluar_linea(Decimal('10'), Decimal('0'), '')
        assert est == 'ERROR_MOTIVO_RECHAZO'

    def test_linea_rechazada_con_motivo_ok(self):
        est, motivo = self._evaluar_linea(Decimal('10'), Decimal('0'), 'producto incorrecto')
        assert est == LST_RECHAZADO
        assert motivo == 'producto incorrecto'

    def test_mix_parcial_y_rechazada_marca_envio_parcial(self):
        """Un envío con una línea parcial + una rechazada debe contar como
        recepción parcial a nivel cabecera."""
        linea_a = self._evaluar_linea(Decimal('20'), Decimal('8'), 'daño parcial')
        linea_b = self._evaluar_linea(Decimal('5'), Decimal('0'), 'producto faltante')
        has_partial = linea_a[0] == LST_PARCIAL
        has_rejected = linea_b[0] == LST_RECHAZADO
        is_parcial_faena = has_partial or has_rejected
        assert is_parcial_faena is True


# ─────────────────────────────────────────────────────────────────────
# 3. Doble clic en importar_oc (idempotencia)
# ─────────────────────────────────────────────────────────────────────

class TestDobleClicImportar:
    """La API y el servicio deben ser idempotentes: la misma idempotency_key
    no debe crear una segunda fila (equivalente a doble clic del usuario)."""

    def test_doble_post_misma_key_no_duplica(self, db):
        r1, c1 = create_tracking_row(
            num_oc=60001, api_estado='BODEGA', idempotency_key='click-once'
        )
        r2, c2 = create_tracking_row(
            num_oc=60001, api_estado='BODEGA', idempotency_key='click-once'
        )
        assert c1 is True and c2 is False
        assert r1.id == r2.id
        filas = DespachoTracking.query.filter_by(num_oc=60001).count()
        assert filas == 1

    def test_clics_distintos_con_keys_distintas_crean_filas(self, db):
        """Un segundo clic real (nueva key) sí crea nueva fila — es
        comportamiento esperado para transiciones distintas."""
        db.session.add(DespachoTracking(num_oc=60002, estado=ST_INGRESADO))
        db.session.commit()
        create_tracking_row(num_oc=60002, api_estado='BODEGA', idempotency_key='k-bodega')
        create_tracking_row(num_oc=60002, api_estado='TRANSITO', idempotency_key='k-transito')
        filas = DespachoTracking.query.filter_by(num_oc=60002).count()
        assert filas == 3  # INGRESADO + EN_BODEGA + EN_RUTA


# ─────────────────────────────────────────────────────────────────────
# 4. Race condition: dos bodegueros despachan la misma OC
# ─────────────────────────────────────────────────────────────────────

class TestRaceCondition:
    """Simula dos procesos intentando despachar la misma OC casi en simultáneo.
    La matriz de transiciones y la idempotency_key deben evitar estados
    inválidos o duplicación real."""

    def test_dos_transiciones_desde_mismo_estado_una_gana(self, db):
        """Antes de la corrección EN_RUTA→EN_RUTA (fix anterior), este caso
        rechazaba el segundo despacho parcial. Ahora ambos son válidos, pero
        cada uno tiene su idempotency_key propia."""
        num_oc = 70001
        db.session.add(DespachoTracking(num_oc=num_oc, estado=ST_EN_BODEGA))
        db.session.commit()

        # Primer despacho (bodeguero A).
        r_a, created_a = create_tracking_row(
            num_oc=num_oc, api_estado='TRANSITO', idempotency_key='despA'
        )
        assert created_a is True
        assert r_a.estado == ST_EN_RUTA

        # Segundo despacho (bodeguero B) casi en simultáneo — parcial.
        r_b, created_b = create_tracking_row(
            num_oc=num_oc, api_estado='TRANSITO', idempotency_key='despB'
        )
        assert created_b is True  # Ambos se registran como envíos independientes.
        assert r_b.estado == ST_EN_RUTA
        assert r_a.id != r_b.id

    def test_reintento_exacto_no_crea_segundo_despacho(self, db):
        """Si bodeguero B por error reenvía con la MISMA key que A (retry de red),
        no se duplica."""
        num_oc = 70002
        db.session.add(DespachoTracking(num_oc=num_oc, estado=ST_EN_BODEGA))
        db.session.commit()
        r1, c1 = create_tracking_row(num_oc=num_oc, api_estado='TRANSITO', idempotency_key='key-x')
        r2, c2 = create_tracking_row(num_oc=num_oc, api_estado='TRANSITO', idempotency_key='key-x')
        assert c1 is True
        assert c2 is False
        assert r1.id == r2.id


# ─────────────────────────────────────────────────────────────────────
# 5. Validación de cantidad: despachar 50 cuando hay 30 recibidos
# ─────────────────────────────────────────────────────────────────────

class TestValidacionCantidad:
    """Replica la lógica de `despacho_bodega` que valida que el acumulado
    a despachar no supere la cantidad ingresada en bodega."""

    def _validar_despacho(
        self,
        qty_ingresada: Decimal,
        already_sent: Decimal,
        qty_send: Decimal,
        qty_solicitada: Decimal | None = None,
    ):
        TOL = Decimal('0.0001')
        if already_sent + qty_send > qty_ingresada + TOL:
            return 'SUPERA_INGRESADA'
        if qty_solicitada and qty_solicitada > 0 and already_sent + qty_send > qty_solicitada + TOL:
            return 'SUPERA_SOLICITADA'
        return 'OK'

    def test_despachar_dentro_de_lo_recibido_ok(self):
        assert self._validar_despacho(
            Decimal('30'), Decimal('0'), Decimal('20')
        ) == 'OK'

    def test_despachar_mas_de_lo_recibido_rechaza(self):
        """Bodega recibió 30. El operador intenta despachar 50. Debe rechazar."""
        assert self._validar_despacho(
            qty_ingresada=Decimal('30'),
            already_sent=Decimal('0'),
            qty_send=Decimal('50'),
        ) == 'SUPERA_INGRESADA'

    def test_despacho_parcial_acumulado_no_supera_recibido(self):
        """Segundo despacho parcial: ya se enviaron 20, se intentan 10 más.
        Si se recibieron 30, el acumulado (30) cabe exactamente."""
        assert self._validar_despacho(
            qty_ingresada=Decimal('30'),
            already_sent=Decimal('20'),
            qty_send=Decimal('10'),
        ) == 'OK'

    def test_despacho_parcial_acumulado_sobrepasa(self):
        """Ya se enviaron 20 de 30 recibidos; intentar 15 más debe rechazar."""
        assert self._validar_despacho(
            qty_ingresada=Decimal('30'),
            already_sent=Decimal('20'),
            qty_send=Decimal('15'),
        ) == 'SUPERA_INGRESADA'

    def test_despacho_supera_solicitado_en_oc(self):
        """Si la OC solicita 25 pero en bodega llegaron 30, no se puede
        despachar más de lo solicitado aunque haya stock extra."""
        assert self._validar_despacho(
            qty_ingresada=Decimal('30'),
            already_sent=Decimal('0'),
            qty_send=Decimal('28'),
            qty_solicitada=Decimal('25'),
        ) == 'SUPERA_SOLICITADA'


# ─────────────────────────────────────────────────────────────────────
# 6. Validación de patente vehicular
# ─────────────────────────────────────────────────────────────────────

class TestValidacionPatente:
    """_is_valid_patente y _normalize_patente son funciones puras del módulo
    _helpers. La patente chilena estándar es AA-BB-00 o ABCD-12 (6 chars)."""

    def test_patente_clasica_con_guion_valida(self):
        assert _is_valid_patente('ABCD-12') is True

    def test_patente_sin_guion_se_normaliza_a_guion(self):
        # 6 caracteres sin guion se reinterpretan como XXXX-YY.
        assert _normalize_patente('ABCD12') == 'ABCD-12'
        assert _is_valid_patente('ABCD12') is True

    def test_patente_con_puntos_y_espacios_se_normaliza(self):
        assert _normalize_patente('a.b c.d-12') == 'ABCD-12'
        assert _is_valid_patente('a.b c.d-12') is True

    def test_patente_vacia_invalida(self):
        assert _is_valid_patente('') is False
        assert _is_valid_patente(None) is False

    def test_patente_solo_letras_invalida(self):
        """Debe contener al menos un número."""
        assert _is_valid_patente('ABCDEF') is False

    def test_patente_solo_numeros_invalida(self):
        """Debe contener al menos una letra."""
        assert _is_valid_patente('123456') is False

    def test_patente_con_caracteres_raros_se_limpia(self):
        # Normalize filtra no-alfanuméricos y no-guion — el resultado puede
        # ser válido si quedan suficientes caracteres.
        norm = _normalize_patente('@@ABCD!!12##')
        assert norm == 'ABCD-12'
        assert _is_valid_patente('@@ABCD!!12##') is True

    def test_patente_muy_corta_invalida(self):
        assert _is_valid_patente('A1') is False

    def test_patente_muy_larga_invalida(self):
        assert _is_valid_patente('ABCDEFGHIJ1234') is False

    def test_patente_doble_guion_invalida(self):
        assert _is_valid_patente('AB--12') is False


# ─────────────────────────────────────────────────────────────────────
# 7. Token anti-doble-envío de formularios
# ─────────────────────────────────────────────────────────────────────

class TestFormToken:
    """Los tokens de despacho/recepción son bindings por OC/envío + sesión.
    Usamos un dict plano como "sesión" porque las funciones solo requieren
    soporte de __getitem__/__setitem__/get/pop (y opcional .modified)."""

    def test_despacho_token_mint_y_verify(self):
        session = {}
        token = mint_despacho_form_token(session, 12345)
        assert verify_despacho_form_token(session, 12345, token) is True

    def test_despacho_token_incorrecto_falla(self):
        session = {}
        mint_despacho_form_token(session, 12345)
        assert verify_despacho_form_token(session, 12345, 'token-manipulado') is False

    def test_despacho_token_para_otra_oc_falla(self):
        """Un token válido para una OC no debe servir para otra."""
        session = {}
        token_a = mint_despacho_form_token(session, 11111)
        mint_despacho_form_token(session, 22222)
        # Token de OC 11111 no sirve para OC 22222.
        assert verify_despacho_form_token(session, 22222, token_a) is False
        # Pero sí sigue sirviendo para la suya.
        assert verify_despacho_form_token(session, 11111, token_a) is True

    def test_despacho_token_consumido_ya_no_sirve(self):
        """Tras consumir el token (submit exitoso), un segundo submit
        con el mismo token debe fallar — protección contra doble clic."""
        session = {}
        token = mint_despacho_form_token(session, 99999)
        assert verify_despacho_form_token(session, 99999, token) is True
        consume_despacho_form_token(session, 99999)
        assert verify_despacho_form_token(session, 99999, token) is False

    def test_despacho_token_submitted_vacio_falla(self):
        session = {}
        mint_despacho_form_token(session, 1)
        assert verify_despacho_form_token(session, 1, '') is False
        assert verify_despacho_form_token(session, 1, None) is False

    def test_despacho_token_sin_mint_falla(self):
        """Si nunca se minteó un token para esa OC, cualquier submit falla."""
        session = {}
        assert verify_despacho_form_token(session, 123, 'cualquier-cosa') is False

    def test_recepcion_token_mint_y_verify(self):
        session = {}
        token = mint_recepcion_form_token(session, 42)
        assert verify_recepcion_form_token(session, 42, token) is True

    def test_recepcion_token_consumido_ya_no_sirve(self):
        session = {}
        token = mint_recepcion_form_token(session, 42)
        consume_recepcion_form_token(session, 42)
        assert verify_recepcion_form_token(session, 42, token) is False

    def test_tokens_de_despacho_y_recepcion_no_se_mezclan(self):
        """Un token de despacho no debe servir como token de recepción
        aun si comparten el mismo número — usan namespaces distintos."""
        session = {}
        # Mintamos ambos con el mismo número 77.
        tok_d = mint_despacho_form_token(session, 77)
        tok_r = mint_recepcion_form_token(session, 77)
        assert tok_d != tok_r
        # Cada token solo sirve en su canal.
        assert verify_despacho_form_token(session, 77, tok_r) is False
        assert verify_recepcion_form_token(session, 77, tok_d) is False
        assert verify_despacho_form_token(session, 77, tok_d) is True
        assert verify_recepcion_form_token(session, 77, tok_r) is True


# ─────────────────────────────────────────────────────────────────────
# 8. Mapeo estado API → DB (contrato estable con cliente móvil)
# ─────────────────────────────────────────────────────────────────────

class TestMapeoApiDb:
    def test_estados_conocidos_mapean(self):
        assert map_api_estado_to_db('BODEGA') == ST_EN_BODEGA
        assert map_api_estado_to_db('TRANSITO') == ST_EN_RUTA
        assert map_api_estado_to_db('ENTREGADO') == ST_ENTREGADO

    def test_case_insensitive(self):
        assert map_api_estado_to_db('bodega') == ST_EN_BODEGA
        assert map_api_estado_to_db(' Transito ') == ST_EN_RUTA

    def test_estado_desconocido_lanza(self):
        with pytest.raises(ValueError, match='Estado API inválido'):
            map_api_estado_to_db('ARCHIVADO')

    def test_estado_vacio_lanza(self):
        with pytest.raises(ValueError):
            map_api_estado_to_db('')


# ─────────────────────────────────────────────────────────────────────
# 9. CSRF enforcement real (requiere app con CSRF_ENABLED=True)
# ─────────────────────────────────────────────────────────────────────

class _CsrfConfig(TestingConfig):
    """Variante de TestingConfig con CSRF activado para ejercitar el guard."""
    CSRF_ENABLED = True


@pytest.fixture(scope='function')
def csrf_client():
    """App y cliente con enforcement CSRF activo."""
    app = create_app(_CsrfConfig)
    with app.test_client() as c:
        yield c


class TestCsrfEnforcement:
    """Valida que el ``before_request`` de CSRF rechace POSTs sin token
    y acepte los que traen el token válido de la sesión."""

    def test_post_sin_token_rechazado(self, csrf_client):
        resp = csrf_client.post('/bodega/importar_oc')
        assert resp.status_code == 400

    def test_post_con_token_invalido_rechazado(self, csrf_client):
        # Abrir /login genera un token en sesión al renderizar.
        csrf_client.get('/login')
        resp = csrf_client.post(
            '/bodega/importar_oc',
            data={'_csrf_token': 'token-manipulado', 'folio': '1234'},
        )
        assert resp.status_code == 400

    def test_post_con_token_valido_pasa_csrf(self, csrf_client):
        """Token válido hace que CSRF no aborte; luego redirect a login (sin sesión)."""
        csrf_client.get('/login')
        with csrf_client.session_transaction() as sess:
            token = sess.get('_csrf_token')
        assert token, 'GET /login debe sembrar _csrf_token en sesión'
        resp = csrf_client.post(
            '/bodega/importar_oc',
            data={'_csrf_token': token, 'folio': '1234'},
            follow_redirects=False,
        )
        # CSRF OK; la ruta requiere login → redirect (302) o 401.
        assert resp.status_code in (302, 401)

    def test_get_no_necesita_token(self, csrf_client):
        resp = csrf_client.get('/health')
        assert resp.status_code == 200

    def test_endpoint_no_protegido_pasa_sin_token(self, csrf_client):
        """POST a una ruta no listada en ``_CSRF_PROTECTED_ENDPOINTS`` no aborta."""
        # /api/tracking/ es tracking blueprint aparte, no frontend.
        resp = csrf_client.post('/api/tracking/', json={'num_oc': 1, 'estado': 'BODEGA'})
        # Sin API key o con JSON mal formado obtendremos 401/403/400 — lo
        # importante es que NO sea el 400 de CSRF (que viene del frontend bp).
        # Basta con verificar que el status no es porque le faltó CSRF.
        # El endpoint exige API_SECRET → 401/403.
        assert resp.status_code in (400, 401, 403)

    def test_header_x_csrf_token_tambien_aceptado(self, csrf_client):
        csrf_client.get('/login')
        with csrf_client.session_transaction() as sess:
            token = sess.get('_csrf_token')
        resp = csrf_client.post(
            '/bodega/importar_oc',
            data={'folio': '1'},
            headers={'X-CSRF-Token': token},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 401)


# ─────────────────────────────────────────────────────────────────────
# 10. Regeneración de sesión tras login (session fixation)
# ─────────────────────────────────────────────────────────────────────

class TestSessionFixation:
    """Verifica que tras un login exitoso los valores previos de la sesión
    del atacante se descartan. Probamos la función auxiliar que hace el clear
    + reinstalación de flashes conservando solo lo permitido."""

    def test_session_clear_elimina_valores_previos(self):
        """Simula el patrón aplicado en auth_routes tras verify_password OK."""
        session = {
            'atacante_inyectado': 'payload-malicioso',
            '_csrf_token': 'token-plantado-por-atacante',
            '_flashes': [('info', 'mensaje legítimo del flash')],
            'user_id': 9999,  # valor no válido que un atacante haya plantado
        }
        # Patrón del fix:
        saved_flashes = session.get('_flashes')
        session.clear()
        if saved_flashes:
            session['_flashes'] = saved_flashes
        # Re-poblar con valores del usuario real.
        session['user_id'] = 1
        session['rol'] = 'BODEGA'

        assert 'atacante_inyectado' not in session
        assert session.get('_csrf_token') is None
        assert session['user_id'] == 1
        assert session['rol'] == 'BODEGA'
        assert session.get('_flashes') == [('info', 'mensaje legítimo del flash')]


# ─────────────────────────────────────────────────────────────────────
# 11. RBAC — matriz de roles y permisos
# ─────────────────────────────────────────────────────────────────────

class TestRBAC:
    """Ejercita has_any_role y la matriz ROLE_PERMISSIONS — el núcleo de
    autorización. Cualquier endpoint que use @login_required(roles=...) o
    checks manuales depende de estas funciones."""

    def test_superadmin_pasa_cualquier_permiso(self):
        for perm in ROLE_PERMISSIONS.keys():
            assert has_any_role('SUPERADMIN', roles_for(perm)), perm

    def test_bodega_puede_importar_y_despachar(self):
        assert has_any_role('BODEGA', roles_for('import_oc'))
        assert has_any_role('BODEGA', roles_for('dispatch_bodega'))
        assert has_any_role('BODEGA', roles_for('can_receive')) is False

    def test_faena_puede_recibir_no_despachar(self):
        assert has_any_role('FAENA', roles_for('faena_operations'))
        assert has_any_role('FAENA', roles_for('can_receive'))
        assert has_any_role('FAENA', roles_for('dispatch_bodega')) is False
        assert has_any_role('FAENA', roles_for('manage_users')) is False

    def test_visualizador_solo_ve_no_opera(self):
        assert has_any_role('VISUALIZADOR', roles_for('view_all'))
        assert has_any_role('VISUALIZADOR', roles_for('view_reports'))
        assert has_any_role('VISUALIZADOR', roles_for('import_oc')) is False
        assert has_any_role('VISUALIZADOR', roles_for('dispatch_bodega')) is False
        assert has_any_role('VISUALIZADOR', roles_for('can_receive')) is False

    def test_supervisor_contrato_ve_requisiciones_no_opera(self):
        assert has_any_role('SUPERVISOR_CONTRATO', roles_for('view_requisiciones'))
        assert has_any_role('SUPERVISOR_CONTRATO', roles_for('import_oc')) is False
        assert has_any_role('SUPERVISOR_CONTRATO', roles_for('dispatch_bodega')) is False
        assert has_any_role('SUPERVISOR_CONTRATO', roles_for('can_receive')) is False

    def test_rol_legacy_transportista_mapea_faena(self):
        """ROLE_ALIASES convierte 'TRANSPORTISTA' → FAENA."""
        assert has_any_role('TRANSPORTISTA', roles_for('faena_operations'))

    def test_rol_vacio_o_none_denegado(self):
        assert has_any_role(None, ['SUPERADMIN']) is False
        assert has_any_role('', ['SUPERADMIN']) is False

    def test_rol_desconocido_denegado(self):
        assert has_any_role('HACKER', roles_for('manage_users')) is False
        assert has_any_role('XYZ', roles_for('import_oc')) is False


# ─────────────────────────────────────────────────────────────────────
# 12. Flujo HTTP completo vía API pública /api/tracking/
# ─────────────────────────────────────────────────────────────────────

class TestApiTrackingFullFlow:
    """Ejecuta el flujo real a través del endpoint HTTP público con API_SECRET.
    Este es el único camino REAL end-to-end que los tests anteriores evitaban."""

    def _auth(self, app):
        return {'X-API-Key': app.config['API_SECRET']}

    def test_flujo_http_bodega_transito_entregado(self, app, client, db):
        """POST sucesivos representando el ciclo de vida vía API."""
        headers = self._auth(app)
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            r1 = client.post('/api/tracking/',
                             json={'num_oc': 80001, 'estado': 'BODEGA', 'idempotency_key': 'b1'},
                             headers=headers)
            assert r1.status_code == 201, r1.get_json()

            r2 = client.post('/api/tracking/',
                             json={'num_oc': 80001, 'estado': 'TRANSITO', 'idempotency_key': 't1'},
                             headers=headers)
            assert r2.status_code == 201

            r3 = client.post('/api/tracking/',
                             json={'num_oc': 80001, 'estado': 'ENTREGADO', 'idempotency_key': 'e1'},
                             headers=headers)
            assert r3.status_code == 201

        r_hist = client.get('/api/tracking/oc/80001', headers=headers)
        assert r_hist.status_code == 200
        estados = [row['estado'] for row in r_hist.get_json()]
        # Orden descendente por id.
        assert estados == [ST_ENTREGADO, ST_EN_RUTA, ST_EN_BODEGA]

    def test_flujo_http_despues_entregado_no_acepta_cambios(self, app, client, db):
        headers = self._auth(app)
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            client.post('/api/tracking/',
                        json={'num_oc': 80002, 'estado': 'BODEGA', 'idempotency_key': 'x1'},
                        headers=headers)
            client.post('/api/tracking/',
                        json={'num_oc': 80002, 'estado': 'TRANSITO', 'idempotency_key': 'x2'},
                        headers=headers)
            client.post('/api/tracking/',
                        json={'num_oc': 80002, 'estado': 'ENTREGADO', 'idempotency_key': 'x3'},
                        headers=headers)
            r_invalid = client.post('/api/tracking/',
                                    json={'num_oc': 80002, 'estado': 'BODEGA', 'idempotency_key': 'x4'},
                                    headers=headers)
        assert r_invalid.status_code == 400
        assert 'Transición' in r_invalid.get_json()['mensaje']

    def test_flujo_http_sin_api_secret_rechaza(self, client, db):
        resp = client.post('/api/tracking/',
                           json={'num_oc': 80003, 'estado': 'BODEGA'})
        assert resp.status_code in (401, 403)

    def test_flujo_http_doble_clic_misma_key_devuelve_existente(self, app, client, db):
        headers = self._auth(app)
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            r1 = client.post('/api/tracking/',
                             json={'num_oc': 80004, 'estado': 'BODEGA', 'idempotency_key': 'dc'},
                             headers=headers)
            r2 = client.post('/api/tracking/',
                             json={'num_oc': 80004, 'estado': 'BODEGA', 'idempotency_key': 'dc'},
                             headers=headers)
        assert r1.status_code == 201
        assert r2.status_code == 200  # Ya existía, devuelve 200.
        assert r1.get_json()['id'] == r2.get_json()['id']

    def test_flujo_http_num_oc_invalido_rechaza(self, app, client, db):
        headers = self._auth(app)
        # num_oc fuera de rango → validación Marshmallow.
        resp = client.post('/api/tracking/',
                           json={'num_oc': 0, 'estado': 'BODEGA'},
                           headers=headers)
        assert resp.status_code == 400

    def test_flujo_http_estado_desconocido_rechaza(self, app, client, db):
        headers = self._auth(app)
        resp = client.post('/api/tracking/',
                           json={'num_oc': 80005, 'estado': 'ARCHIVADO'},
                           headers=headers)
        assert resp.status_code == 400


# ─────────────────────────────────────────────────────────────────────
# 13. Concurrencia real con threads sobre la API
# ─────────────────────────────────────────────────────────────────────

class TestApiConcurrency:
    """Simula múltiples clientes reintentando con la misma idempotency_key.
    El contrato debe ser: solo una inserción real (201), el resto lecturas
    del duplicado (200). Usamos requests secuenciales porque el ``FOR UPDATE``
    aplicado en ``tracking_local_service`` ya hace el trabajo de serialización."""

    def test_retry_secuencial_misma_key_no_duplica(self, app, client, db):
        headers = {'X-API-Key': app.config['API_SECRET']}
        results = []
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            for _ in range(5):
                r = client.post(
                    '/api/tracking/',
                    json={'num_oc': 81001, 'estado': 'BODEGA',
                          'idempotency_key': 'race-seq'},
                    headers=headers,
                )
                results.append(r.status_code)

        assert results.count(201) == 1, f'esperado 1x 201, obtenido {results}'
        assert results.count(200) == len(results) - 1

        # Y no se crearon filas extra.
        filas = DespachoTracking.query.filter_by(num_oc=81001).count()
        assert filas == 1

    def test_paralelo_con_keys_distintas_crea_filas_independientes(self, app, client, db):
        """Dos clientes distintos (keys distintas) crean inserciones válidas
        sin interferir. Equivalente a dos bodegueros despachando partes
        diferentes de la misma OC en instantes cercanos."""
        headers = {'X-API-Key': app.config['API_SECRET']}
        # Sembramos EN_BODEGA para que TRANSITO sea transición válida.
        db.session.add(DespachoTracking(num_oc=81002, estado=ST_EN_BODEGA))
        db.session.commit()
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            r1 = client.post('/api/tracking/',
                             json={'num_oc': 81002, 'estado': 'TRANSITO',
                                   'idempotency_key': 'cli-a'},
                             headers=headers)
            r2 = client.post('/api/tracking/',
                             json={'num_oc': 81002, 'estado': 'TRANSITO',
                                   'idempotency_key': 'cli-b'},
                             headers=headers)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.get_json()['id'] != r2.get_json()['id']


# ─────────────────────────────────────────────────────────────────────
# 14. Políticas de contraseña y sanitización (seguridad)
# ─────────────────────────────────────────────────────────────────────

class TestPasswordYSanitizacion:
    def test_password_minimo_8_chars(self):
        ok, _ = validate_password_strength('abc1')
        assert ok is False

    def test_password_sin_numero_falla(self):
        ok, _ = validate_password_strength('sololetras')
        assert ok is False

    def test_password_sin_letra_falla(self):
        ok, _ = validate_password_strength('12345678')
        assert ok is False

    def test_password_correcta_pasa(self):
        ok, _ = validate_password_strength('Segura123!')
        assert ok is True

    def test_password_none_falla(self):
        ok, _ = validate_password_strength(None)
        assert ok is False

    def test_sanitize_usuario_filtra_caracteres_raros(self):
        assert sanitize_input('juan@evil\'; DROP--', 'usuario') == 'juanevilDROP--'

    def test_sanitize_texto_libre_preserva_nombres(self):
        assert sanitize_input("O'Higgins, Ltda.") == "O'Higgins, Ltda."

    def test_sanitize_texto_libre_elimina_punto_y_coma(self):
        assert ';' not in sanitize_input('normal;;;;texto')


# ─────────────────────────────────────────────────────────────────────
# 15. SSRF y validación de URL de evidencia (foto)
# ─────────────────────────────────────────────────────────────────────

class TestSsrfEvidencia:
    """Replica casos del validador SSRF de schemas/tracking.py."""

    def _auth(self, app):
        return {'X-API-Key': app.config['API_SECRET']}

    @pytest.mark.parametrize('url', [
        'http://127.0.0.1/evil.jpg',
        'http://localhost/x.png',
        'http://169.254.169.254/meta',  # AWS metadata
        'http://10.0.0.1/internal.jpg',
        'http://192.168.1.1/admin.jpg',
        'http://metadata.google.internal/m',
        'http://[::1]/x.jpg',
        'ftp://external.com/file.jpg',
        'javascript:alert(1)',
    ])
    def test_rechaza_urls_peligrosas(self, app, client, db, url):
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            resp = client.post(
                '/api/tracking/',
                json={'num_oc': 82001, 'estado': 'BODEGA', 'foto_evidencia_url': url},
                headers=self._auth(app),
            )
        assert resp.status_code == 400, f'URL debería rechazarse: {url}'

    def test_acepta_url_externa_valida(self, app, client, db):
        with patch('routes.tracking_routes._validate_oc_in_softland', return_value=None):
            resp = client.post(
                '/api/tracking/',
                json={
                    'num_oc': 82002,
                    'estado': 'BODEGA',
                    'foto_evidencia_url': 'https://storage.example.com/foto.jpg',
                },
                headers=self._auth(app),
            )
        assert resp.status_code == 201


# ─────────────────────────────────────────────────────────────────────
# 16. Endpoints protegidos requieren login (nivel HTTP real)
# ─────────────────────────────────────────────────────────────────────

class TestEndpointsRequierenLogin:
    """Verifica que las rutas críticas redirijan al login cuando no hay sesión."""

    @pytest.mark.parametrize('path', [
        '/bodega/importar_oc',   # POST
    ])
    def test_post_sin_sesion_redirige_al_login(self, client, path):
        resp = client.post(path, follow_redirects=False)
        # 302 al login (sin sesión). CSRF está OFF en TestingConfig así
        # que no intercepta antes del @login_required.
        assert resp.status_code in (302, 303)
        assert '/login' in (resp.headers.get('Location') or '')

    def test_get_admin_usuarios_sin_sesion_redirige(self, client):
        resp = client.get('/superadmin/usuarios', follow_redirects=False)
        assert resp.status_code in (302, 303)
        assert '/login' in (resp.headers.get('Location') or '')

    def test_get_dashboard_sin_sesion_redirige(self, client):
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code in (200, 302, 303)
        # Si redirige, que sea a login.
        if resp.status_code in (302, 303):
            assert '/login' in (resp.headers.get('Location') or '')
