-- ============================================================
-- Limpieza de datos de prueba para la vista del supervisor de contratos.
-- Borra inserts en 3 tablas:
--   - despachostracking         (chips de estado simple)
--   - despachosenvio            (viaje + foto de evidencia)
--   - despachosenviodetalle     (recepción línea por línea en faena)
--
-- Ejecutar con:
--   python -c "from dotenv import load_dotenv; load_dotenv('.env'); \
--     import os; from sqlalchemy import create_engine, text; \
--     eng = create_engine(os.environ['SQLALCHEMY_DATABASE_URI']); \
--     sql = open('cleanup_test_tracking.sql', encoding='utf-8').read(); \
--     [c := eng.connect(), [c.execute(text(s)) for s in sql.split(';') if s.strip() and not s.strip().startswith('--')], c.commit()]"
-- ============================================================

-- 1) Detalle de recepción (hijos)
DELETE FROM despachosenviodetalle WHERE NumOc IN (58275, 58501);

-- 2) Cabeceras de envío
DELETE FROM despachosenvio WHERE NumOc IN (58275, 58501);

-- 3) Tracking simple insertado en sesiones de prueba
DELETE FROM despachostracking
WHERE NumOc IN (
    58275, 58276,                              -- prueba inicial
    58792, 58731, 58729, 58728, 58722,         -- En Ruta
    58704, 58703, 58702, 58614, 58568,         -- EN_BODEGA
    58548, 58520, 58501, 58481,                -- Entregado
    58464, 58463, 58458, 58455, 58444          -- INGRESADO
);
