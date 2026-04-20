# PLAN DE PRUEBAS MANUAL — Tracking Logístico v1.2.9

**Fecha:** 2026-04-20
**Objetivo:** Validar end-to-end toda la lógica de negocio (importación, envío, recepción, faltantes, reportes, RBAC) antes del despliegue definitivo.
**Duración estimada:** 3–4 horas (prueba full) / 1 hora (smoke test abreviado).

---

## 0. ANÁLISIS DE LA LÓGICA DE NEGOCIO (resumen ejecutivo)

La app cubre **cinco flujos de negocio** acoplados a Softland (ERP, solo-lectura) + BD local MariaDB (estado de tracking):

| # | Flujo | Actor | Estados de cabecera | Tabla principal |
|---|-------|-------|---------------------|-----------------|
| 1 | **Importar OC** | BODEGA | `INGRESADO` | `DespachosTracking` |
| 2 | **Despachar a faena** | BODEGA | `EN_BODEGA → En Ruta` | `DespachosEnvio` + `DespachosEnvioDetalle` |
| 3 | **Recibir en faena** | FAENA | `En Ruta → Entregado` | `DespachosEnvio` (update) |
| 4 | **Gestionar faltantes/rechazos** | FAENA → BODEGA | Líneas: `PARCIAL`/`RECHAZADO` | `DespachosEnvioDetalle` + `NotificacionesBodega` |
| 5 | **Reportes y tracking** | ADMIN / VISUALIZADOR / SUPERVISOR | N/A (read) | merge ERP + local |

**Estados de cabecera válidos** ([utils/states.py](utils/states.py)): `INGRESADO`, `EN_BODEGA`, `DISPONIBLE EN BODEGA`, `En Ruta`, `Entregado`, `CANCELADO`, `ANULADO`, `PENDIENTE_EN_SOFTLAND`.
**Estados de línea**: `EN_RUTA`, `PARCIAL`, `ENTREGADO`, `RECHAZADO`.
**Roles**: `SUPERADMIN`, `BODEGA`, `FAENA`, `VISUALIZADOR`, `SUPERVISOR_CONTRATO`.

