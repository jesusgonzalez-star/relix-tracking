"""
Pruebas contra SQL Server / Softland reales.

Solo se ejecutan con RUN_INTEGRATION_TESTS=1 (ver TESTS.md).
"""
import os

import pytest

RUN = os.environ.get('RUN_INTEGRATION_TESTS', '').lower() in ('1', 'true', 'yes')


@pytest.mark.integration
@pytest.mark.skipif(not RUN, reason='RUN_INTEGRATION_TESTS no está activado')
def test_local_sqlserver_select_one():
    from utils.db_legacy import DatabaseConnection

    conn = DatabaseConnection.get_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT 1 AS n')
        row = cur.fetchone()
        assert row is not None
        assert int(row[0]) == 1
    finally:
        conn.close()
