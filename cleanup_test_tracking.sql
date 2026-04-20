-- ============================================================
-- Limpieza de filas de prueba insertadas para testear los chips
-- de estado del supervisor de contratos (#7064, #7247, #7142 …)
--
-- Ejecutar con:
--   mysql -h localhost -u tracking -prelix tracking < cleanup_test_tracking.sql
-- o desde Python:
--   python -c "from dotenv import load_dotenv; load_dotenv('.env'); \
--     import os; from sqlalchemy import create_engine, text; \
--     eng = create_engine(os.environ['SQLALCHEMY_DATABASE_URI']); \
--     open_sql = open('cleanup_test_tracking.sql').read(); \
--     [eng.connect().execute(text(s)) for s in open_sql.split(';') if s.strip() and not s.strip().startswith('--')]"
--
-- OCs inyectadas el 2026-04-20 por la sesión de pruebas del supervisor
-- ============================================================

DELETE FROM despachostracking
WHERE NumOc IN (
    58275, 58276,                              -- prueba inicial (En Ruta, EN_BODEGA)
    58792, 58731, 58729, 58728, 58722,         -- En Ruta
    58704, 58703, 58702, 58614, 58568,         -- EN_BODEGA
    58548, 58520, 58501, 58481,                -- Entregado
    58464, 58463, 58458, 58455, 58444          -- INGRESADO
);
