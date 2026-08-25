import logging
import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from flask import current_app, g

from config import BASE_DIR
from database.models import POSTGRES_SCHEMA, SCHEMA

logger = logging.getLogger(__name__)

# Arbitrary constant so all workers contend on the same advisory lock while
# creating the schema.
SCHEMA_LOCK_KEY = 8274419100234117


class CursorResult:
    """Expose lastrowid for both SQLite and PostgreSQL INSERT statements."""

    def __init__(self, cursor, lastrowid):
        self._cursor = cursor
        self.lastrowid = lastrowid

    def __getattr__(self, name):
        return getattr(self._cursor, name)


def engine_kind(url: str | None) -> str:
    raw = (url or "").strip()
    if raw.startswith("postgres://") or raw.startswith("postgresql://"):
        return "postgres"
    return "sqlite"


def _sqlite_path(url: str) -> str:
    if url in {"sqlite:///:memory:", "sqlite://:memory:", ":memory:"}:
        raise RuntimeError(
            "DATABASE_URL points at an in-memory SQLite database. This application opens one "
            "connection per request, and each connection to ':memory:' gets its own empty "
            "database, so no account or attempt would survive a single request. Use a file path "
            "such as sqlite:///instance/speaked.db, or PostgreSQL."
        )
    raw = url
    if raw.startswith("sqlite:////"):
        raw = "/" + raw[11:]
    elif raw.startswith("sqlite:///"):
        raw = raw[10:]
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


def normalize_postgres_dsn(url: str) -> str:
    raw = (url or "").strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "sslmode" not in query:
        query["sslmode"] = "require"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def to_postgres_sql(sql: str) -> str:
    sql = sql.replace("ON CONFLICT(", "ON CONFLICT (")
    out = []
    in_single = False
    in_double = False
    for ch in sql:
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif ch == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(ch)
    converted = "".join(out)
    stripped = converted.strip().rstrip(";")
    upper = stripped.upper()
    if upper.startswith("INSERT") and "RETURNING" not in upper:
        stripped = stripped + " RETURNING id"
    return stripped


def _split_statements(schema: str) -> list[str]:
    statements = []
    for chunk in schema.split(";"):
        text = chunk.strip()
        if text:
            statements.append(text)
    return statements


def get_db():
    if "db" not in g:
        url = current_app.config["DATABASE_URL"]
        kind = engine_kind(url)
        g.db_kind = kind
        if kind == "postgres":
            try:
                import psycopg2
                from psycopg2.extras import RealDictCursor
            except ImportError as exc:
                raise RuntimeError(
                    "DATABASE_URL is PostgreSQL but the psycopg2 driver is not installed. "
                    "Add psycopg2-binary to requirements.txt. Refusing to fall back to SQLite, "
                    "which would lose all data on the next restart."
                ) from exc
            try:
                g.db = psycopg2.connect(normalize_postgres_dsn(url), cursor_factory=RealDictCursor)
            except Exception as exc:
                # Never fall back to SQLite here: a silent fallback in production
                # writes accounts to a disk that is wiped on redeploy.
                logger.error("PostgreSQL connection failed: %s", exc)
                raise RuntimeError(
                    f"Could not connect to PostgreSQL: {exc}. Check DATABASE_URL, credentials, "
                    "and that the database accepts connections."
                ) from exc
        else:
            path = _sqlite_path(url)
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            g.db = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    g.pop("db_kind", None)
    if db is not None:
        db.close()


def _warn_if_ephemeral():
    url = current_app.config.get("DATABASE_URL") or ""
    if current_app.config.get("IS_RENDER") and engine_kind(url) == "sqlite":
        logger.warning(
            "RENDER is set but DATABASE_URL is SQLite. Render's filesystem is ephemeral, "
            "so accounts and progress will be lost on restart. Attach Render PostgreSQL and set DATABASE_URL."
        )


def init_db(app=None):
    if app is not None:
        with app.app_context():
            init_db()
            return
    _warn_if_ephemeral()
    db = get_db()
    kind = g.get("db_kind") or engine_kind(current_app.config["DATABASE_URL"])
    schema = POSTGRES_SCHEMA if kind == "postgres" else SCHEMA
    if kind == "postgres":
        cursor = db.cursor()
        # Every gunicorn worker runs init_db at boot. Concurrent "CREATE TABLE IF
        # NOT EXISTS" is not race-safe in PostgreSQL and can fail with a
        # duplicate pg_type error, so serialise schema creation with an advisory
        # lock held for the duration of the transaction.
        try:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_KEY,))
            for statement in _split_statements(schema):
                cursor.execute(statement)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            cursor.close()
        return
    db.executescript(schema)
    db.commit()


def query_one(sql, args=()):
    cursor = _run(sql, args, commit=False)
    row = cursor.fetchone()
    return row


def query_all(sql, args=()):
    cursor = _run(sql, args, commit=False)
    return cursor.fetchall()


def execute(sql, args=()):
    return _run(sql, args, commit=True)


def _returned_id(cursor):
    """Read the id produced by an INSERT ... RETURNING id statement.

    psycopg2 reports ``lastrowid`` as a row OID, which is 0 or None for ordinary
    tables, so RETURNING is the only reliable source of a new primary key. The
    row must be read before the transaction is committed.
    """
    try:
        row = cursor.fetchone()
    except Exception:
        return None
    if not row:
        return None
    if isinstance(row, dict):
        if "id" in row:
            return row["id"]
        values = list(row.values())
        return values[0] if values else None
    return row[0]


def _run(sql, args=(), commit=False):
    db = get_db()
    kind = g.get("db_kind") or engine_kind(current_app.config["DATABASE_URL"])
    if kind == "postgres":
        cursor = db.cursor()
        converted = to_postgres_sql(sql)
        # psycopg2 only performs %-interpolation when the parameter sequence is
        # not None, so parameterless SQL must pass None rather than an empty
        # tuple or any literal % in the statement would raise.
        params = tuple(args) if args else None
        try:
            cursor.execute(converted, params)
        except Exception:
            # Leaving a failed statement uncommitted aborts the whole PostgreSQL
            # transaction and every later query in the request would fail too.
            db.rollback()
            raise
        lastrowid = None
        if commit:
            # Never fetchone() after UPDATE/DELETE. psycopg2 raises
            # ProgrammingError ("no results to fetch") and that aborts the
            # whole PostgreSQL transaction. Retry marking starts with an UPDATE.
            is_insert = converted.strip().upper().startswith("INSERT")
            if is_insert:
                lastrowid = _returned_id(cursor)
                if lastrowid is None and "ON CONFLICT" not in converted.upper():
                    # Callers use this id to look the new row straight back up, so a
                    # missing id must fail here rather than surface later as a
                    # confusing lookup miss in an unrelated part of the app.
                    db.rollback()
                    raise RuntimeError(
                        "PostgreSQL INSERT did not return an id; the row was not created. "
                        f"Statement: {converted.split('VALUES')[0].strip()}"
                    )
            db.commit()
        return CursorResult(cursor, lastrowid)
    cursor = db.execute(sql, args)
    if commit:
        db.commit()
    return CursorResult(cursor, cursor.lastrowid)
