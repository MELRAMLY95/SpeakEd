import io
import json

from tests.conftest import signup
from tests.fake_ai import FakeAIProvider, install_fake


def test_full_exam_results_show_total_and_feedback(client, app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(supports_images_flag=False))
    signup(client)
    start = client.post(
        "/exam/start",
        data={"exam_type": "full", "mode": "full", "topic_title": "Plastic pollution"},
        follow_redirects=True,
    )
    assert start.status_code == 200
    begin = client.post("/exam/1/begin", follow_redirects=True)
    assert begin.status_code == 200
    for _ in range(30):
        response = client.post(
            "/exam/1/turn",
            json={
                "transcript": "I usually go once a month because I enjoy action films with my friends, for example last Saturday.",
                "metrics": {"duration_ms": 8000, "word_count": 20},
            },
        )
        data = response.get_json()
        if data.get("redirect"):
            results = client.get(data["redirect"])
            assert results.status_code == 200
            html = results.data.decode()
            assert "could not complete marking" not in html.lower()
            assert "/50" in html
            assert "Estimated grade" in html
            assert "Not an official Pearson Edexcel certificate grade" in html
            assert "What went well" in html
            assert "Recommended next step" in html
            with app.app_context():
                from database.database import query_one
                attempt = query_one("SELECT status, total_score FROM attempts WHERE id = 1")
                feedback = query_one("SELECT strengths_json FROM feedback WHERE attempt_id = 1")
            assert attempt["status"] == "completed"
            assert attempt["total_score"] is not None
            assert feedback is not None
            return
    raise AssertionError("exam did not complete")


def test_full_exam_flow_text_turns(client, monkeypatch):
    install_fake(monkeypatch)
    signup(client)
    start = client.post(
        "/exam/start",
        data={"exam_type": "full", "mode": "full", "topic_title": "Plastic pollution"},
        follow_redirects=True,
    )
    assert start.status_code == 200
    assert b"Role play" in start.data or b"prepare" in start.data.lower() or b"Preparation" in start.data
    begin = client.post("/exam/1/begin", follow_redirects=True)
    assert begin.status_code == 200
    for _ in range(30):
        response = client.post(
            "/exam/1/turn",
            json={
                "transcript": "I usually go once a month because I enjoy action films with my friends, for example last Saturday.",
                "metrics": {"duration_ms": 8000, "word_count": 20},
            },
        )
        data = response.get_json()
        if data.get("redirect"):
            results = client.get(data["redirect"])
            assert results.status_code == 200
            assert b"practice result" in results.data.lower() or b"Practice result" in results.data or b"4XES2" in results.data
            assert b"could not complete marking" not in results.data.lower()
            assert b"/50" in results.data
            return
    raise AssertionError("exam did not complete")


def test_full_exam_preparation_shows_local_picture(client, app):
    signup(client)
    start = client.post(
        "/exam/start",
        data={"exam_type": "full", "mode": "full", "topic_title": "Plastic pollution"},
        follow_redirects=True,
    )
    assert start.status_code == 200
    html = start.data.decode()
    assert "Picture stimulus" in html
    assert "/static/images/pictures/" in html
    assert ".svg" in html
    assert "picsum.photos" not in html
    with app.app_context():
        from database.database import query_one
        row = query_one("SELECT payload_json FROM attempts WHERE id = 1")
        payload = json.loads(row["payload_json"])
        image = payload["picture"]["image"]
    assert image.endswith(".svg")
    assert image in html


def test_picture_id_is_honoured(client, app):
    signup(client)
    client.post(
        "/practice/start",
        data={"section": "picture", "picture_id": "pt02"},
        follow_redirects=True,
    )
    with app.app_context():
        from database.database import query_one
        row = query_one("SELECT payload_json FROM attempts WHERE id = 1")
        payload = json.loads(row["payload_json"])
        assert payload["picture"]["id"] == "pt02"
        assert payload["picture"]["image"].endswith(".svg")


def test_practice_picture_picker_shows_local_images(client):
    signup(client)
    page = client.get("/practice/picture")
    assert page.status_code == 200
    html = page.data.decode()
    assert "picsum.photos" not in html
    assert "/static/images/pictures/homes.svg" in html
    assert "/static/images/pictures/tourism.svg" in html
    svg = client.get("/static/images/pictures/homes.svg")
    assert svg.status_code == 200
    assert b"<svg" in svg.data


def test_empty_turn_is_rejected(client, monkeypatch):
    install_fake(monkeypatch)
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    response = client.post("/exam/1/turn", json={"transcript": "", "metrics": {}})
    assert response.status_code == 400
    data = response.get_json()
    assert data["retry"] is True
    assert data["code"] == "empty_response"


def test_audio_upload_is_accepted(client, app, monkeypatch):
    install_fake(monkeypatch)
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    audio = (io.BytesIO(b"\x00" * 400), "turn.webm", "audio/webm")
    response = client.post(
        "/exam/1/turn",
        data={
            "transcript": "I go to the cinema about twice a month with my sister.",
            "metrics": json.dumps({"duration_ms": 2000, "word_count": 12}),
            "audio": audio,
        },
    )
    assert response.status_code == 200
    data = response.get_json()
    assert "error" not in data or not data.get("error")
    with app.app_context():
        from database.database import query_one
        row = query_one("SELECT speech_metrics_json, text FROM transcripts WHERE attempt_id = 1")
        metrics = json.loads(row["speech_metrics_json"])
        assert metrics.get("audio_received") is True
        assert "cinema" in row["text"]


