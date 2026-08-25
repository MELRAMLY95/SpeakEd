"""Tests for scripts/migrate_sqlite_to_postgres.py against a real PostgreSQL server."""

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

from app import create_app
from config import TestConfig
from database.database import query_all, query_one
from tests import pg_real

pytestmark = pytest.mark.skipif(
    not pg_real.available(),
    reason="set SPEAKED_TEST_PG to a throwaway PostgreSQL DSN to run migration tests",
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_sqlite_to_postgres.py"
PASSWORD = "password12"


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def source_sqlite(tmp_path):
    """A populated SQLite database standing in for the legacy one."""
    db_path = tmp_path / "legacy.db"

    class Local(TestConfig):
        DATABASE_URL = f"sqlite:///{db_path}"
        SECRET_KEY = "legacy"

    app = create_app(Local)
    client = app.test_client()
    client.post(
        "/signup",
        data={"name": "Legacy User", "email": "legacy@example.com", "password": PASSWORD, "confirm": PASSWORD},
        follow_redirects=True,
    )
    response = client.post("/practice/start", data={"section": "roleplay"})
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
    client.post(
        f"/exam/{attempt_id}/turn",
        json={"transcript": "Legacy answer about swimming on Fridays.", "metrics": {"duration_ms": 5000}},
    )
    return db_path, attempt_id


@pytest.fixture()
def target_pg():
    name, dsn = pg_real.create_database()
    try:
        yield dsn
    finally:
        pg_real.drop_database(name)


def _init_target(dsn):
    class Local(TestConfig):
        DATABASE_URL = dsn
        SECRET_KEY = "stable-target-secret"

    return create_app(Local)


def test_dry_run_writes_nothing(source_sqlite, target_pg):
    db_path, _ = source_sqlite
    app = _init_target(target_pg)
    module = _load_script()

    assert module.migrate(db_path, target_pg, commit=False) == 0

    with app.app_context():
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0
        assert query_one("SELECT COUNT(*) AS n FROM attempts")["n"] == 0


def test_migration_preserves_users_attempts_and_transcripts(source_sqlite, target_pg):
    db_path, attempt_id = source_sqlite
    app = _init_target(target_pg)
    module = _load_script()

    assert module.migrate(db_path, target_pg, commit=True) == 0

    with app.app_context():
        user = query_one("SELECT * FROM users WHERE email = ?", ("legacy@example.com",))
        attempt = query_one("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
        transcripts = query_all("SELECT * FROM transcripts WHERE attempt_id = ?", (attempt_id,))

    assert user is not None, "user was not migrated"
    assert attempt is not None, "attempt was not migrated"
    assert attempt["user_id"] == user["id"], "relationship was not preserved"
    assert any("swimming" in t["text"] for t in transcripts), "transcript was not migrated"


def test_migrated_password_hash_still_works(source_sqlite, target_pg):
    db_path, _ = source_sqlite
    app = _init_target(target_pg)
    _load_script().migrate(db_path, target_pg, commit=True)

    with app.app_context():
        stored = query_one("SELECT password_hash FROM users WHERE email = ?", ("legacy@example.com",))["password_hash"]
    assert check_password_hash(stored, PASSWORD), "the migrated hash no longer verifies"

    client = app.test_client()
    response = client.post(
        "/login",
        data={"email": "legacy@example.com", "password": PASSWORD},
        follow_redirects=True,
    )
    assert b"Incorrect email or password" not in response.data
    assert client.get("/dashboard").status_code == 200


def test_migration_is_rerunnable_without_duplicating(source_sqlite, target_pg):
    db_path, _ = source_sqlite
    app = _init_target(target_pg)
    module = _load_script()

    module.migrate(db_path, target_pg, commit=True)
    module.migrate(db_path, target_pg, commit=True)

    with app.app_context():
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 1
        assert query_one("SELECT COUNT(*) AS n FROM attempts")["n"] == 1


def test_new_signup_after_migration_does_not_collide(source_sqlite, target_pg):
    db_path, _ = source_sqlite
    app = _init_target(target_pg)
    _load_script().migrate(db_path, target_pg, commit=True)

    client = app.test_client()
    response = client.post(
        "/signup",
        data={"name": "Fresh User", "email": "fresh@example.com", "password": PASSWORD, "confirm": PASSWORD},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert client.get("/dashboard").status_code == 200
    with app.app_context():
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 2


def test_source_sqlite_is_never_modified(source_sqlite, target_pg):
    db_path, _ = source_sqlite
    _init_target(target_pg)
    before = db_path.read_bytes()

    _load_script().migrate(db_path, target_pg, commit=True)

    assert db_path.read_bytes() == before, "the SQLite source file was modified"
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    conn.close()


def test_script_refuses_to_run_without_a_postgres_dsn(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--sqlite", "instance/speaked.db"],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT.parent.parent),
    )
    assert result.returncode == 1
    assert "PostgreSQL DSN is required" in result.stdout


def test_script_never_prints_password_hashes(source_sqlite, target_pg, capsys):
    db_path, _ = source_sqlite
    _init_target(target_pg)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()

    _load_script().migrate(db_path, target_pg, commit=True)
    output = capsys.readouterr().out

    assert stored not in output
    assert "scrypt:" not in output
    assert PASSWORD not in output
