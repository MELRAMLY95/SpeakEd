from app import create_app
from config import TestConfig
from database.database import query_one


OWNER_EMAIL = "mel@speaked.owner"
OWNER_PASSWORD = "owner-pass-12"


def _private_client(tmp_path):
    class Local(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'private.db'}"
        PRIVATE_MODE = True
        OWNER_EMAIL = OWNER_EMAIL
        OWNER_PASSWORD = OWNER_PASSWORD
        OWNER_NAME = "Mel"

    return create_app(Local).test_client()


def test_private_mode_rejects_public_signup(tmp_path):
    client = _private_client(tmp_path)
    page = client.get("/signup")
    assert page.status_code == 200
    assert b"private preview" in page.data.lower()
    assert b'name="password"' not in page.data
    blocked = client.post(
        "/signup",
        data={
            "name": "Intruder",
            "email": "student@example.com",
            "password": "password12",
            "confirm": "password12",
        },
    )
    assert blocked.status_code == 403
    with client.application.app_context():
        assert query_one("SELECT id FROM users WHERE email = ?", ("student@example.com",)) is None


def test_private_mode_only_owner_can_sign_in(tmp_path):
    client = _private_client(tmp_path)
    stranger = client.post(
        "/login",
        data={"email": "student@example.com", "password": "password12"},
        follow_redirects=True,
    )
    assert b"Incorrect email or password" in stranger.data
    owner = client.post(
        "/login",
        data={"email": OWNER_EMAIL, "password": OWNER_PASSWORD},
        follow_redirects=True,
    )
    assert owner.status_code == 200
    assert b"Welcome" in owner.data


def test_private_mode_hides_create_account_links(tmp_path):
    client = _private_client(tmp_path)
    home = client.get("/")
    assert b"Create account" not in home.data
    assert b"Start practising" not in home.data
    assert b"Sign in" in home.data
    login = client.get("/login")
    assert b"Create an account" not in login.data
