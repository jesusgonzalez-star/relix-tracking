# Pruebas automáticas

## Ejecución habitual (sin ERP ni SQL Server)

Desde la raíz del workspace (donde está `pyproject.toml`):

```bash
python -m pytest -v
```

Incluye cobertura y `--cov-fail-under` definido en `pyproject.toml`. Para solo tests rápidos sin medir cobertura:

```bash
python -m pytest testing 21/tests -v --no-cov
```

## Pruebas de integración (opcional)

Requieren instancias accesibles según `config` / variables de entorno (`LOCAL_SERVER`, `LOCAL_DB_NAME`, credenciales Softland, etc.).

1. Defina `RUN_INTEGRATION_TESTS=1`.
2. Ejecute:

```bash
python -m pytest testing 21/tests/integration -v -m integration --no-cov
```

Si la BD no está disponible, esos tests fallarán (no se saltan salvo que no active la variable).

## Marcador `integration`

Registrado en `pyproject.toml`. Con `--strict-markers`, cualquier marca nueva debe declararse allí.
