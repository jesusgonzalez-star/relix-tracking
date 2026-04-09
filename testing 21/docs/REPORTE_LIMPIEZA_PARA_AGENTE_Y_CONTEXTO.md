# Reporte: qué borrar o excluir para ahorrar contexto del agente (sin romper la app)

**Estado (aplicado en el repo):** Se eliminaron logs y `.txt` de depuración, `test_*.py`, `recover_logs.py`, `extract_frontend.py`, `app_legacy_monolito.py`, la carpeta `scripts/` y `services/sync_service.py`. La documentación larga de la raíz pasó a `docs/historico/`. Existe `.cursorignore` con `.venv/`, `__pycache__`, `docs/historico/`. Si necesitas migraciones o `cron_sync`, recupera esos scripts desde Git u otra copia.

---

Objetivo: reducir archivos que Cursor/otro agente indexa o sugiere abrir, **manteniendo** `python app.py` / Gunicorn funcionando igual.

La app en producción arranca desde [`app.py`](file:///testing%2021/app.py) y carga: `config`, `extensions`, `routes` (`softland_routes`, `tracking_routes`, `frontend_routes`), `models` vía SQLAlchemy, `services/softland_service` (usado por rutas), plantillas y `static`.

---

## 1. Mayor impacto sin borrar nada: excluir `.venv` del índice

Carpeta **`.venv/`** concentra miles de archivos de terceros. No la borres (el entorno deja de funcionar); **exclúyela del workspace del agente**.

- Crea o edita **`.cursorignore`** en la raíz del proyecto `testing 21` con:

```gitignore
.venv/
**/__pycache__/
*.pyc
```

- Asegura **`.gitignore`** con `.venv/` si no quieres versionar el entorno virtual.

Esto suele ser **más efectivo** que eliminar `.py` sueltos del proyecto.

---

## 2. Borrado seguro: basura de depuración y salidas (no importados por la app)

Ninguno de estos archivos es `import`ado por `app.py` ni por los blueprints en runtime. Puedes eliminarlos con **impacto nulo** en la ejecución:

| Archivo | Motivo |
|---------|--------|
| `live_crash.txt` | Volcado de error manual |
| `recent_errors.txt` | Log pegado |
| `traceback_roles.txt` | Traceback pegado |
| `traceback_output.txt` | Traceback pegado |
| `error.txt`, `err_log.txt`, `error_log.txt` | Logs sueltos |
| `tail_app_log.txt` | Salida de tail |
| `cols.txt`, `tables.txt` | Volcados de esquema/consulta |
| `routes.txt` | Listado de rutas desactualizado (no usado por código) |
| `error.log`, `app.log` | Logs generados en disco (se pueden regenerar; no son código) |

**Nota:** Si usas `gunicorn_config.py` y escribes `access.log` / `error.log` en el directorio de trabajo, esos archivos **se recrean** al arrancar; puedes borrarlos cuando el servicio esté parado.

---

## 3. Borrado seguro: scripts de prueba y utilidades de desarrollo en la raíz

| Archivo | Motivo |
|---------|--------|
| `test.py` | Script de prueba |
| `test_flask.py` | Prueba manual Flask |
| `test_detalles.py` | Prueba manual |
| `test_query.py` | Prueba manual |
| `test_crash.py` | Prueba manual |
| `test_admin_tracking.py` | Prueba manual |
| `recover_logs.py` | Utilidad; no enlazada desde la app |
| `extract_frontend.py` | Extractor one-off contra un `app_legacy` externo; rutas fijas a otra carpeta |

La aplicación **no** los importa.

---

## 4. Borrado seguro: monolito legacy (solo referencia en `extract_frontend.py`)

| Archivo | Líneas (aprox.) | Motivo |
|---------|-----------------|--------|
| `app_legacy_monolito.py` | ~1150+ | **No** está importado por `app.py` ni por `routes/`. Es copia antigua del monolito. |

Si ya migraste todo a `routes/frontend_routes.py`, puedes borrarlo y ganar mucho contexto si el agente abre el árbol completo.

**Condición:** conserva una copia en otro medio (zip/Git histórico) si aún la usas como referencia humana.

---

## 5. Opcional: carpeta `scripts/` (operación / migraciones)

No la carga Flask al arrancar. Contiene tareas puntuales:

- `crear_roles.py`, `migracion_rbac.py`, `migracion_historica_2026.py`, `normalize_business_roles.py`, `set_profile_passwords.py`
- `cron_sync.py` → importa [`services/sync_service.py`](../services/sync_service.py)

**Si borras `scripts/` entero:** la app web sigue funcionando.

**Pero:** perderías comandos de migración y, si en producción tienes **cron** llamando a `cron_sync.py`, dejarías de tener ese script en el repo (deberías conservarlo en el servidor o en otro repositorio de ops).

**Si solo quieres reducir contexto y aún usas sincronización programada:** mueve `scripts/` y `sync_service.py` a un repo `ops/` o documéntalos fuera del árbol que el agente indexa (o añade `scripts/` a `.cursorignore` sin borrar).

---

## 6. Opcional: `services/sync_service.py`

Solo lo usa `scripts/cron_sync.py`. **No** lo importa `frontend_routes` ni `app.py`.

- Puedes **borrarlo** si no ejecutas `cron_sync` y no planeas esa sincronización.
- Si mantienes `cron_sync.py`, **conserva** `sync_service.py`.

---

## 7. Documentación Markdown (no afecta runtime)

Puedes **archivar o borrar** para que el agente no los sugiera al buscar “todo el repo”. La app no los lee en ejecución:

- `INDEX.md`
- `INFORME_COMPLETO_FLUJO_DATOS_SOFTLAND_Y_LOCAL.md`
- `PRIMEROS_PASOS.md`
- `SEGURIDAD.md`
- `RESUMEN_VISUAL.md`
- `CAMBIOS.md`
- `MEJORAS.md`
- `docs/DESPLIEGUE_LINUX_APACHE.md` (mantener si sirve para despliegue; o mover fuera del workspace de Cursor)

**Recomendación:** dejar **uno** (por ejemplo `INDEX.md` corto) y mover el resto a `docs/historico/` o un zip; o añadir `*.md` selectivos en `.cursorignore` si prefieres no borrar.

---

## 8. No borrar (necesarios para que “siga funcionando perfectamente”)

| Ruta | Motivo |
|------|--------|
| `app.py`, `config.py`, `extensions.py` | Arranque y configuración |
| `routes/*.py` | Rutas web y API |
| `utils/auth.py`, `utils/db_legacy.py`, `utils/errors.py` | Auth y BD GUI |
| `services/softland_service.py` | ERP desde frontend y `softland_routes` |
| `models/tracking.py`, `schemas/tracking.py` | API tracking + `db.create_all()` |
| `templates/`, `static/` | UI |
| `storage/` (estructura) | Evidencias; vaciar solo archivos viejos si quieres, no quitar la carpeta si la app escribe ahí |
| `requirements.txt`, `gunicorn_config.py` | Despliegue |
| `docs/REPORTE_*` (este tipo) | Opcional conservar como referencia |

**Atención:** [`routes/frontend_routes.py`](../routes/frontend_routes.py) es **muy grande** (~3500+ líneas). No se puede “borrar para contexto” sin romper la app; mitigar con búsquedas acotadas o refactor futuro (fuera de este reporte).

---

## 9. Resumen de prioridades

1. **`.cursorignore` + `.gitignore` con `.venv/`** — máximo ahorro de tokens del agente.
2. **Borrar txt/logs/tracebacks** de la raíz — seguro y limpio.
3. **Borrar `test_*.py`, `recover_logs.py`, `extract_frontend.py`** — seguro.
4. **Borrar `app_legacy_monolito.py`** — seguro para runtime si no lo usas tú a mano.
5. **`scripts/` + `sync_service.py`** — solo si confirmas que no hay cron ni migraciones desde ese árbol.
6. **Markdown** — consolidar, archivar o ignorar en Cursor.

---

## 10. Checklist rápido post-limpieza

```bash
# Desde la raíz del proyecto, con venv activado
python -c "from app import create_app; create_app()"
# o
python app.py
```

Probar login y una pantalla crítica (bodega/faena) tras eliminar archivos.

---

*Documento orientado a reducir ruido para asistentes de código; revisa backups antes de borrar historial útil.*
