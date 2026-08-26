"""Load picture-task images as bytes Gemini can actually receive."""

from __future__ import annotations

import re
import struct
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from urllib.parse import urlparse

from config import BASE_DIR
from security import host_is_blocked

MAX_PICTURE_BYTES = 2_000_000
FETCH_TIMEOUT = 10

_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/png",
}


class PictureLoadError(Exception):
    pass


_TOPIC_SVG = {
    "homes": "/static/images/pictures/homes.svg",
    "tourism": "/static/images/pictures/tourism.svg",
    "school": "/static/images/pictures/school.svg",
    "work": "/static/images/pictures/work.svg",
}

_TITLE_TOPICS = (
    ("home", "homes"),
    ("living", "homes"),
    ("tourism", "tourism"),
    ("travel", "tourism"),
    ("holiday", "tourism"),
    ("school", "school"),
    ("educat", "school"),
    ("learn", "school"),
    ("work", "work"),
    ("career", "work"),
    ("employ", "work"),
)


def _static_url(path: Path) -> str:
    return "/" + path.relative_to(BASE_DIR).as_posix()


def browser_picture_src(ref: str | None, *, title: str = "") -> str:
    """Return a same-origin image URL that exists on disk.

    Prompt cards historically pointed at .jpg files that were never shipped;
    the repo only has SVG scene cards. External Picsum URLs are also mapped
    back to those local files so the exam photo still shows if the CDN fails.
    """
    value = (ref or "").strip()
    lowered = value.lower()
    for topic, svg in _TOPIC_SVG.items():
        if topic in lowered:
            disk = BASE_DIR / svg.lstrip("/")
            if disk.is_file():
                return svg
    title_l = (title or "").lower()
    for needle, topic in _TITLE_TOPICS:
        if needle in title_l:
            svg = _TOPIC_SVG[topic]
            disk = BASE_DIR / svg.lstrip("/")
            if disk.is_file():
                return svg
    if not value or value.startswith(("http://", "https://")):
        return value
    try:
        path = _local_path(value)
    except PictureLoadError:
        return value
    if path.is_file():
        return _static_url(path)
    if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        svg = path.with_suffix(".svg")
        if svg.is_file():
            return _static_url(svg)
    return value


def load_picture_media(ref: str | None) -> tuple[bytes, str]:
    """Return (bytes, mime) for a stored path or http(s) URL.

    SVG files are rasterized to PNG so Gemini receives pixels, not a filename.
    """
    value = (ref or "").strip()
    if not value:
        raise PictureLoadError("No picture path was recorded for this attempt.")
    if value.startswith(("http://", "https://")):
        data, mime = _fetch_url(value)
    else:
        path = _local_path(value)
        if not path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            svg = path.with_suffix(".svg")
            if svg.is_file():
                path = svg
        if not path.is_file():
            raise PictureLoadError(f"Picture file was not found: {path.name}")
        data = path.read_bytes()
        if not data:
            raise PictureLoadError("Picture file was empty.")
        suffix = path.suffix.lower()
        if suffix == ".svg":
            data = svg_to_png(data.decode("utf-8", errors="replace"))
            mime = "image/png"
        else:
            mime = _MIME.get(suffix, "image/jpeg")
    if len(data) > MAX_PICTURE_BYTES:
        raise PictureLoadError("Picture is too large to send to the examiner.")
    if not data:
        raise PictureLoadError("Picture bytes were empty after loading.")
    return data, mime


def _local_path(ref: str) -> Path:
    raw = ref.split("?", 1)[0].replace("\\", "/")
    if not raw or ".." in Path(raw).parts or "\0" in raw:
        raise PictureLoadError("Invalid picture path.")
    if raw.startswith("/static/"):
        path = (BASE_DIR / raw.lstrip("/")).resolve()
    elif Path(raw).is_absolute():
        raise PictureLoadError("Invalid picture path.")
    else:
        path = (BASE_DIR / raw.lstrip("/")).resolve()
    static_root = (BASE_DIR / "static").resolve()
    try:
        path.relative_to(static_root)
    except ValueError as exc:
        raise PictureLoadError("Invalid picture path.") from exc
    return path


def _fetch_url(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise PictureLoadError("Picture URLs must be HTTPS.")
    if host_is_blocked(parsed.hostname or ""):
        raise PictureLoadError("That picture URL is not allowed.")
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "SpeakEd-examiner"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            data = response.read(MAX_PICTURE_BYTES + 1)
            header_mime = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    except urllib.error.URLError as exc:
        raise PictureLoadError("The picture URL could not be fetched.") from exc
    if len(data) > MAX_PICTURE_BYTES:
        raise PictureLoadError("Picture is too large to send to the examiner.")
    if not data:
        raise PictureLoadError("Fetched picture was empty.")
    mime = header_mime if header_mime.startswith("image/") else "image/jpeg"
    if mime in {"image/svg+xml", "text/xml", "application/xml"} or data.lstrip().startswith(b"<svg"):
        return svg_to_png(data.decode("utf-8", errors="replace")), "image/png"
    return data, mime


def _hex_rgb(value: str) -> tuple[int, int, int]:
    text = (value or "").strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return (180, 180, 180)
    return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))


