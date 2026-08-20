import sqlite3
from pathlib import Path

from flask import current_app, g

from config import BASE_DIR
from database.models import SCHEMA


def _sqlite_path(url: str) -> str:
    if url in {"sqlite:///:memory:", "sqlite://:memory:"}:
        return ":memory:"
    raw = url
    if raw.startswith("sqlite:///"):
        raw = raw[10:]
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path)


def get_db():
    if "db" not in g:
        url = current_app.config["DATABASE_URL"]
        path = _sqlite_path(url)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(app=None):
    if app is not None:
        with app.app_context():
            db = get_db()
            db.executescript(SCHEMA)
            db.commit()
            return
    db = get_db()
    db.executescript(SCHEMA)
    db.commit()


def query_one(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def query_all(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def execute(sql, args=()):
    db = get_db()
    cursor = db.execute(sql, args)
    db.commit()
    return cursor
