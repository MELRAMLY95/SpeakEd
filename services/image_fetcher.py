"""Load Task 3 photographs from Getty Images' public oEmbed endpoint.

Each topic has several Getty asset ids. SpeakEd picks a different id each time
and asks https://embed.gettyimages.com/oembed?url=http://gty.im/{id}.
Tests keep local SVG cards (PICTURE_SOURCE=local).
"""

from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from pathlib import Path

from ai.picture_media import browser_picture_src, local_svg_for_topic, topic_key_from_card

GETTY_OEMBED = "https://embed.gettyimages.com/oembed?url=http://gty.im/{asset_id}"
GETTY_CREDIT = "Photograph from Getty Images"

# Several public Getty Images asset ids per 4XES2 topic so the photo rotates.
GETTY_IDS = {
    "homes": ["1435656847", "1651033002", "1416913509", "2209732703"],
    "tourism": ["2138928345", "1824595205", "1488646953"],
    "education": ["2169899800", "2209544218", "2203120233", "2206652191", "1324059362"],
    "school": ["2169899800", "2209544218", "2203120233", "2206652191", "1324059362"],
    "work": ["2193568098", "2197230968", "2161803902"],
    "myself": ["2189077006", "1363289792", "1313823475"],
    "friends_family": ["1400784606", "948544134", "2206183844", "2158329332"],
    "hobbies": ["1561143023", "1561142466", "1452860606"],
    "equality": ["1864423396", "2200866856", "2214245446"],
    "environment": ["2150674855", "1382387513", "1483622172"],
    "media": ["948544134", "1416913509", "1504711434"],
    "technology": ["2178258003", "1023919092", "1531297484"],
    "sport": ["1455481853", "1517649763", "1579952363"],
    "health": ["888273280", "1840349194", "1967042640"],
    "food": ["1813251478", "1414235077", "1504674900"],
}

_LAST_ASSET: dict[str, str] = {}


class ImageFetcher:
    def __init__(self, cache_dir: Path | None = None):
        self.cache_dir = cache_dir or Path(__file__).resolve().parent.parent / "static" / "images" / "pictures"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "image_cache.json"
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        if self.cache_file.exists():
            try:
                with self.cache_file.open(encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError, TypeError):
                return {}
        return {}

    def _save_cache(self) -> None:
        try:
            with self.cache_file.open("w", encoding="utf-8") as handle:
                json.dump(self.cache, handle, indent=2)
        except OSError:
            pass

    def _entry(self, key: str) -> dict[str, str]:
        raw = self.cache.get(key)
        if isinstance(raw, dict) and str(raw.get("url") or "").startswith("https://media.gettyimages.com"):
            return {"url": str(raw["url"]), "credit": str(raw.get("credit") or GETTY_CREDIT)}
        return {}

    def get_random_image_url(self, topic: str, width: int = 1920, height: int = 1080) -> str:
        return self.get_image_for_topic(topic, force_refresh=True)

    def get_cached_image_url(self, topic: str) -> str | None:
        return self._entry(_cache_key(topic)).get("url") or None

    def cache_image_url(self, topic: str, url: str, credit: str = GETTY_CREDIT) -> None:
        self.cache[_cache_key(topic)] = {"url": url, "credit": credit}
        self._save_cache()

    def refresh_all_images(self) -> dict[str, str]:
        new_urls = {}
        for topic in GETTY_IDS:
            if topic == "school":
                continue
            new_urls[topic] = self.get_image_for_topic(topic, force_refresh=True)
        return new_urls

    def get_image_for_topic(self, topic: str, force_refresh: bool = False, asset_id: str = "") -> str:
        topic = (topic or "").strip() or "homes"
        asset_id = str(asset_id or pick_asset_id(topic))
        if _picture_source() == "local":
            return local_svg_for_topic(topic)
        key = _cache_key(topic, asset_id)
        if not force_refresh:
            cached = self._entry(key)
            if cached.get("url"):
                return cached["url"]
        url, credit = fetch_getty_oembed(asset_id)
        if url:
            self.cache[key] = {"url": url, "credit": credit}
            self._save_cache()
            return url
        cached = self._entry(key)
        return cached.get("url") or ""

    def credit_for_topic(self, topic: str, asset_id: str = "") -> str:
        if _picture_source() == "local":
            return ""
        return self._entry(_cache_key(topic, asset_id)).get("credit") or GETTY_CREDIT


def ids_for_topic(topic: str, card: dict | None = None) -> list[str]:
    extra: list[str] = []
    if card:
        raw = card.get("getty_ids") or card.get("getty_id")
        if isinstance(raw, list):
            extra = [str(item) for item in raw if str(item).isdigit()]
        elif str(raw or "").isdigit():
            extra = [str(raw)]
    pool = GETTY_IDS.get(topic) or GETTY_IDS["homes"]
    if isinstance(pool, str):
        pool = [pool]
    ordered: list[str] = []
    for item in extra + [str(value) for value in pool]:
        if item.isdigit() and item not in ordered:
            ordered.append(item)
    return ordered or ["1435656847"]


def pick_asset_id(topic: str, card: dict | None = None) -> str:
    pool = ids_for_topic(topic, card)
    last = _LAST_ASSET.get(topic)
    choices = [item for item in pool if item != last] or pool
    chosen = random.choice(choices)
    _LAST_ASSET[topic] = chosen
    return chosen


def _cache_key(topic: str, asset_id: str = "") -> str:
    return str(asset_id or topic)


def _cfg(name: str, default: str = "") -> str:
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            value = current_app.config.get(name)
            if value is not None and str(value).strip() != "":
                return str(value)
    except RuntimeError:
        pass
    return os.environ.get(name, default)


def _picture_source() -> str:
    raw = (_cfg("PICTURE_SOURCE", "getty") or "getty").strip().lower()
    return "local" if raw == "local" else "getty"


def fetch_getty_oembed(asset_id: str) -> tuple[str, str]:
    asset_id = str(asset_id or "").strip()
    if not asset_id.isdigit():
        return "", GETTY_CREDIT
    request = urllib.request.Request(
        GETTY_OEMBED.format(asset_id=asset_id),
        headers={"User-Agent": "SpeakEd-pictures", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, OSError):
        return "", GETTY_CREDIT
    if not isinstance(data, dict):
        return "", GETTY_CREDIT
    url = str(data.get("thumbnail_url") or "").strip()
    if not url.startswith("https://media.gettyimages.com"):
        return "", GETTY_CREDIT
    photographer = str(data.get("photographer") or "").strip()
    credit = f"Photograph: {photographer} / Getty Images" if photographer else GETTY_CREDIT
    return url, credit


_image_fetcher = None


def get_image_fetcher() -> ImageFetcher:
    global _image_fetcher
    if _image_fetcher is None:
        _image_fetcher = ImageFetcher()
    return _image_fetcher


def attach_picture_media(card: dict | None) -> dict:
    shown = dict(card or {})
    topic = topic_key_from_card(shown)
    asset_id = pick_asset_id(topic, shown)
    shown["getty_id"] = asset_id
    fetcher = get_image_fetcher()
    if _picture_source() == "local":
        shown["image"] = browser_picture_src(shown.get("image"), title=shown.get("title") or "")
        shown["credit"] = ""
        return shown
    shown["image"] = fetcher.get_image_for_topic(topic, asset_id=asset_id)
    shown["credit"] = fetcher.credit_for_topic(topic, asset_id=asset_id)
    return shown
