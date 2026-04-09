# Scripts de mantenimiento (no runtime web)

Estos archivos no son parte del arranque de `app.py`.
Se usan solo para inicializacion, pruebas locales o tareas puntuales.

## Contenido

- `run_sql.py`: ejecuta el SQL base por bloques `GO`.
- `database_softland_tracking.sql`: schema SQL de soporte/mock.
- `db_setup.py`: setup historico de tablas locales.
- `create_demo_user.py`: crea usuarios/demo data.
- `populate_softland.py`: rellena mock data de Softland.
- `extract_errors.py`: extrae tracebacks recientes desde `app.log`.

## Nota

Antes de ejecutar scripts desde esta carpeta, revisar rutas relativas y variables de entorno (`.env`).
