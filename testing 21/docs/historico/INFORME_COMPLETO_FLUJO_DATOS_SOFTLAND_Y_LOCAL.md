# Informe Completo de Flujo de Datos

## 1) Resumen Ejecutivo

Este software opera con **dos orígenes de datos**:

- **Softland (ERP, solo lectura)**: fuente maestra de órdenes de compra y datos ERP.
- **Base local (Tracking/Usuarios)**: fuente operativa del flujo interno de despacho/recepción.

La aplicación **lee** desde Softland para visualizar y validar información de negocio, y **escribe** en la base local para registrar el ciclo logístico:

`INGRESADO` -> `En Ruta` -> `Entregado`

---

## 2) Conexiones y Configuración

### 2.1 Softland (Read-Only)

- Archivo: `config.py`
- Clase: `SoftlandConfig`
- Cadena de conexión: `ApplicationIntent=ReadOnly`
- Uso principal:
  - `services/softland_service.py`
  - consultas ERP en `routes/frontend_routes.py`

### 2.2 Base Local (Tracking + Usuarios)

- Archivo: `config.py`
- Clase: `LocalDbConfig`
- Conexión legacy: `utils/db_legacy.py` (`DatabaseConnection.get_connection`)
- Tablas locales usadas:
  - `DespachosTracking`
  - `UsuariosSistema`
  - `Roles`
  - (opcional según esquema) `CodigosQR`

---

## 3) Qué Datos se Obtienen desde Softland

## 3.1 Detalle de OC (Encabezado + Productos)

- Archivo: `services/softland_service.py`
- Método: `SoftlandService.obtener_detalle_oc(num_oc)`

### Encabezado

Fuente:
- `softland.OW_vsnpTraeEncabezadoOCompra` (OC)
- `softland.NW_OW_VsnpSaldoDetalleOC` (S)
- `softland.EC_VsnpTraeAuxiliaresLogCwtauxi` (Aux)

Campos obtenidos:
- `Folio`: `OC.NumOc`
- `Proveedor`: `Aux.NomAux`
- `Fecha Emisión`: `OC.FechaOC`

### Productos

Fuente:
- `softland.ow_vsnpMovimIWDetalleOC` (D)
- `softland.IW_vsnpProductos` (P)
- `softland.NW_OW_VsnpSaldoDetalleOC` (S)
- `softland.owordendet` (OD)

Campos obtenidos:
- `codigo`: `P.CodProd`
- `descripcion` (estándar): `P.DesProd`
- `descripcion_editada`: `OD.DetProd` (fallback `P.Desprod2`)
- `cantidad`: `S.cantidadOC`
- `cantidad_recibida`: `S.ingresada`

---

## 3.2 Dashboard Principal (`/`)

- Archivo: `routes/frontend_routes.py`
- Ruta: `index()`

Fuente ERP:
- `softland.OW_vsnpTraeEncabezadoOCompra` (OC)
- `OUTER APPLY` hacia:
  - `softland.owreqoc`
  - `softland.owrequisicion`
  - `softland.owsolicitanterq`

Campos ERP que se muestran:
- `Folio`: `OC.NumOc`
- `Fecha Emisión`: `OC.FechaOC`
- `Llegada Estimada`: `OC.FecFinalOC`
- `Proveedor`: `OC.NomAux`
- `Requisición/Solicitante`: cadena de requisición
- `CentroCosto`: `OC.DescCC`/`OC.CodiCC`
- `MontoTotal`: `OC.ValorTotMB`

Filtro temporal:
- Solo año actual (`YEAR(GETDATE())`).

---

## 3.3 Detalle de Requisición (`/requisicion/<folio>`)

Fuente:
- `softland.owordencom`
- `softland.owreqoc`
- `softland.owrequisicion`
- `softland.owsolicitanterq`
- `softland.IW_vsnpProductos`

Entrega:
- Cabecera de requisición asociada a la OC.
- Detalle de líneas de requisición.

---

## 3.4 Tracking Completo y Reportes

- `tracking_completo()` y `reportes()` en `routes/frontend_routes.py`
- Combinan:
  - maestro ERP Softland
  - estados locales de `DespachosTracking`

