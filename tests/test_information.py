from routes.information import _plain_text
from tests.conftest import signup
from tests.fake_ai import FakeAIProvider, install_fake


def test_plain_text_keeps_bullet_lists():
    raw = """# Plastic pollution

**Key Facts**
* It harms marine animals
* Bottles take centuries to break down

See [this note](https://example.com).
"""
    cleaned = _plain_text(raw)
    assert "#" not in cleaned
    assert "**" not in cleaned
    assert "https://example.com" not in cleaned
    assert "It harms marine animals" in cleaned
    assert "Bottles take centuries to break down" in cleaned
    assert cleaned.count("•") >= 2


def test_information_home_requires_login(client):
    response = client.get("/information/", follow_redirects=False)
    assert response.status_code in {302, 303}


def test_gather_information_with_ai(client, app, monkeypatch):
    install_fake(monkeypatch)
    signup(client)
    page = client.get("/information/new")
    assert page.status_code == 200
    assert b"Gather New Information" in page.data
    assert b"page-header" in page.data

    response = client.post(
        "/information/new",
        data={"topic": "Plastic pollution"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Plastic pollution" in response.data
    assert b"Information gathered successfully" in response.data
    assert b"IGCSE ESL speaking" in response.data
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT topic, information FROM gathered_info WHERE id = 1")
        assert row["topic"] == "Plastic pollution"
        assert "bottle deposit" in row["information"].lower()


def test_gather_information_shows_ai_error(client, app, monkeypatch):
    class Boom:
        name = "gemini"

        def is_available(self):
            return True

        def generate_text(self, *args, **kwargs):
            raise RuntimeError("Gemini API error 429: RESOURCE_EXHAUSTED quota")

    monkeypatch.setattr("routes.information.get_ai", lambda: Boom())
    signup(client)
    response = client.post(
        "/information/new",
        data={"topic": "Recycling"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Could not generate information" in response.data
    assert b"429" in response.data
    with app.app_context():
        from database.database import query_one

        assert query_one("SELECT id FROM gathered_info") is None


def test_gather_information_without_ai_creates_template(client, app):
    signup(client)
    response = client.post(
        "/information/new",
        data={"topic": "Climate change"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Climate change" in response.data
    assert b"template" in response.data.lower()
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT information FROM gathered_info WHERE id = 1")
        assert "[Add key facts about Climate change here]" in row["information"]


def test_view_edit_search_and_delete(client, monkeypatch):
    install_fake(monkeypatch)
    signup(client)
    client.post("/information/new", data={"topic": "Recycling"}, follow_redirects=True)

    listed = client.get("/information/")
    assert b"Recycling" in listed.data
    assert b"Created:" in listed.data

    search = client.get("/information/?search=recycl")
    assert b"Recycling" in search.data

    view = client.get("/information/1")
    assert view.status_code == 200
    assert b"<br>" not in view.data
    assert b"IGCSE ESL speaking" in view.data

    edit = client.post(
        "/information/1/edit",
        data={"topic": "Recycling at home", "information": "Use a bottle bank every week."},
        follow_redirects=True,
    )
    assert b"Recycling at home" in edit.data
    assert b"bottle bank" in edit.data

    deleted = client.post("/information/1/delete", follow_redirects=True)
    assert deleted.status_code == 200
    assert b"No information gathered yet" in deleted.data
