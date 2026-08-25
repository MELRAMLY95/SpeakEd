"""Tests for the startup guards that stop SpeakEd running on a database that
silently loses user data.
"""

import pytest

from config import DEV_SECRET_KEY, Config, TestConfig, validate_runtime_config
from database.database import _sqlite_path, engine_kind


def _config(**overrides):
    base = {
        "IS_PRODUCTION": True,
        "DATABASE_URL": "postgresql://u:p@host/db",
        "SECRET_KEY": "a-real-stable-production-secret",
    }
    base.update(overrides)
    return base


def test_valid_production_config_is_accepted():
    validate_runtime_config(_config())


def test_production_rejects_sqlite():
    with pytest.raises(RuntimeError, match="requires a PostgreSQL DATABASE_URL"):
        validate_runtime_config(_config(DATABASE_URL="sqlite:///instance/speaked.db"))


def test_production_rejects_empty_database_url():
    with pytest.raises(RuntimeError, match="requires a PostgreSQL DATABASE_URL"):
        validate_runtime_config(_config(DATABASE_URL=""))


def test_production_rejects_the_development_secret_key():
    with pytest.raises(RuntimeError, match="stable SECRET_KEY"):
        validate_runtime_config(_config(SECRET_KEY=DEV_SECRET_KEY))


def test_production_rejects_missing_secret_key():
    with pytest.raises(RuntimeError, match="stable SECRET_KEY"):
        validate_runtime_config(_config(SECRET_KEY=""))


def test_postgres_url_variants_are_accepted_in_production():
    validate_runtime_config(_config(DATABASE_URL="postgres://u:p@host/db"))
    validate_runtime_config(_config(DATABASE_URL="postgresql://u:p@host/db"))


def test_local_development_is_not_restricted():
    """SQLite and the dev secret stay usable locally."""
    validate_runtime_config(
        {"IS_PRODUCTION": False, "DATABASE_URL": "sqlite:///instance/speaked.db", "SECRET_KEY": DEV_SECRET_KEY}
    )


def test_app_refuses_to_start_in_production_without_postgres():
    from app import create_app

    class Broken(TestConfig):
        IS_PRODUCTION = True
        DATABASE_URL = "sqlite:///instance/speaked.db"
        SECRET_KEY = "stable-secret"

    with pytest.raises(RuntimeError, match="requires a PostgreSQL DATABASE_URL"):
        create_app(Broken)


def test_in_memory_sqlite_is_rejected_loudly():
    """Each request opens a new connection, so ':memory:' silently loses data."""
    for url in ("sqlite:///:memory:", "sqlite://:memory:", ":memory:"):
        with pytest.raises(RuntimeError, match="in-memory SQLite"):
            _sqlite_path(url)


def test_test_config_does_not_use_in_memory_sqlite():
    assert ":memory:" not in TestConfig.DATABASE_URL
    assert engine_kind(TestConfig.DATABASE_URL) == "sqlite"


def test_database_url_env_var_selects_the_engine(monkeypatch):
    import importlib

    import config as config_module

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    try:
        reloaded = importlib.reload(config_module)
        assert reloaded.Config.DATABASE_URL == "postgresql://u:p@host/db"

        monkeypatch.setenv("DATABASE_URL", "   ")
        reloaded = importlib.reload(config_module)
        assert reloaded.Config.DATABASE_URL == reloaded.LOCAL_SQLITE_URL, "blank URL should fall back locally"
    finally:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        importlib.reload(config_module)


def test_session_cookie_is_secure_in_production():
    assert Config.SESSION_COOKIE_HTTPONLY is True
    assert Config.SESSION_COOKIE_SAMESITE == "Lax"
    assert TestConfig.SESSION_COOKIE_SECURE is False