---

## 4) Qué Datos se Guardan en la Base Local

## 4.1 Tabla Operativa Principal: `DespachosTracking`

Creación/compatibilidad automática:
- Función: `_ensure_local_tracking_table(cursor)` en `routes/frontend_routes.py`

Columnas operativas:
- `NumOc`
- `Estado`
- `FechaHoraSalida`
- `FechaHoraEntrega`
- `UrlFotoEvidencia`
- `RegistradoPor`
- `Transportista`
- `GuiaDespacho`
- `Observaciones`
- `transportista_asignado_id`

---

## 4.2 Flujo de Escritura Local por Ruta

### A) Importar OC (Bodega/Admin)

- Ruta: `/bodega/importar_oc`
- Acción:
  - Inserta OC en local como `INGRESADO`:
    - `NumOc`
    - `Estado='INGRESADO'`
    - `RegistradoPor`
  - Si Softland no está disponible, igual crea registro local (modo resiliente).

### B) Despachar OC (Bodega/Admin)

- Ruta: `/bodega/despacho/<folio>`
- Acción:
  - Actualiza local a `En Ruta`
  - Guarda:
    - `FechaHoraSalida`
    - `GuiaDespacho`
    - `Transportista`
    - `Observaciones`
    - `transportista_asignado_id` (usuario FAENA asignado)

### C) Recibir OC en Faena

- Ruta: `/transportista/entregar/<folio>`
- Acción:
  - Requiere foto de evidencia.
  - Guarda archivo en disco y URL en DB.
  - Actualiza local:
    - `Estado='Entregado'`
    - `FechaHoraEntrega`
    - `UrlFotoEvidencia`
    - `RegistradoPor`
    - geolocalización en `Observaciones` (si aplica)

Control de seguridad:
- Si rol `FAENA`, solo puede cerrar órdenes asignadas a su `transportista_asignado_id`.

---

## 5) Carpeta de Evidencias (Fotos)

Definición:
- `config.py` -> `EVIDENCE_UPLOAD_DIR`
- Default:
  - `storage/evidencias` dentro del proyecto

Servicio de archivos:
- Ruta: `/evidencias/<filename>`
- Función: `get_evidencia()`
- Acceso con sesión iniciada.

---

## 6) Mapeo de Campos (Softland -> App -> DB Local)

| Contexto | Campo en Softland | Campo en App | Persistencia Local |
|---|---|---|---|
| OC Encabezado | `OW_vsnpTraeEncabezadoOCompra.NumOc` | `folio` | `DespachosTracking.NumOc` |
| Proveedor | `Aux.NomAux` / `OC.NomAux` | `proveedor` | se refleja en UI; local usa `Transportista` para logística |
| Fecha Emisión | `OC.FechaOC` | `fecha_emision` | no se persiste en `DespachosTracking` |
| ETA | `OC.FecFinalOC` | `fecha_llegada_estimada` | no se persiste |
| Centro Costo | `OC.DescCC`/`OC.CodiCC` | `centro_costo` | no se persiste en tracking |
| Monto | `OC.ValorTotMB` | `monto_total` | no se persiste |
| Producto Código | `P.CodProd` | `codigo` | no se persiste (solo visual detalle ERP) |
| Descripción 1 | `P.DesProd` | `descripcion` | no se persiste |
| Descripción 2 | `OD.DetProd` / `P.Desprod2` | `descripcion_editada` | no se persiste |
| Cantidad OC | `S.cantidadOC` | `cantidad` | no se persiste |
| Cantidad Recibida ERP | `S.ingresada` | `cantidad_recibida` | no se persiste |
| Estado tracking | N/A (local) | `estado_tracking` | `DespachosTracking.Estado` |
| Fecha salida | N/A (local) | `fecha_salida` | `DespachosTracking.FechaHoraSalida` |
| Fecha entrega | N/A (local) | `fecha_entrega` | `DespachosTracking.FechaHoraEntrega` |
| Foto evidencia | N/A (local/disco) | `foto_url` | `DespachosTracking.UrlFotoEvidencia` + archivo en `storage/evidencias` |

