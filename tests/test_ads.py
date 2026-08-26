"""Non-intrusive advertising slots: placement, premium gating, and isolation."""

from pathlib import Path

import pytest

from ads import is_live_publisher, path_forbids_ads
from subscriptions import is_premium
from app import create_app
from config import TestConfig
from tests.conftest import signup
from tests.fake_ai import install_fake

ROOT = Path(__file__).resolve().parent.parent
ADS_CSS = (ROOT / "static" / "css" / "ads.css").read_text(encoding="utf-8")


class AdsConfig(TestConfig):
    ADS_ENABLED = True
    ADS_CONSENT_REQUIRED = False
    ADS_TEST_MODE = True
    AD_CLIENT_ID = "ca-pub-XXXXXXXXXXXXXXXX"
    AD_SLOT_HOME = "slot-home"
    AD_SLOT_DASHBOARD = "slot-dashboard"
    AD_SLOT_INFORMATION = "slot-info"
    AD_SLOT_PRIVACY = "slot-privacy"


@pytest.fixture()
def ads_app(tmp_path):
    class Local(AdsConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'ads.db'}"

    return create_app(Local)


@pytest.fixture()
def ads_client(ads_app):
    return ads_app.test_client()


@pytest.fixture()
def live_ads_app(tmp_path):
    class Local(AdsConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'ads-live.db'}"
        AD_CLIENT_ID = "ca-pub-1234567890123456"
        ADS_TEST_MODE = True

    return create_app(Local)


@pytest.fixture()
def live_ads_client(live_ads_app):
    return live_ads_app.test_client()


def _slot(html: bytes, name: str) -> str:
    text = html.decode()
    marker = f'data-ad-slot="{name}"'
    start = text.find(marker)
    assert start != -1, f"missing ad slot {name}"
    aside_start = text.rfind("<aside", 0, start)
    aside_end = text.find("</aside>", start)
    assert aside_start != -1 and aside_end != -1
    return text[aside_start : aside_end + len("</aside>")]


def test_placeholder_publisher_id_is_not_live():
    assert is_live_publisher("ca-pub-XXXXXXXXXXXXXXXX") is False
    assert is_live_publisher("") is False
    assert is_live_publisher("ca-pub-1234567890123456") is True


def test_path_forbids_exam_and_practice():
    assert path_forbids_ads("/exam/1") is True
    assert path_forbids_ads("/practice") is True
    assert path_forbids_ads("/practice/roleplay") is True
    assert path_forbids_ads("/evaluation") is True
    assert path_forbids_ads("/progress") is True
    assert path_forbids_ads("/") is False
    assert path_forbids_ads("/dashboard") is False


def test_premium_status_ignores_request_shaped_objects():
    assert is_premium(None) is False
    assert is_premium({"is_premium": 1}) is False
    assert is_premium({"id": "not-a-number", "is_premium": 1}) is False


def test_free_user_sees_approved_ad_slots(ads_client):
    home = ads_client.get("/")
    assert home.status_code == 200
    assert b'data-ad-slot="home"' in home.data
    assert b"Advertisement" in home.data
    assert b"googlesyndication.com" not in home.data

    privacy = ads_client.get("/privacy")
    assert privacy.status_code == 200
    assert b'data-ad-slot="privacy"' in privacy.data

    signup(ads_client)
    dashboard = ads_client.get("/dashboard")
    assert dashboard.status_code == 200
    assert b'data-ad-slot="dashboard"' in dashboard.data

    information = ads_client.get("/information/")
    assert information.status_code == 200
    assert b'data-ad-slot="information"' in information.data

    home_html = home.data.decode()
    assert home_html.index("hero-actions") < home_html.index("ad-slot")
    assert home.data.count(b"class=\"ad-slot\"") == 1


def test_premium_user_does_not_see_ads(ads_app, ads_client):
    signup(ads_client)
    with ads_app.app_context():
        from database.database import query_one
        from subscriptions import activate_test_subscription

        user = query_one("SELECT id FROM users WHERE email = ?", ("student@example.com",))
        activate_test_subscription(user["id"])

    dashboard = ads_client.get("/dashboard")
    assert dashboard.status_code == 200
    assert b"Welcome" in dashboard.data
    assert b"ad-slot" not in dashboard.data
    assert ads_client.get("/").status_code == 200
    assert b"ad-slot" not in ads_client.get("/").data
    assert b"ad-slot" not in ads_client.get("/privacy").data
    assert b"ad-slot" not in ads_client.get("/information/").data


def test_ads_never_appear_during_an_active_exam(ads_client, monkeypatch):
    install_fake(monkeypatch)
    signup(ads_client)
    room = ads_client.post(
        "/exam/start",
        data={"exam_type": "full", "mode": "full", "topic_title": "Plastic pollution"},
        follow_redirects=True,
    )
    assert room.status_code == 200
    assert b"ad-slot" not in room.data
    assert b"googlesyndication.com" not in room.data
    csp = room.headers.get("Content-Security-Policy") or ""
    assert "googlesyndication" not in csp

    begun = ads_client.post("/exam/1/begin", follow_redirects=True)
    assert begun.status_code == 200
    assert b"ad-slot" not in begun.data
    assert b"data-mic" in begun.data