def test_invalid_audio_rejected(client, monkeypatch):
    install_fake(monkeypatch)
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    audio = (io.BytesIO(b"not-audio"), "turn.exe", "application/octet-stream")
    response = client.post(
        "/exam/1/turn",
        data={
            "transcript": "Hello",
            "metrics": json.dumps({"duration_ms": 2000}),
            "audio": audio,
        },
    )
    assert response.status_code == 400
    assert response.get_json()["retry"] is True


def _assert_turn_not_saved(app):
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT COUNT(*) AS n FROM transcripts WHERE attempt_id = 1")
        assert row["n"] == 0
        payload = json.loads(query_one("SELECT payload_json FROM attempts WHERE id = 1")["payload_json"])
        student = [t for t in payload.get("turns", []) if t.get("speaker") == "student"]
        assert student == []
        attempt = query_one("SELECT stage, status FROM attempts WHERE id = 1")
        assert attempt["stage"] == "roleplay"
        assert attempt["status"] == "in_progress"


def test_failed_transcription_does_not_save_empty_answer(client, app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(supports_audio_flag=True, transcribe_fail=True))
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    audio = (io.BytesIO(b"\x00" * 400), "turn.webm", "audio/webm")
    response = client.post(
        "/exam/1/turn",
        data={
            "transcript": "",
            "metrics": json.dumps({"duration_ms": 2000, "word_count": 0}),
            "audio": audio,
        },
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "transcription_unavailable"
    assert data["retry"] is True
    _assert_turn_not_saved(app)


def test_empty_transcription_does_not_save_empty_answer(client, app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(supports_audio_flag=True, transcribe_empty=True))
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    audio = (io.BytesIO(b"\x00" * 400), "turn.webm", "audio/webm")
    response = client.post(
        "/exam/1/turn",
        data={
            "transcript": "   ",
            "metrics": json.dumps({"duration_ms": 2000, "word_count": 0}),
            "audio": audio,
        },
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "transcription_unavailable"
    _assert_turn_not_saved(app)


def test_successful_transcription_saves_gemini_text(client, app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(supports_audio_flag=True))
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    audio = (io.BytesIO(b"\x00" * 400), "turn.webm", "audio/webm")
    response = client.post(
        "/exam/1/turn",
        data={
            "transcript": "",
            "metrics": json.dumps({"duration_ms": 2000, "word_count": 0}),
            "audio": audio,
        },
    )
    assert response.status_code == 200
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT text FROM transcripts WHERE attempt_id = 1")
        assert "football" in row["text"]
        attempt = query_one("SELECT stage FROM attempts WHERE id = 1")
        assert attempt["stage"] == "roleplay"


def test_marking_unavailable_without_ai_on_finish(client):
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    for _ in range(8):
        response = client.post(
            "/exam/1/turn",
            json={
                "transcript": "I go to the cinema about twice a month with my sister.",
                "metrics": {"duration_ms": 4000, "word_count": 12},
            },
        )
        data = response.get_json()
        if data.get("redirect"):
            page = client.get(data["redirect"])
            assert page.status_code == 200
            assert b"could not complete marking" in page.data.lower() or b"Retry marking" in page.data
            return
    raise AssertionError("roleplay did not complete")


def _finish_roleplay(client) -> str:
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    for _ in range(8):
        response = client.post(
            "/exam/1/turn",
            json={
                "transcript": "I go to the cinema about twice a month with my sister because we enjoy action films.",
                "metrics": {"duration_ms": 4000, "word_count": 18},
            },
        )
        data = response.get_json()
        if data.get("redirect"):
            return data["redirect"]
    raise AssertionError("roleplay did not complete")


def test_scores_are_saved_when_feedback_ai_fails(client, app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(fail_feedback=True))
    signup(client)
    redirect_url = _finish_roleplay(client)
    page = client.get(redirect_url)
    assert page.status_code == 200
    assert b"could not complete marking" not in page.data.lower()
    assert b"No score was recorded" not in page.data
    assert b"/10" in page.data
    assert b"Estimated grade" in page.data
    assert b"Not an official Pearson Edexcel certificate grade" in page.data
    with app.app_context():
        from database.database import query_one

        attempt = query_one("SELECT status, roleplay_score, total_score FROM attempts WHERE id = 1")
        assert attempt["status"] == "completed"
        assert attempt["roleplay_score"] is not None
        assert attempt["roleplay_score"] >= 0
        feedback = query_one("SELECT strengths_json FROM feedback WHERE attempt_id = 1")
        assert feedback is not None
        assert json.loads(feedback["strengths_json"])


def test_results_restore_scores_cleared_after_marking(client, app, monkeypatch):
    install_fake(monkeypatch)
    signup(client)
    redirect_url = _finish_roleplay(client)
    with app.app_context():
        from database.database import execute, query_one

        execute(
            """UPDATE attempts SET status='marking_unavailable', roleplay_score=NULL, topic_talk_score=NULL,
               picture_score=NULL, total_score=NULL, strongest_area=NULL, weakest_area=NULL WHERE id=1"""
        )
        cleared = query_one("SELECT roleplay_score, status FROM attempts WHERE id = 1")
        assert cleared["roleplay_score"] is None
        assert cleared["status"] == "marking_unavailable"
    page = client.get(redirect_url)
    assert page.status_code == 200
    assert b"could not complete marking" not in page.data.lower()
    assert b"/10" in page.data
    with app.app_context():
        from database.database import query_one

        restored = query_one("SELECT status, roleplay_score, total_score FROM attempts WHERE id = 1")
        assert restored["status"] == "completed"
        assert restored["roleplay_score"] is not None

