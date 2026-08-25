"""Regression tests for signup/login on the PostgreSQL code path.

These run against tests/fake_pg.py, an in-process driver that enforces the
psycopg2 rules our adapter must satisfy (``%s`` placeholders, dict rows,
``RETURNING id``, identity columns). No real database is created or deleted.
"""

import pytest
from werkzeug.security import check_password_hash

from app import create_app
from config import TestConfig
from database.database import engine_kind, query_one
from tests import fake_pg

PASSWORD = "password12"
WRONG_PASSWORD = "password13"
EMAIL = "pg-student@example.com"


def _pg_config(secret="stable-postgres-secret"):
    class Local(TestConfig):
        DATABASE_URL = "postgresql://speaked:secret@db.internal:5432/speaked"
        SECRET_KEY = secret

    return Local


@pytest.fixture()
def pg(monkeypatch, tmp_path):
    connections = fake_pg.install(monkeypatch, tmp_path / "pg" / "speaked.sql")
    return connections


def _signup(client, email=EMAIL, password=PASSWORD):
    return client.post(
        "/signup",
        data={"name": "Malak", "email": email, "password": password, "confirm": password},
        follow_redirects=True,
    )


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def test_config_is_detected_as_postgres(pg):
    app = create_app(_pg_config())
    assert engine_kind(app.config["DATABASE_URL"]) == "postgres"


def test_signup_stores_a_real_werkzeug_hash(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    assert _signup(client).status_code == 200

    with app.app_context():
        user = query_one("SELECT * FROM users WHERE email = ?", (EMAIL,))

    assert user is not None, "signup did not create a row that login can find"
    stored = user["password_hash"]
    assert isinstance(stored, str)
    assert stored != PASSWORD
    assert PASSWORD not in stored
    assert stored.startswith(("scrypt:", "pbkdf2:"))
    assert check_password_hash(stored, PASSWORD) is True
    assert check_password_hash(stored, WRONG_PASSWORD) is False


def test_hash_is_not_truncated_by_the_database(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)

    with app.app_context():
        stored = query_one("SELECT password_hash FROM users WHERE email = ?", (EMAIL,))["password_hash"]

    # Werkzeug scrypt hashes are ~162 chars; a VARCHAR(n)-style truncation would
    # silently shorten this and every login would then fail.
    assert len(stored) > 80
    assert stored.count("$") == 2


def test_login_succeeds_with_correct_password(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)
    client.get("/logout")

    response = _login(client)
    assert response.status_code == 200
    assert b"Incorrect email or password" not in response.data
    assert client.get("/dashboard").status_code == 200


def test_login_rejects_an_incorrect_password(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)
    client.get("/logout")

    response = _login(client, password=WRONG_PASSWORD)
    assert b"Incorrect email or password" in response.data
    assert client.get("/dashboard", follow_redirects=True).status_code == 200
    assert b"Sign in" in client.get("/dashboard", follow_redirects=True).data


def test_login_still_works_after_a_second_application_initialisation(pg):
    config = _pg_config()
    first = create_app(config)
    first_client = first.test_client()
    _signup(first_client)
    first_client.get("/logout")

    second = create_app(config)
    second_client = second.test_client()
    response = _login(second_client)
    assert response.status_code == 200
    assert b"Incorrect email or password" not in response.data
    assert second_client.get("/dashboard").status_code == 200


def test_sqlite_placeholders_never_reach_the_postgres_driver(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)
    client.get("/logout")
    _login(client)

    for connection in pg:
        for statement in connection.executed:
            assert "?" not in statement, f"unconverted SQLite placeholder: {statement}"


def test_signup_returns_the_new_user_id_for_the_session(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    with app.app_context():
        from database.database import execute

        result = execute(
            "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("Direct", "direct@example.com", "scrypt:1$a$b", "2026-01-01", "2026-01-01"),
        )
        assert result.lastrowid is not None
        assert result.lastrowid > 0


def test_unknown_email_reproduces_the_reported_symptom(pg, caplog):
    """An account that never reached PostgreSQL fails with the password message.

    This is the exact user-visible symptom of the reported bug: the email and
    password are both correct, but the row lives in a different database.
    """
    app = create_app(_pg_config())
    client = app.test_client()

    with caplog.at_level("INFO"):
        response = _login(client, email="only-in-sqlite@example.com")

    assert b"Incorrect email or password" in response.data
    assert "no account found" in caplog.text
    assert "password mismatch" not in caplog.text


def test_wrong_password_is_logged_differently_from_unknown_email(pg, caplog):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)
    client.get("/logout")

    with caplog.at_level("INFO"):
        _login(client, password=WRONG_PASSWORD)

    assert "password mismatch" in caplog.text
    assert "no account found" not in caplog.text
    assert PASSWORD not in caplog.text
    assert WRONG_PASSWORD not in caplog.text


def test_parameterless_statements_do_not_pass_an_empty_sequence(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)

    for connection in pg:
        for params in connection.params:
            assert params is None or len(params) > 0, "empty parameter sequence sent to psycopg2"


def test_like_search_with_percent_wildcards_works_on_postgres(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)

    response = client.get("/information/?search=recycling")
    assert response.status_code == 200


def test_failed_statement_rolls_back_instead_of_aborting_the_transaction(pg):
    from database.database import execute

    app = create_app(_pg_config())
    with app.app_context():
        with pytest.raises(Exception):
            execute("INSERT INTO users (name) VALUES (?)", ("missing required columns",))
        # A PostgreSQL connection stays unusable after an error until rollback,
        # so the next query must still succeed.
        assert query_one("SELECT COUNT(*) AS n FROM users") is not None

    assert any(connection.rollbacks > 0 for connection in pg)


def test_change_password_then_login_with_new_password(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    _signup(client)
    client.post(
        "/account",
        data={"name": "Malak", "current_password": PASSWORD, "new_password": "brandnew123"},
        follow_redirects=True,
    )
    client.get("/logout")

    stale = _login(client, password=PASSWORD)
    assert b"Incorrect email or password" in stale.data
    fresh = _login(client, password="brandnew123")
    assert b"Incorrect email or password" not in fresh.data
