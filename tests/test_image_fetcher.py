import json
from unittest.mock import patch

from ai.picture_media import PictureLoadError, load_picture_media
from services.image_fetcher import GETTY_IDS, ImageFetcher, attach_picture_media, fetch_getty_oembed


def test_picture_cards_cover_4xes2_chapters():
    from ai.prompts import PromptBank

    bank = PromptBank()
    keys = {card.get("topic_key") for card in bank.picture["cards"]}
    for card in bank.picture["cards"]:
        assert str(card.get("getty_id") or "").isdigit()
    for required in (
        "friends_family",
        "myself",
        "hobbies",
        "education",
        "equality",
        "environment",
        "tourism",
        "media",
    ):
        assert required in keys


def test_local_source_uses_svg(app):
    with app.app_context():
        card = attach_picture_media({"id": "pt06", "title": "Friends and Family", "topic_key": "friends_family", "getty_id": "1400784606", "image": "/static/images/pictures/homes.svg"})
        assert card["image"].endswith(".svg")
        assert "gettyimages" not in card["image"]


def test_getty_oembed_uses_public_asset_url(tmp_path):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url

        class Resp:
            def read(self):
                return json.dumps(
                    {
                        "thumbnail_url": "https://media.gettyimages.com/id/1400784606/photo/friends.jpg?s=170x170",
                        "photographer": "Example Photographer",
                    }
                ).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    fetcher = ImageFetcher(cache_dir=tmp_path)
    with patch("services.image_fetcher._picture_source", return_value="getty"):
        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            url = fetcher.get_image_for_topic("friends_family", force_refresh=True, asset_id="1400784606")
    assert url.startswith("https://media.gettyimages.com/")
    assert "gty.im/1400784606" in captured["url"]
    assert "Example Photographer" in fetcher.credit_for_topic("friends_family", "1400784606")


def test_fetch_getty_oembed_rejects_non_getty_hosts():
    def fake_urlopen(request, timeout=None):
        class Resp:
            def read(self):
                return json.dumps({"thumbnail_url": "https://evil.example/photo.jpg"}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return Resp()

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        url, _credit = fetch_getty_oembed("1400784606")
    assert url == ""


def test_themes_cover_user_chapters():
    for key in ("friends_family", "myself", "hobbies", "education", "equality", "environment", "tourism", "media"):
        assert GETTY_IDS[key].isdigit()


def test_disallowed_picture_host_is_rejected():
    try:
        load_picture_media("https://evil.example/photo.jpg")
        ok = True
    except PictureLoadError:
        ok = False
    assert ok is False