---

## 7) Flujo End-to-End del Software

1. **Bodega/Admin** importa una OC (Softland validación + creación local en `INGRESADO`).
2. **Bodega/Admin** despacha:
   - cambia a `En Ruta`,
   - asigna usuario `FAENA`.
3. **FAENA** ve solo sus asignadas en recepciones.
4. **FAENA** acepta y marca recibido:
   - sube foto (obligatorio),
   - estado pasa a `Entregado`.
5. Todo el sistema refleja estado final en:
   - dashboard,
   - recepciones pendientes,
   - vistas de tracking/reportes.

---

## 8) APIs Actuales y Roles (Estado Implementado)

- `POST /api/verificar_qr`
  - Roles: `ADMINISTRADOR`, `BODEGA`, `FAENA`
- `GET /api/estado_orden/<folio>`
  - Roles: `ADMINISTRADOR`, `BODEGA`, `VISUALIZADOR`, `FAENA`
  - Restricción adicional: `FAENA` solo folios asignados a su usuario.
- `GET /api/test-db`
  - Solo `ADMINISTRADOR`

---

## 9) Observaciones Importantes de Operación

- Softland es fuente maestra de consulta, pero el tracking operativo vive en local.
- Si Softland cae temporalmente, el flujo local sigue funcionando para no detener operación.
- El estado de negocio para despacho/recepción depende de `DespachosTracking`.
- Las fotos no van a Softland; se almacenan en carpeta local y URL en DB local.

---

## 10) Conclusión

La arquitectura actual está diseñada para:

- **Consultar ERP en tiempo real** (Softland Read-Only).
- **Operar logística de última milla localmente** (tracking propio).
- **Trazabilidad completa** del ciclo de OC mediante estados, usuario responsable, fechas y evidencia fotográfica.

Este documento refleja el flujo efectivo implementado actualmente en el código del proyecto.

---

## 11) Lógica Funcional Completa del Código (Vista General)

Esta sección resume **cómo funciona cada módulo principal** y **cómo interactúan** entre sí.

### 11.1 Autenticación, Sesión y Roles

- Login (`/login`):
  - valida credenciales contra `UsuariosSistema` + `Roles`,
  - carga sesión con `user_id`, `username`, `nombre`, `rol`, `email`.
- Logout (`/logout`):
  - limpia sesión y vuelve a login.
- Registro (`/registro`):
  - crea usuario nuevo con rol por defecto `VISUALIZADOR`.
- Decorador de seguridad:
  - `login_required(roles=[...])` controla acceso por rol.
- Compatibilidad de roles:
  - `has_any_role()` aplica alias/jerarquía definidos en `utils/auth.py`.

### 11.2 Dashboard Principal (`/`)

- Combina:
  - maestro Softland (encabezado de OC),
  - estado local en `DespachosTracking`.
- Muestra KPIs:
  - Total OC, En Bodega, Despachados, Entregados.
- Reglas por perfil:
  - `BODEGA` y `ADMINISTRADOR`: importan/despachan.
  - `FAENA`: ve panel operativo de recepciones asignadas.
  - `VISUALIZADOR`: solo consulta.
- Filtros visuales:
  - buscador de tabla + filtro de centro de costo.

### 11.3 Importación de OC (`/bodega/importar_oc`)

- Verifica si OC ya existe localmente.
- Si no existe:
  - intenta validar contra Softland (`SoftlandService.obtener_detalle_oc`),
  - inserta local en `INGRESADO`.
- Si Softland no responde:
  - crea la OC en modo local resiliente con observación.

### 11.4 Despacho de Bodega (`/bodega/despacho/<folio>`)

- Solo estados de bodega válidos (`INGRESADO`, `EN_BODEGA`, `DISPONIBLE EN BODEGA`).
- Exige:
  - guía de despacho,
  - usuario FAENA asignado.
- Al confirmar:
  - cambia estado a `En Ruta`,
  - registra salida, guía, observaciones,
  - guarda `transportista_asignado_id`.

### 11.5 Recepciones de Faena (`/transportista/entregas`)