Reglas críticas descubiertas (que serán probadas):
- **Idempotencia** de API vía `api_idempotency_key` ([tracking_local_service.py:31](services/tracking_local_service.py#L31)).
- **Transiciones duras** (no se puede retroceder de `Entregado` o `CANCELADO`) ([utils/states.py:76-101](utils/states.py#L76-L101)).
- **Tolerancia decimal** 0.0001 en cantidades.
- **Double-check** de race conditions en despacho (Fase 1 validación + Fase 2 revalidación con `FOR UPDATE`).
- **RBAC por CC** (FAENA/SUPERVISOR) y por `aux_id_softland` (VISUALIZADOR).
- **Guía de despacho** debe coincidir exactamente entre bodega y faena al recepcionar ([faena_routes.py:537](routes/frontend/faena_routes.py#L537)).
- **Si TODAS las líneas son rechazadas → no se permite cerrar recepción** ([faena_routes.py:640](routes/frontend/faena_routes.py#L640)).

---

## 1. PREPARACIÓN DEL ENTORNO

### 1.1 Datos mínimos requeridos

- [ ] **Backup de BD** antes de empezar (`mysqldump tracking_db > backup_pre_test_$(date +%F).sql`).
- [ ] Softland accesible (si no, anotar; parte de los tests probará degradación).
- [ ] **Al menos 5 OCs reales** en Softland con estas características:
  - **OC-A**: con guía de entrada y cantidades completas (happy path).
  - **OC-B**: con guía de entrada, varios productos (>3 líneas) para probar parciales.
  - **OC-C**: sin guía de entrada (debe bloquear despacho).
  - **OC-D**: con cantidades decimales (p.ej. 2.5 kg) para probar tolerancia.
  - **OC-E**: ya recibida parcialmente (si existe, para probar re-despacho).

### 1.2 Usuarios de prueba (crear si no existen)

El login es por **correo**. Todos los correos deben ser del dominio `@relixwater.cl`.

| Correo (login) | Usuario (interno) | Rol | Centros de Costo | `aux_id_softland` |
|----------------|-------------------|-----|------------------|-------------------|
| `test.super@relixwater.cl` | `test_super` | SUPERADMIN | — | — |
| `test.bodega@relixwater.cl` | `test_bodega` | BODEGA | — | — |
| `test.faena1@relixwater.cl` | `test_faena1` | FAENA | CC-001 | — |
| `test.faena2@relixwater.cl` | `test_faena2` | FAENA | CC-002 | — |
| `test.supervisor@relixwater.cl` | `test_supervisor` | SUPERVISOR_CONTRATO | CC-001 | — |
| `test.visual@relixwater.cl` | `test_visual` | VISUALIZADOR | — | (algún CodAux real) |

Contraseña común de pruebas (cumple política: ≥8, mayús., número, especial): `Test1234!`

### 1.3 Registro de evidencia

Abrir hoja de cálculo con columnas: `ID_Caso | Resultado (OK/FAIL) | Observación | Captura`.
Tomar captura de pantalla cada vez que un paso produzca un flash/error/cambio de estado.

---

## 2. MATRIZ DE COBERTURA

| Grupo | Casos | Prioridad |
|-------|-------|-----------|
| A. Autenticación y sesión | A1–A5 | ALTA |
| B. Importar OC | B1–B6 | ALTA |
| C. Despachar a faena | C1–C10 | **CRÍTICA** |
| D. Recepción en faena | D1–D10 | **CRÍTICA** |
| E. Productos faltantes / rechazo | E1–E5 | ALTA |
| F. Reportes y tracking global | F1–F5 | MEDIA |
| G. Gestión de usuarios | G1–G6 | MEDIA |
| H. RBAC cross-role | H1–H6 | ALTA |
| I. Edge cases / errores | I1–I8 | ALTA |
| J. API REST + idempotencia | J1–J5 | MEDIA |

---

## 3. CASOS DE PRUEBA

Formato: **ID | Precondición | Pasos | Resultado esperado | ✅/❌**

---

### A. AUTENTICACIÓN Y SESIÓN

> **📌 CÓMO SE INGRESA AL SISTEMA**
> El login se hace por **correo electrónico** (campo `Email` en tabla `UsuariosSistema`), **NO** por nombre de usuario ni por nombre completo.
> Ejemplo: correo = `test.bodega@relixwater.cl`, contraseña = `Test1234!`.
> La comparación es case-insensitive (el SQL hace `LOWER(u.Email) = ?`).
>
> **Dominio obligatorio** (`ALLOWED_EMAIL_DOMAIN=@relixwater.cl`, operación en Chile):
> Todos los correos deben terminar en `@relixwater.cl`. Si un usuario tiene otro dominio (p. ej. `.com`, gmail, etc.), el login será rechazado tras validar la contraseña con el mensaje *"Tu cuenta no está autorizada. Contacta al administrador."*.

**A1 — Login válido (por correo)**
- **Pre:** usuario con email `test.bodega@relixwater.cl` existe y está activo.
- **Pasos:** abrir `/login` → campo "Correo" = `test.bodega@relixwater.cl` → "Contraseña" = `Test1234!` → submit.
- **Esperado:** redirige a `/`, flash "¡Bienvenido ...!", nav superior muestra nombre y rol BODEGA.

**A1b — Login con correo en MAYÚSCULAS**
- **Pasos:** correo = `TEST.BODEGA@RELIXWATER.CL`, password correcta.
- **Esperado:** login exitoso (case-insensitive).

**A2 — Login con contraseña incorrecta**
- **Pasos:** correo = `test.bodega@relixwater.cl`, password = `Mala123!`.
- **Esperado:** flash `Correo o contraseña incorrectos`. No revela si el correo existe (mismo mensaje que correo inexistente).

**A2b — Intento de login con el nombre de usuario (no con el correo)**
- **Pasos:** correo = `test_bodega` (sin dominio), password correcta.
- **Esperado:** el campo es `type="email"` y exige formato válido — el navegador bloquea antes del submit, o el backend retorna "Correo y contraseña son requeridos" (porque `sanitize_input(..., 'email')` devuelve vacío). Confirma que el login es por correo, no por usuario corto.

**A2c — Login con nombre completo**
- **Pasos:** correo = `Juan Pérez`, password correcta.
- **Esperado:** falla igual que A2b (no es formato de email).

**A3 — Usuario desactivado**
- **Pre:** `UPDATE UsuariosSistema SET Activo=0 WHERE Email='test.visual@relixwater.cl';`
- **Pasos:** intentar login con ese correo.
- **Esperado:** bloqueado con mensaje genérico. Volver a `Activo=1` al finalizar.

**A3b — Usuario con email de dominio NO permitido**
- **Pre:** `UPDATE UsuariosSistema SET Email='foo@otro.com' WHERE Usuario='test_visual';`
- **Pasos:** login con el correo `foo@otro.com` y contraseña correcta.
- **Esperado:** flash "Tu cuenta no está autorizada. Contacta al administrador.". Restaurar email `@relixwater.cl` al finalizar.

**A4 — Logout invalida sesión**
- **Pasos:** login, luego `/logout`, luego navegar con back-button a una página privada (ej. `/admin/reportes`).
- **Esperado:** redirige a `/login`.

**A5 — Rate limit de login**
- **Pre:** `LOGIN_RATE_LIMIT_ENABLED=true` en `.env`.
- **Pasos:** 11 intentos fallidos en <1 min.
- **Esperado:** 429 "Demasiados intentos" después del décimo.

---

### B. IMPORTAR OC (rol BODEGA)

**B1 — Importar OC válida con guía de entrada**
- **Pre:** sesión `test_bodega`. OC-A en Softland, no importada.
- **Pasos:** en `/` → botón **Importar OC** → folio = OC-A → submit.
- **Esperado:** flash success, aparece en listado con estado `INGRESADO`. Verificar en BD: `SELECT Estado, Observaciones FROM DespachosTracking WHERE NumOc=OC-A ORDER BY Id DESC LIMIT 1;`

**B2 — Importar OC ya importada**
- **Pasos:** repetir B1 con el mismo folio OC-A.
- **Esperado:** flash warning "ya está importada", **NO** se crea fila nueva en BD.

**B3 — Importar OC inexistente en Softland**
- **Pasos:** folio = `9999999`.
- **Esperado:** flash error "OC no encontrada en Softland".

**B4 — Importar sin guía de entrada (OC-C)**
- **Pasos:** folio = OC-C.
- **Esperado:** debe permitir importar pero mostrar advertencia (`guia_entrada=False`). Verificar `Observaciones` contiene flag.

**B5 — Importar con Softland caído**
- **Pre:** bloquear acceso Softland (stop servicio / cambiar conn string temporalmente).
- **Pasos:** importar folio OC-A2.
- **Esperado:** inserta igual con observación de degradación. Restaurar Softland.

**B6 — Rate-limit importación**
- **Pasos:** 11 importaciones en <1 min.
- **Esperado:** 429 después de la 10ª.

---

### C. DESPACHAR A FAENA (rol BODEGA) — **CRÍTICO**

**C1 — Despacho simple, cantidad completa**
- **Pre:** OC-A importada, cantidades llegadas en Softland.
- **Pasos:** `/bodega/despacho/<OC-A>` → seleccionar todas las líneas → ingresar cantidades = pendiente → patente `ABCD-12` → transportista "Juan Pérez" → guía `G-0001` → seleccionar receptor `test_faena1` → subir 1 foto JPG → submit.
- **Esperado:** flash success, `DespachosEnvio.Estado = 'En Ruta'`, líneas en `EN_RUTA`, `EntregaParcialBodega=0`.
- **Verificar BD:**
  ```sql
  SELECT Id, NumOc, Estado, EntregaParcialBodega, transportista_asignado_id
  FROM DespachosEnvio WHERE NumOc=<OC-A> ORDER BY Id DESC LIMIT 1;
  ```

**C2 — Despacho parcial (envía < disponible)**
- **Pre:** OC-B importada con ≥3 líneas.
- **Pasos:** en despacho, seleccionar sólo 2 de 3 líneas, enviar mitad de cantidad en una.
- **Esperado:** `EntregaParcialBodega=1`, `DespachosEnvioDetalle.EstadoLinea='PARCIAL'` en la parcial, líneas no seleccionadas quedan pendientes para próximo despacho.

**C3 — Cantidad > solicitada (debe rechazar)**
- **Pasos:** intentar enviar cantidad mayor que la ingresada en bodega.
- **Esperado:** flash error "no puede superar...", **NO** se crea registro.

**C4 — Cantidad = 0 en todas las líneas**
- **Pasos:** todas las cantidades en 0, submit.
- **Esperado:** rechazo con mensaje "debe enviar al menos un ítem".

**C5 — Patente inválida**
- **Pasos:** usar `1234-AB` (formato incorrecto).
- **Esperado:** flash error formato ABCD-12.

**C6 — Sin foto**
- **Pasos:** no adjuntar foto → submit.
- **Esperado:** rechazo con mensaje "foto obligatoria".

**C7 — Foto de formato inválido (.pdf)**
- **Esperado:** rechazo con mensaje de formato.

**C8 — Cantidades decimales (OC-D, 2.5 kg)**
- **Pasos:** despachar 2.5 unidades.
- **Esperado:** acepta, BD guarda `DOUBLE` con precisión.

**C9 — Segundo despacho sobre OC-B (re-envío)**
- **Pre:** C2 ya ejecutado.
- **Pasos:** volver a `/bodega/despacho/<OC-B>` → debe mostrar las cantidades pendientes (total - enviadas) → enviar el resto.
- **Esperado:** segundo registro `DespachosEnvio` para misma OC. Ambos con `Estado='En Ruta'`.

**C10 — Race condition (opcional, 2 pestañas)**
- **Pre:** abrir despacho en 2 pestañas para misma OC.
- **Pasos:** enviar desde pestaña 1 completo, luego enviar desde pestaña 2.
- **Esperado:** pestaña 2 falla con mensaje "cantidad ya no disponible" (Fase 2 detecta cambio).

---

### D. RECEPCIÓN EN FAENA (rol FAENA) — **CRÍTICO**

Todos los casos requieren que haya al menos un envío `En Ruta` asignado al usuario o a su CC.

**D1 — Recepción completa correcta**
- **Pre:** envío de C1 existe, sesión `test_faena1`.
- **Pasos:** en `/` ver lista de entregas → click en envío → ingresar guía `G-0001` (**debe coincidir exactamente**) → cantidad recibida = enviada en cada línea → observaciones ≥8 chars → foto → submit.
- **Esperado:** flash "Producto recibido exitosamente", `DespachosEnvio.Estado='Entregado'`, `FechaHoraEntrega` con UTC_TIMESTAMP, `RecepcionParcialFaena=0`, todas las líneas `EstadoLinea='ENTREGADO'`.

**D2 — Guía de despacho incorrecta**
- **Pasos:** ingresar `G-9999` en vez de `G-0001`.
- **Esperado:** flash danger "la guía ingresada no coincide", **NO** actualiza.

**D3 — Guía vacía**
- **Esperado:** rechazo con mensaje "debe ingresar el número de guía".

**D4 — Observaciones muy cortas (<8 chars)**
- **Pasos:** escribir "OK".
- **Esperado:** rechazo "mínimo 8 caracteres".

**D5 — Recepción parcial por línea**
- **Pre:** C2 (despacho parcial) completado.
- **Pasos:** recepcionar envío, indicar cantidad recibida MENOR a la enviada en una línea, llenar `motivo_rechazo` = "producto dañado".
- **Esperado:** flash "recepción parcial registrada", línea queda en `PARCIAL`, cabecera `RecepcionParcialFaena=1`, se crea fila en `NotificacionesBodega`.

**D6 — Rechazo total de una línea (cantidad=0 con motivo)**
- **Pasos:** cantidad recibida=0 + motivo="no llegó".
- **Esperado:** `EstadoLinea='RECHAZADO'`, notificación creada.

**D7 — Todas las líneas rechazadas (bloqueo)**
- **Pasos:** poner 0 + motivo en TODAS las líneas.
- **Esperado:** flash warning "debe aceptar al menos un producto", **NO** se cierra recepción.

**D8 — Cantidad recibida > enviada**
- **Pasos:** enviadas 10, recibir 15.
- **Esperado:** flash "no puede superar la enviada ... si llegó material extra contacte a bodega".

**D9 — Recepción sin foto**
- **Esperado:** flash "debe adjuntar foto".

**D10 — Intento de recepcionar envío de otro usuario (aislamiento)**
- **Pre:** envío asignado a `test_faena1`, sesión `test_faena2` (CC distinto).
- **Pasos:** conocer el `envio_id` y navegar directamente a `/transportista/entregar/envio/<id>`.
- **Esperado:** flash "no autorizado", redirige a `/`.

---

### E. PRODUCTOS FALTANTES / RECHAZO (flujo de discrepancia)

**E1 — Ver notificación en bandeja de bodega**
- **Pre:** D5 o D6 ejecutado (generó `NotificacionesBodega`).
- **Pasos:** login `test_bodega` → revisar sección notificaciones / badge.
- **Esperado:** aparece notificación con OC, producto, cantidad enviada vs recibida, motivo.

**E2 — Visualizar histórico de discrepancias en recepción**
- **Pasos:** abrir `/bodega/recepcion/<OC-B>` → sección historial.
- **Esperado:** se muestra flag de líneas con rechazo + motivos.

**E3 — Re-despacho del faltante**
- **Pre:** OC-B tiene cantidad faltante tras D5.
- **Pasos:** `/bodega/despacho/<OC-B>` → debe permitir despachar la cantidad faltante.
- **Esperado:** nuevo envío en `En Ruta` cubriendo el delta.

**E4 — Consulta desde FAENA: ver histórico de recepciones**
- **Pasos:** `test_faena1` → `/faena/ordenes` → abrir OC-B.
- **Esperado:** ve cantidad total solicitada, total enviada acumulada, recibida acumulada.

**E5 — Tracking parcial reflejado en admin**
- **Pasos:** `test_super` → `/admin/tracking_completo` → filtrar OC-B.
- **Esperado:** estado muestra claramente "parcial" / indica líneas con problema.

---

### F. REPORTES Y TRACKING GLOBAL

**F1 — Admin tracking completo: paginación**
- **Pasos:** `/admin/tracking_completo` → cambiar página.
- **Esperado:** 20 por página, navegación OK.

**F2 — Admin reportes: estadísticas coherentes**
- **Pasos:** `/admin/reportes`.
- **Esperado:** suma de "en bodega + despachadas + entregadas + pendientes" = Total OCs (último mes).

**F3 — Rendimiento por usuario**
- **Esperado:** `test_bodega` figura con las OCs procesadas en C1-C9; `test_faena1` con las entregadas en D.

**F4 — Invalidar caché Softland**
- **Pasos:** POST `/superadmin/invalidar-cache` (vía UI o curl con cookie).
- **Esperado:** caché limpia; próximas consultas van al ERP directo.

**F5 — Tracking con filtro de fecha**
- **Pasos:** en `/faena/ordenes` → filtrar `desde=2026-04-01, hasta=2026-04-20`.
- **Esperado:** resultados dentro del rango. `desde > hasta` → error de validación.

---

### G. GESTIÓN DE USUARIOS (rol SUPERADMIN)

**G1 — Crear usuario**
- **Pasos:** `/superadmin/usuarios` → acción `create` → datos válidos.
- **Esperado:** usuario creado, aparece en lista, registro en `AuditLog`.

**G2 — Crear con usuario duplicado**
- **Esperado:** flash error "usuario ya existe".

**G3 — Contraseña débil**
- **Pasos:** password `abc`.
- **Esperado:** rechazo por política (≥8, mayús, núm, especial).

**G4 — Cambiar contraseña**
- **Pasos:** acción `change_password` a `test_faena2`.
- **Esperado:** ese usuario solo puede loguear con la nueva. Registro en AuditLog.

**G5 — Actualizar centros de costo de FAENA**
- **Pasos:** asignar `CC-001,CC-003` a `test_faena1`.
- **Esperado:** ahora ve OCs de ambos CC en `/faena/ordenes`.

**G6 — Eliminar usuario con registros**
- **Pre:** `test_faena2` tiene entregas.
- **Pasos:** delete.
- **Esperado:** FKs reasignadas al superadmin logueado, AuditLog completo.
  - **Verificar:** `SELECT COUNT(*) FROM DespachosEnvio WHERE transportista_asignado_id = <id_viejo>;` debe ser 0.

---

### H. RBAC CROSS-ROLE (accesos no autorizados)

**H1 — BODEGA intenta `/admin/reportes`**
- **Esperado:** 403 o redirect con flash "no autorizado".

**H2 — FAENA intenta importar OC**
- **Esperado:** 403.

**H3 — VISUALIZADOR intenta despachar**
- **Esperado:** 403.

**H4 — FAENA de CC-002 ve OC de CC-001**
- **Pasos:** `test_faena2` → `/faena/ordenes` → filtrar por folio de CC-001.
- **Esperado:** no aparece / flash "no autorizado".

**H5 — VISUALIZADOR con `aux_id_softland`: solo ve su auxiliar**
- **Pasos:** `test_visual` → `/admin/tracking_completo`.
- **Esperado:** solo OCs con CodAux = su `aux_id_softland`.

**H6 — URL directa a recurso sin permiso**
- **Pasos:** `test_faena1` → navegar manual a `/superadmin/usuarios`.
- **Esperado:** 403.

---

### I. EDGE CASES Y ERRORES

**I1 — BD caída durante operación**
- **Pasos:** en medio de un despacho, detener MariaDB (entorno dev).
- **Esperado:** flash "error de conexión", no se corrompe nada al reiniciar.

**I2 — Softland caído durante despacho**
- **Esperado:** degrada pero no bloquea bodega (datos locales).

**I3 — CSRF: submit sin token**
- **Pasos:** desde DevTools, borrar `recepcion_form_token` y submit.
- **Esperado:** flash "formulario expirado".

**I4 — Inyección SQL en folio**
- **Pasos:** navegar a `/bodega/recepcion/1 OR 1=1`.
- **Esperado:** 404 o error controlado (URL exige `<int>`).

**I5 — XSS en observaciones**
- **Pasos:** observación = `<script>alert(1)</script>`.
- **Esperado:** se guarda pero al renderizar queda escapado (no ejecuta).

**I6 — Foto con magic bytes falsificados (.jpg que es .exe)**
- **Esperado:** `validate_image_file` rechaza.

**I7 — URL de next con dominio externo (open redirect)**
- **Pasos:** `?next=https://evil.com`.
- **Esperado:** `_sanitize_next_url` lo descarta, redirige a `/`.

**I8 — Dos submits simultáneos del mismo formulario (token de un uso)**
- **Pasos:** botón back + resubmit.
- **Esperado:** segundo intento rechazado (token ya consumido).

---

### J. API REST + IDEMPOTENCIA

Usar `curl` con header `X-API-Secret: <valor de .env>`.

**J1 — POST /api/tracking/ válido**
```bash
curl -X POST http://localhost:5000/api/tracking/ \
  -H "X-API-Secret: $API_SECRET" -H "Content-Type: application/json" \
  -d '{"num_oc": 12345, "estado": "BODEGA", "idempotency_key": "test-001"}'
```
- **Esperado:** 201, fila creada.

**J2 — Reintento con misma `idempotency_key`**
- **Pasos:** repetir J1 idéntico.
- **Esperado:** 200 (no 201), devuelve misma fila. No duplica.

**J3 — Misma key con datos distintos**
- **Pasos:** mismo `idempotency_key=test-001` pero `estado=TRANSITO`.
- **Esperado:** **409 Conflict**.

**J4 — Sin API secret**
- **Esperado:** 401/403.

**J5 — GET /api/tracking/oc/<num_oc> paginado**
```bash
curl "http://localhost:5000/api/tracking/oc/12345?limit=10&offset=0" -H "X-API-Secret: $API_SECRET"
```
- **Esperado:** JSON con `{data, total, limit, offset}`.

**J6 — Transición inválida vía API**
- **Pasos:** OC en estado `Entregado`, POST con `estado=BODEGA`.
- **Esperado:** 400 "transición inválida".

---

## 4. CHECKLIST DE REGRESIÓN FINAL

Antes de dar por aprobada la versión, verifica:

- [ ] Todos los casos A–J ejecutados y marcados ✅.
- [ ] `SELECT COUNT(*) FROM DespachosTracking` coherente antes vs. después (+N filas esperadas).
- [ ] `AuditLog` tiene entradas para cada CRUD de usuario.
- [ ] Logs de Gunicorn/Apache sin tracebacks 500 inesperados.
- [ ] Nada de PII ni contraseñas en logs.
- [ ] Backup restaurado en entorno limpio y probado smoke test (A1+B1+C1+D1).

---

## 5. RECOMENDACIONES PARA EJECUCIÓN

1. **Ejecuta en orden**: A → B → C → D → E, porque los casos dependen de datos generados en anteriores.
2. **No uses producción** hasta aprobar en staging.
3. **Captura BD antes y después** de cada bloque: `mysqldump tracking_db > snap_<bloque>.sql`.
4. **Si un caso crítico falla** (C o D) detén el test y reporta; el resto de la suite depende de ellos.
5. Al terminar, limpia datos de prueba: `DELETE FROM DespachosEnvioDetalle WHERE EnvioId IN (SELECT Id FROM DespachosEnvio WHERE ... );` — cuidado con FKs.

---

## 6. SMOKE TEST (1 hora) — si no hay tiempo para todo

Ejecuta sólo: **A1, B1, C1, C2, C3, D1, D2, D5, D7, E1, E3, H1, H4, I3, J1, J2**.
Si esos 16 pasan, la app está funcionalmente sana para entrar en operación supervisada.

---

**Fin del plan. Suerte — y anota TODO lo que falle, por pequeño que parezca.**
