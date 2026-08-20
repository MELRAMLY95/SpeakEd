from tests.conftest import signup


def test_full_exam_flow_text_turns(client):
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
    for _ in range(20):
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
            return
    raise AssertionError("exam did not complete")