def _fill_rect(pixels: list[list[tuple[int, int, int]]], x: int, y: int, w: int, h: int, color: tuple[int, int, int], width: int, height: int) -> None:
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(width, x + w), min(height, y + h)
    for py in range(y0, y1):
        row = pixels[py]
        for px in range(x0, x1):
            row[px] = color


def _fill_circle(pixels: list[list[tuple[int, int, int]]], cx: int, cy: int, r: int, color: tuple[int, int, int], width: int, height: int) -> None:
    r2 = r * r
    x0, y0 = max(0, cx - r), max(0, cy - r)
    x1, y1 = min(width, cx + r + 1), min(height, cy + r + 1)
    for py in range(y0, y1):
        row = pixels[py]
        dy = py - cy
        for px in range(x0, x1):
            dx = px - cx
            if dx * dx + dy * dy <= r2:
                row[px] = color


def _fill_polygon(pixels: list[list[tuple[int, int, int]]], points: list[tuple[int, int]], color: tuple[int, int, int], width: int, height: int) -> None:
    if len(points) < 3:
        return
    ys = [p[1] for p in points]
    for py in range(max(0, min(ys)), min(height, max(ys) + 1)):
        xs = []
        for i, (x1, y1) in enumerate(points):
            x2, y2 = points[(i + 1) % len(points)]
            if y1 == y2:
                continue
            if (y1 <= py < y2) or (y2 <= py < y1):
                xs.append(x1 + (py - y1) * (x2 - x1) / (y2 - y1))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            x0 = max(0, int(xs[i]))
            x1 = min(width, int(xs[i + 1]) + 1)
            row = pixels[py]
            for px in range(x0, x1):
                row[px] = color


def svg_to_png(svg_text: str, out_w: int = 320, out_h: int = 200) -> bytes:
    """Rasterize the simple geometric SVGs used as SpeakEd picture cards."""
    box = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg_text)
    src_w = int(box.group(1)) if box else 640
    src_h = int(box.group(2)) if box else 400
    sx, sy = out_w / src_w, out_h / src_h
    pixels = [[(240, 240, 240) for _ in range(out_w)] for _ in range(out_h)]

    for match in re.finditer(r"<rect\b([^>]*)/?>", svg_text):
        attrs = match.group(1)
        xm = re.search(r'\bx="([\d.]+)"', attrs)
        ym = re.search(r'\by="([\d.]+)"', attrs)
        wm = re.search(r'\bwidth="([\d.]+)"', attrs)
        hm = re.search(r'\bheight="([\d.]+)"', attrs)
        x = float(xm.group(1)) if xm else 0.0
        y = float(ym.group(1)) if ym else 0.0
        w = float(wm.group(1)) if wm else 0.0
        h = float(hm.group(1)) if hm else 0.0
        fill = re.search(r'\bfill="([^"]+)"', attrs)
        color = _hex_rgb(fill.group(1)) if fill else (200, 200, 200)
        _fill_rect(pixels, int(x * sx), int(y * sy), max(1, int(w * sx)), max(1, int(h * sy)), color, out_w, out_h)

    for match in re.finditer(r'<polygon\b([^>]*)/?>', svg_text):
        attrs = match.group(1)
        pts = re.search(r'\bpoints="([^"]+)"', attrs)
        fill = re.search(r'\bfill="([^"]+)"', attrs)
        if not pts:
            continue
        points = []
        nums = [float(n) for n in re.findall(r"[\d.]+", pts.group(1))]
        points = [(int(nums[i] * sx), int(nums[i + 1] * sy)) for i in range(0, len(nums) - 1, 2)]
        _fill_polygon(pixels, points, _hex_rgb(fill.group(1) if fill else "#888888"), out_w, out_h)

    for match in re.finditer(r"<circle\b([^>]*)/?>", svg_text):
        attrs = match.group(1)
        cx = float(re.search(r'\bcx="([\d.]+)"', attrs).group(1))
        cy = float(re.search(r'\bcy="([\d.]+)"', attrs).group(1))
        r = float(re.search(r'\br="([\d.]+)"', attrs).group(1))
        fill = re.search(r'\bfill="([^"]+)"', attrs)
        _fill_circle(pixels, int(cx * sx), int(cy * sy), max(1, int(r * min(sx, sy))), _hex_rgb(fill.group(1) if fill else "#888888"), out_w, out_h)

    return rgb_png(pixels)


def rgb_png(pixels: list[list[tuple[int, int, int]]]) -> bytes:
    height = len(pixels)
    width = len(pixels[0]) if pixels else 0
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in pixels)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
