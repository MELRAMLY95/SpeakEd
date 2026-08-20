from tests.conftest import signup


def test_progress_page_empty_then_history(client):
    signup(client)
    page = client.get("/progress")
    assert page.status_code == 200
    history = client.get("/history")
    assert history.status_code == 200
