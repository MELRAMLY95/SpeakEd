import json
from unittest.mock import patch

from ai.local_ai import GeminiProvider
from ai.marking import MarkingUnavailable, load_scheme, mark_extended
from ai.picture_media import load_picture_media, svg_to_png
from tests.fake_ai import FakeAIProvider


def test_homes_svg_loads_as_nonempty_png():
    data, mime = load_picture_media("/static/images/pictures/homes.svg")
    assert mime == "image/png"
    assert data.startswith(b"\x89PNG")
    assert len(data) > 100


def test_missing_picture_fails_safely():
    try:
        load_picture_media("/static/images/pictures/does-not-exist.svg")
        raised = False
    except Exception:
        raised = True
    assert raised


def test_picture_path_traversal_is_rejected():
    from ai.picture_media import PictureLoadError

    for ref in (
        "/static/../.env",
        "/static/images/pictures/../../config.py",
        "/etc/passwd",
        "http://127.0.0.1/secret.png",
        "https://localhost/picture.png",
    ):
        try:
            load_picture_media(ref)
            ok = True
        except PictureLoadError:
            ok = False
        assert ok is False


def test_marking_attaches_picture_bytes():
    scheme = load_scheme()
    ai = FakeAIProvider()
    result = mark_extended(
        "picture",
        [{"text": "I can see a house with a red roof and a garden.", "question": "Describe the photo."}],
        scheme,
        ai=ai,
        context={
            "picture_title": "Homes and Living Spaces",
            "picture_intro": "Look at the picture.",
            "picture_image": "/static/images/pictures/homes.svg",
        },
    )
    assert result["image_assessed"] is True
    assert ai.image_calls >= 1
    assert ai.last_image_mime == "image/png"
    assert ai.last_image_bytes > 0
    assert "supplied picture" in ai.prompts[0]
    assert result["score"] >= 0


def test_marking_fails_safely_when_picture_missing():
    scheme = load_scheme()
    ai = FakeAIProvider()
    try:
        mark_extended(
            "picture",
            [{"text": "I can see a house.", "question": "Describe the photo."}],
            scheme,
            ai=ai,
            context={"picture_image": "/static/images/pictures/missing.svg"},
        )
        ok = False
    except MarkingUnavailable as exc:
        ok = True
        assert "could not be loaded" in str(exc).lower()
    assert ok
    assert ai.image_calls == 0


def test_gemini_parts_include_png_inline_data():
    png = svg_to_png(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10" fill="#00ff00"/></svg>'
    )
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["url"] = request.full_url

        class Resp:
            status = 200

            def read(self):
                return b'{"candidates":[{"content":{"parts":[{"text":"{\\"ok\\":true}"}]}}]}'

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    provider = GeminiProvider("test-key", "gemini-3.5-flash-lite")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.generate_json_with_media("assess the picture", [(png, "image/png")])
    parts = captured["body"]["contents"][0]["parts"]
    assert parts[0]["text"] == "assess the picture"
    assert parts[1]["inline_data"]["mime_type"] == "image/png"
    assert len(parts[1]["inline_data"]["data"]) > 50
    assert "test-key" not in json.dumps(captured["body"])
