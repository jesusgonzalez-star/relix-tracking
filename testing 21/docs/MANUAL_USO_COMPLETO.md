# Manual de Uso Completo

## 1) Objetivo

Este manual explica el uso operativo de la plataforma de tracking logístico por perfil:

- Bodega
- Faena
- Visualizador
- Superadmin

Incluye flujos paso a paso, validaciones obligatorias, buenas practicas y solucion de problemas frecuentes.

## 2) Conceptos clave

- `OC`: Orden de Compra.
- `Guia`: guia de despacho asociada a un envio.
- `Patente`: patente del camion que transporta la carga.
- `Envio`: despacho especifico de una OC (una OC puede tener varios envios/guias).
- `Evidencia`: fotos de despacho/recepcion asociadas al envio.

## 3) Estados de tracking

- `EN_BODEGA`: disponible para preparar despacho.
- `En Ruta`: enviado desde bodega, pendiente de recepcion en faena.
- `Entregado`: recepcion cerrada en faena.

Notas:
- Una OC puede estar en `En Ruta` y tener mas de una guia/camion.
- El sistema oculta acciones que no aplican (por ejemplo, despacho cuando no queda saldo pendiente).

## 4) Acceso y navegacion general

1. Ingresar por `Login` con usuario y contrasena.
2. El dashboard principal muestra:
   - estadisticas operativas,
   - filtros,
   - tabla de OCs con acciones segun rol.
3. Usar filtros para acotar busqueda por estado, fechas, requisicion, OC y centro de costo.

## 5) Flujo operativo por perfil

## 5.1 Bodega

### 5.1.1 Revisar una OC

1. Ir al dashboard.
2. Ubicar la OC por filtros.
3. Entrar a `Revisar OC` para ver detalle, guias y evidencia.

### 5.1.2 Despachar a faena (total o parcial)

1. En la OC, presionar `Despachar a Faena` (solo aparece si hay saldo real pendiente).
2. Completar:
   - guia de despacho,
   - patente del camion (obligatoria y validada),
   - transportista/asignacion,
   - cantidades por linea.
3. Adjuntar una o varias fotos de evidencia de despacho.
4. Confirmar envio.

Resultado esperado:
- Se crea un envio con su propia guia, patente, detalle y fotos.
- La OC puede seguir con mas envios si queda pendiente.

### 5.1.3 Comportamientos importantes

- Si todo lo ingresado ya esta enviado, no se ofrece boton de despacho.
- Si hay envio parcial, se puede crear otro envio para completar.
- Las fotos quedan asociadas al envio/guia, no mezcladas entre guias.

## 5.2 Faena

### 5.2.1 Interfaz unificada

Faena opera en una sola interfaz (dashboard principal + detalle de recepcion), con filtros:

- Todos
- Pendientes (En Ruta)
- Cerradas (Entregado)

### 5.2.2 Ver detalle y recepcionar

1. Desde el dashboard, abrir `Recepcionar ahora` o `Ver detalle`.
2. En `Aceptar Recepcion`, revisar:
   - guia recibida,
   - patente del envio,
   - camiones/guias de la OC (resumen y detalle por envio).
3. Para cerrar recepcion del envio actual:
   - ingresar guia de confirmacion (debe coincidir),
   - subir foto de recepcion (obligatoria),
   - completar observaciones (minimo requerido),
   - validar checklist completo de lineas,
   - enviar formulario.

Resultado esperado:
- El envio cambia a `Entregado`.
- Se registra evidencia de recepcion y geolocalizacion.
- El retorno vuelve al dashboard de faena (misma interfaz, sin navbar legacy).

## 5.3 Visualizador

Perfil de consulta:

- Accede a tracking general y reportes.
- Sin acciones de despacho ni recepcion.
- Puede revisar estados, tiempos y evidencia consolidada.

## 5.4 Superadmin

Perfil de administracion y soporte:

- Gestion de usuarios y roles.
- Acceso transversal a vistas operativas.
- Apoyo en auditoria de trazabilidad y control de incidentes.

## 6) Reglas obligatorias del sistema

- Patente obligatoria al despachar en bodega.
- Guia obligatoria en despacho y validada en recepcion.
- Foto obligatoria para cierre de recepcion en faena.
- Checklist completo de lineas para recepcionar.
- Control de permisos por rol y asignacion.

## 7) Evidencias (fotos) y trazabilidad

- Cada envio/guia guarda su propia evidencia.
- En vistas de OC con multiples guias, cada bloque muestra sus fotos correctas.
- En faena, al recepcionar un envio, se prioriza evidencia de ese envio (no de otro).
- Si no hay evidencia disponible, la interfaz muestra estado sin foto en ese bloque.

## 8) Buenas practicas operativas

- Usar una guia por envio real y no reutilizar guia entre camiones.
- Subir fotos claras por cada envio.
- Registrar observaciones concretas (danos, faltantes, conformidad).
- En faena, validar primero guia/patente y luego checklist antes de cerrar.
- Usar filtros de estado para trabajar solo pendientes.

## 9) Problemas frecuentes y solucion

### 9.1 No aparece boton `Despachar a Faena`

Posible causa:
- no queda saldo ingresado pendiente de envio.

Accion:
- revisar detalle de OC y envios existentes.

### 9.2 Guia no coincide en recepcion

Posible causa:
- error de digitacion o guia incorrecta.

Accion:
- confirmar guia de bodega mostrada en pantalla y reintentar.

### 9.3 No puedo cerrar recepcion

Posibles causas:
- falta foto,
- checklist incompleto,
- observacion muy corta,
- envio ya no esta en `En Ruta`.

Accion:
- completar validaciones y volver a enviar.

### 9.4 Fotos no visibles o mezcladas

Posible causa:
- evidencia historica incompleta o registro sin archivo fisico.

Accion:
- abrir detalle por guia/envio y verificar bloque de evidencia de ese envio.

## 10) Checklist de operacion diaria

## Bodega (inicio a cierre)

1. Filtrar OCs del dia.
2. Revisar pendientes reales.
3. Despachar con guia + patente + fotos.
4. Confirmar que estados queden en `En Ruta`.

## Faena (inicio a cierre)

1. Filtrar `Pendientes (En Ruta)`.
2. Abrir detalle por envio.
3. Confirmar guia, checklist y evidencia.
4. Cerrar recepcion.
5. Verificar que pase a `Entregado`.

## 11) Recomendaciones de administracion

- Mantener usuarios/roles actualizados.
- Evitar compartir cuentas.
- Revisar periodicamente reportes y OCs con estados atipicos.
- Usar observaciones para trazabilidad y auditoria.

---

Si necesitas, se puede generar una version corta de entrenamiento (1 hoja) para operadores nuevos de Bodega y Faena.
