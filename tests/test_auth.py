from tests.conftest import signup


def test_signup_and_login(client):
    response = signup(client)
    assert response.status_code == 200
    assert b"Welcome" in response.data
    client.get("/logout", follow_redirects=True)
    bad = client.post("/login", data={"email": "student@example.com", "password": "wrongpass1"})
    assert b"Incorrect" in bad.data
    ok = client.post(
        "/login",
        data={"email": "student@example.com", "password": "password12"},
        follow_redirects=True,
    )
    assert b"Welcome" in ok.data


def test_dashboard_requires_login(client):
    response = client.get("/dashboard", follow_redirects=True)
    assert b"Sign in" in response.data


def test_user_cannot_open_other_history(client, app):
    signup(client, "one@example.com")
    with app.app_context():
        from database.database import execute, query_one

        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at)
               VALUES (1, 'full', 'full', 'completed', 'complete', '{}', '2026-01-01T00:00:00+00:00')"""
        )
        row = query_one("SELECT id FROM attempts")
    client.get("/logout")
    signup(client, "two@example.com")
    hidden = client.get(f"/history/{row['id']}")
    assert hidden.status_code == 404
