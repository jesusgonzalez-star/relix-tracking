"""
Abstracción de conexión a la base local (MariaDB).

Este módulo retorna un wrapper sobre PyMySQL compatible con la interfaz
pyodbc-style que usa el código legacy:

- placeholders ``?`` se traducen a ``%s`` (los literales ``%`` se duplican)
- ``cursor.execute(sql, scalar)`` → ``execute(sql, (scalar,))``
- silencia error 1061 (Duplicate key name) en ``CREATE INDEX IF NOT EXISTS``
  por si se ejecuta contra versiones de MariaDB sin soporte nativo completo.
"""
import logging
import os
import re
import urllib.parse

import pymysql

from config import LocalDbConfig

logger = logging.getLogger(__name__)


# ─── Normalización de placeholders y detección de IF NOT EXISTS ────────────

_RE_CREATE_INDEX_IF_NOT_EXISTS = re.compile(
    r'\bCREATE\s+(UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS\b', re.IGNORECASE
)


def _translate_placeholders(sql: str) -> str:
    """Convierte ``?`` (estilo qmark) a ``%s`` (estilo PyMySQL).

    Respeta literales entre comillas simples/dobles para no tocar ``'?'``.
    Duplica los ``%`` literales para que PyMySQL no los interprete.
    """
    if sql is None or ('?' not in sql and '%' not in sql):
        return sql
    out = []
    i, n = 0, len(sql)
    in_squote = False
    in_dquote = False
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_dquote:
            in_squote = not in_squote
            out.append(ch)
        elif ch == '"' and not in_squote:
            in_dquote = not in_dquote
            out.append(ch)
        elif in_squote or in_dquote:
            out.append(ch)
        elif ch == '?':
            out.append('%s')
        elif ch == '%':
            out.append('%%')
        else:
            out.append(ch)
        i += 1
    return ''.join(out)


# ─── Connection wrappers ─────────────────────────────────────────────────────

class _MariaDBCursorWrapper:
    """Cursor compatible con la interfaz pyodbc-style que usa el código legacy.

    - acepta ``execute(sql, scalar)`` o ``execute(sql, tuple)``
    - traduce ``?`` → ``%s``
    - silencia el error 1061 de CREATE INDEX cuando vino de un IF NOT EXISTS
    """

    def __init__(self, real_cursor):
        self._cursor = real_cursor

    def _exec(self, sql, params):
        swallow_dup_idx = bool(_RE_CREATE_INDEX_IF_NOT_EXISTS.search(sql or ''))
        sql = _translate_placeholders(sql)
        try:
            if params is None:
                return self._cursor.execute(sql)
            if isinstance(params, (list, tuple)):
                return self._cursor.execute(sql, tuple(params))
            return self._cursor.execute(sql, (params,))
        except pymysql.err.OperationalError as e:
            if swallow_dup_idx and getattr(e, 'args', (None,))[0] == 1061:
                return 0
            raise

    def execute(self, sql, params=None, *args):
        if args:
            params = (params, *args)
        return self._exec(sql, params)

    def executemany(self, sql, seq_of_params):
        sql = _translate_placeholders(sql)
        return self._cursor.executemany(sql, seq_of_params)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        if size is not None:
            return self._cursor.fetchmany(size)
        return self._cursor.fetchmany()

    @property
    def lastrowid(self):
        return self._cursor.lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def close(self):
        return self._cursor.close()

    def __iter__(self):
        return iter(self._cursor)


class _MariaDBConnectionWrapper:
    """Connection compatible con el resto del código legacy."""

    def __init__(self, real_conn):
        self._conn = real_conn

    def cursor(self):
        return _MariaDBCursorWrapper(self._conn.cursor())

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur


# ─── Parser de URI MariaDB ───────────────────────────────────────────────────

def _parse_mariadb_uri(uri: str) -> dict:
    """Acepta ``mysql+pymysql://user:pass@host:port/db?charset=utf8mb4`` o
    ``mysql://...``. Retorna dict con kwargs para ``pymysql.connect``.
    """
    parsed = urllib.parse.urlparse(uri)
    user = urllib.parse.unquote(parsed.username or 'root')
    password = urllib.parse.unquote(parsed.password or '')
    host = parsed.hostname or '127.0.0.1'
    port = parsed.port or 3306
    database = (parsed.path or '/').lstrip('/') or 'tracking'

    qs = urllib.parse.parse_qs(parsed.query)
    charset = (qs.get('charset') or ['utf8mb4'])[0]

    return dict(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        charset=charset,
        autocommit=False,
        connect_timeout=10,
    )


def _resolve_mariadb_uri() -> str:
    uri = (os.environ.get('SQLALCHEMY_DATABASE_URI') or '').strip()
    if uri:
        return uri
    return getattr(LocalDbConfig, 'SQLALCHEMY_DATABASE_URI', '') or ''


class DatabaseConnection:
    """Conexión a la base local (MariaDB)."""

    @classmethod
    def get_connection(cls):
        uri = _resolve_mariadb_uri()

        if not uri.startswith('mysql'):
            raise RuntimeError(
                f'SQLALCHEMY_DATABASE_URI no soportada: {uri!r}\n'
                'Solo se acepta MariaDB/MySQL: mysql+pymysql://user:pass@host/db'
            )

        kwargs = _parse_mariadb_uri(uri)
        try:
            conn = pymysql.connect(**kwargs)
            # PIPES_AS_CONCAT: habilita ``a || b`` como CONCAT (ANSI SQL).
            # ANSI_QUOTES: permite identificadores con comillas dobles.
            with conn.cursor() as _c:
                _c.execute(
                    "SET SESSION sql_mode = "
                    "CONCAT(@@SESSION.sql_mode, ',PIPES_AS_CONCAT,ANSI_QUOTES')"
                )
            return _MariaDBConnectionWrapper(conn)
        except Exception as e:
            logger.error('Error de conexión MariaDB: %s', e)
            raise
