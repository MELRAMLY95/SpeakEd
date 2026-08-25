"""Helpers for running tests against a REAL PostgreSQL server.

Set SPEAKED_TEST_PG to a superuser DSN of a throwaway server, for example:

    postgresql://postgres@127.0.0.1:55432/postgres?sslmode=disable

Each test gets its own freshly created database on that server. Only databases
whose name starts with ``speaked_test_`` are ever created or dropped, so a
production database can never be touched by these helpers.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import urlsplit, urlunsplit

ADMIN_DSN_ENV = "SPEAKED_TEST_PG"
TEST_DB_PREFIX = "speaked_test_"


def admin_dsn() -> str | None:
    return os.environ.get(ADMIN_DSN_ENV, "").strip() or None


def available() -> bool:
    """True when a real PostgreSQL server is reachable."""
    dsn = admin_dsn()
    if not dsn:
        return False
    try:
        import psycopg2
    except ImportError:
        return False
    try:
        conn = psycopg2.connect(dsn, connect_timeout=5)
        conn.close()
        return True
    except Exception:
        return False


def _connect_admin():
    import psycopg2
    from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

    conn = psycopg2.connect(admin_dsn(), connect_timeout=10)
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    return conn


def _dsn_for(database: str) -> str:
    parts = urlsplit(admin_dsn())
    query = parts.query
    if "sslmode" not in query:
        query = (query + "&" if query else "") + "sslmode=disable"
    return urlunsplit((parts.scheme, parts.netloc, "/" + database, query, parts.fragment))


def create_database() -> tuple[str, str]:
    """Create a uniquely named throwaway database. Returns (name, dsn)."""
    name = TEST_DB_PREFIX + uuid.uuid4().hex[:12]
    conn = _connect_admin()
    try:
        conn.cursor().execute(f'CREATE DATABASE "{name}"')
    finally:
        conn.close()
    return name, _dsn_for(name)


def drop_database(name: str) -> None:
    """Drop a throwaway database. Refuses any name outside the test prefix."""
    if not name.startswith(TEST_DB_PREFIX):
        raise ValueError(f"refusing to drop non-test database {name!r}")
    conn = _connect_admin()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        cursor.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        conn.close()
