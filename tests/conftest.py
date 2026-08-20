import pytest

from app import create_app
from config import TestConfig


@pytest.fixture()
def app(tmp_path):
    class Local(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'test.db'}"

    application = create_app(Local)
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def signup(client, email="student@example.com"):
    return client.post(
        "/signup",
        data={
            "name": "Malak",
            "email": email,
            "password": "password12",
            "confirm": "password12",
        },
        follow_redirects=True,
    )