def test_ads_never_appear_during_practice(ads_client):
    signup(ads_client)
    for path in (
        "/practice",
        "/practice/roleplay",
        "/practice/topic-talk",
        "/practice/picture",
        "/exam",
    ):
        response = ads_client.get(path)
        assert response.status_code == 200, path
        assert b"ad-slot" not in response.data, path
        assert b"googlesyndication.com" not in response.data, path


def test_ads_do_not_cover_buttons_or_microphone_controls():
    assert "position: fixed" not in ADS_CSS
    assert "position:fixed" not in ADS_CSS
    assert "position: sticky" not in ADS_CSS
    compact = ADS_CSS.replace(" ", "")
    assert "position:absolute" not in compact
    assert "z-index:0" in compact
    assert "max-width:100%" in compact


def test_ad_provider_failure_does_not_break_the_page(live_ads_client):
    response = live_ads_client.get("/")
    assert response.status_code == 200
    assert b"A virtual speaking examiner" in response.data
    assert b"Start practising" in response.data
    assert b'data-ad-slot="home"' in response.data
    assert b"async" in response.data
    assert b"Something went wrong" not in response.data


def test_disabling_ads_removes_slots(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"ad-slot" not in response.data
    assert b"googlesyndication.com" not in response.data
    signup(client)
    assert b"ad-slot" not in client.get("/dashboard").data
    assert b"ad-slot" not in client.get("/privacy").data


def test_browser_cannot_fake_premium_to_hide_ads(ads_client):
    signup(ads_client)
    spoofed = ads_client.get(
        "/dashboard?isPremium=true&premium=1&ads=0",
        headers={"X-Premium": "true"},
    )
    assert spoofed.status_code == 200
    assert b'data-ad-slot="dashboard"' in spoofed.data

    ads_client.set_cookie("isPremium", "true")
    ads_client.set_cookie("premium", "1")
    with_cookies = ads_client.get("/dashboard")
    assert b'data-ad-slot="dashboard"' in with_cookies.data


def test_mobile_ad_css_keeps_layout_usable():
    assert "@media (max-width: 640px)" in ADS_CSS
    assert "width: 100%" in ADS_CSS
    assert "max-height: 90px" in ADS_CSS or "max-height: 100px" in ADS_CSS


def test_ad_slot_does_not_include_student_information(ads_client):
    signup(ads_client, "private-student@example.com")
    dashboard = ads_client.get("/dashboard")
    slot = _slot(dashboard.data, "dashboard")
    assert "private-student@example.com" not in slot
    assert "password12" not in slot
    assert "is_premium" not in slot
    page = dashboard.data.decode()
    assert "private-student@example.com" not in page


def test_results_and_sensitive_pages_have_no_ads(ads_client, monkeypatch):
    install_fake(monkeypatch)
    signup(ads_client)
    ads_client.post(
        "/exam/start",
        data={"exam_type": "full", "mode": "full", "topic_title": "Plastic pollution"},
        follow_redirects=True,
    )
    results = ads_client.get("/exam/1/results", follow_redirects=True)
    assert results.status_code == 200
    assert b"ad-slot" not in results.data

    for path in ("/evaluation", "/progress", "/history", "/account", "/information/new"):
        response = ads_client.get(path)
        assert response.status_code == 200, path
        assert b"ad-slot" not in response.data, path

    ads_client.post("/logout", follow_redirects=True)
    for path in ("/login", "/signup", "/forgot-password"):
        response = ads_client.get(path)
        assert response.status_code == 200, path
        assert b"ad-slot" not in response.data, path


def test_live_ads_widen_csp_only_on_approved_pages(live_ads_client, monkeypatch):
    home = live_ads_client.get("/")
    csp = home.headers.get("Content-Security-Policy") or ""
    assert "pagead2.googlesyndication.com" in csp
    assert "script-src 'self'" in csp

    signup(live_ads_client)
    install_fake(monkeypatch)
    room = live_ads_client.post(
        "/exam/start",
        data={"exam_type": "full", "mode": "full", "topic_title": "Plastic pollution"},
        follow_redirects=True,
    )
    exam_csp = room.headers.get("Content-Security-Policy") or ""
    assert "googlesyndication" not in exam_csp
    assert b"ad-slot" not in room.data


def test_consent_deny_hides_ads(tmp_path):
    class Local(AdsConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'ads-consent.db'}"
        ADS_CONSENT_REQUIRED = True

    client = create_app(Local).test_client()
    home = client.get("/")
    assert b"ad-slot" in home.data
    assert b"Allow" in home.data
    assert b"googlesyndication.com" not in home.data

    denied = client.post("/ads/consent", data={"choice": "deny", "next": "/"}, follow_redirects=True)
    assert denied.status_code == 200
    assert b"ad-slot" not in denied.data


def test_legacy_users_table_gains_is_premium_column(tmp_path):
    import sqlite3

    path = tmp_path / "legacy-users.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE users ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, "
        "password_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    class Local(AdsConfig):
        DATABASE_URL = f"sqlite:///{path}"

    app = create_app(Local)
    with app.app_context():
        from database.database import get_db

        columns = {row[1] for row in get_db().execute("PRAGMA table_info(users)")}
    assert "is_premium" in columns