- Fuente local robusta (`DespachosTracking`).
- Muestra órdenes `En Ruta` y `Entregado`.
- Si el usuario es `FAENA`:
  - solo ve filas con `transportista_asignado_id = user_id`.
- Incluye:
  - acción de cierre para `En Ruta`,
  - acción de ver evidencia para `Entregado` con foto.
- Auto-actualización periódica en UI para reflejar cambios.

### 11.6 Cierre de Recepción (`/transportista/entregar/<folio>`)

- Si `POST`:
  - exige foto de evidencia (obligatoria),
  - acepta formatos móviles/PC (`jpg`, `jpeg`, `png`, `webp`, `heic`, `heif`),
  - guarda archivo en `storage/evidencias`,
  - actualiza orden a `Entregado` con `FechaHoraEntrega`,
  - guarda `UrlFotoEvidencia`, `RegistradoPor` y geolocalización en observaciones.
- Si `GET`:
  - si estado `En Ruta`: muestra formulario de cierre (foto).
  - si estado `Entregado`: muestra evidencia ya tomada.
- Seguridad:
  - un `FAENA` no puede cerrar folios no asignados.

### 11.7 Detalle ERP de Recepción (`/bodega/recepcion/<folio>`)

- Consulta detalle de productos desde Softland.
- Controla acceso por rol y, para perfiles restringidos, aplica validación por `aux_id_softland`.
- Renderiza vista de detalle con:
  - descripción estándar + descripción editada,
  - cantidad solicitada + recibida.

### 11.8 Detalle de Requisición (`/requisicion/<folio>`)

- Busca requisición asociada a OC en Softland.
- Trae:
  - cabecera (solicitante, número req, fechas, centro costo, estado req),
  - detalle de líneas (producto, descripción, cantidad, partida).
- Si no existe requisición:
  - muestra aviso y retorna al dashboard.

### 11.9 Gestión de Usuarios (`/superadmin/usuarios`)

- Actualmente gestionada por perfil `ADMINISTRADOR`.
- Permite crear usuarios con roles:
  - `ADMINISTRADOR`, `BODEGA`, `VISUALIZADOR`, `FAENA`.
- Valida:
  - campos obligatorios,
  - unicidad de usuario/email,
  - rol válido y existente.

### 11.10 Tracking Completo y Reportes

- `tracking_completo`:
  - mezcla estado ERP y estado local para visión consolidada.
- `reportes`:
  - genera métricas por estado y rendimiento operativo.

### 11.11 APIs internas y seguridad por rol

- `POST /api/verificar_qr`
  - autenticado para `ADMINISTRADOR`, `BODEGA`, `FAENA`.
- `GET /api/estado_orden/<folio>`
  - autenticado para `ADMINISTRADOR`, `BODEGA`, `VISUALIZADOR`, `FAENA`,
  - `FAENA` solo folios asignados.
- `GET /api/test-db`
  - solo `ADMINISTRADOR`.

### 11.12 Manejo de errores y resiliencia

- Errores globales:
  - handlers `404`, `403`, `500`.
- Resiliencia:
  - si Softland no está disponible, el tracking local mantiene continuidad operativa.
- Límite de carga:
  - middleware por tamaño máximo de request (`MAX_CONTENT_LENGTH`).

---

## 12) Matriz de Perfiles y Permisos (Operación)

### `ADMINISTRADOR`

- Ver dashboard completo.
- Importar OCs.
- Despachar y asignar a faena.
- Ver tracking global y reportes.
- Gestionar usuarios.
- Acceso a APIs administrativas habilitadas.

### `BODEGA`

- Ver dashboard operativo.
- Importar OCs.
- Despachar y asignar a faena.
- Sin cierre de recepción final en faena.

### `FAENA`

- Ver recepciones asignadas.
- Aceptar y marcar recibido.
- Subir foto obligatoria.
- Ver evidencia de órdenes ya entregadas.
- Sin permisos de importación/despacho inicial.

### `VISUALIZADOR`

- Solo consulta de datos.
- Sin acciones transaccionales (no importar, no despachar, no cerrar recepción).


