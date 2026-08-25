"""Student speech: browser capture, optional upload, validation, temp storage."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

ALLOWED_AUDIO_EXTENSIONS = {".webm", ".ogg", ".mp3", ".wav", ".m4a", ".mp4", ".mpeg"}
ALLOWED_AUDIO_MIMES = {
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "video/webm",
}
MIN_AUDIO_BYTES = 256
MIN_DURATION_MS = 400

_MIME_EXT = {
    "audio/webm": ".webm",
    "video/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
}


class SpeechError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict:
        return {"error": self.message, "code": self.code, "retry": True}


def summarise_metrics(metrics: dict | None) -> dict:
    metrics = metrics or {}
    duration_ms = int(metrics.get("duration_ms") or 0)
    pause_count = int(metrics.get("pause_count") or 0)
    filler_count = int(metrics.get("filler_count") or 0)
    words = int(metrics.get("word_count") or 0)
    wpm = round((words / (duration_ms / 60000)) if duration_ms else 0, 1)
    audio_received = bool(metrics.get("audio_received"))
    return {
        "duration_ms": duration_ms,
        "pause_count": pause_count,
        "filler_count": filler_count,
        "word_count": words,
        "words_per_minute": wpm,
        "audio_received": audio_received,
        "pronunciation_note": (
            "Pronunciation can only be assessed when the selected model actually received the recording."
            if audio_received
            else "No audio was available to the examiner. Pronunciation and intonation were not assessed."
        ),
    }


def parse_metrics(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _safe_ext(filename: str, mime_type: str) -> str:
    name = secure_filename(filename or "") or "turn"
    ext = Path(name).suffix.lower()
    if ext in ALLOWED_AUDIO_EXTENSIONS:
        return ext
    return _MIME_EXT.get((mime_type or "").split(";")[0].strip().lower(), "")


def validate_audio_bytes(data: bytes, mime_type: str, filename: str = "turn.webm", duration_ms: int = 0) -> str:
    if not data:
        raise SpeechError("empty_recording", "No audio was captured. Please record your answer and try again.")
    if len(data) < MIN_AUDIO_BYTES:
        raise SpeechError("empty_recording", "The recording was empty or too short. Please speak again.")
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime and mime not in ALLOWED_AUDIO_MIMES:
        raise SpeechError("invalid_audio", "That audio format is not supported. Try Chrome or Edge with the microphone enabled.")
    ext = _safe_ext(filename, mime)
    if not ext:
        raise SpeechError("invalid_audio", "The audio file type could not be identified.")
    max_len = int(current_app.config.get("MAX_CONTENT_LENGTH") or 8 * 1024 * 1024)
    if len(data) > max_len:
        raise SpeechError("oversized_recording", "The recording is too large. Give a shorter answer and try again.")
    if duration_ms and duration_ms < MIN_DURATION_MS:
        raise SpeechError("short_recording", "The recording was too short. Please answer again.")
    return ext


def attempt_audio_dir(attempt_id: int) -> Path:
    root = Path(current_app.instance_path) / "exam_audio" / str(int(attempt_id))
    root.mkdir(parents=True, exist_ok=True)
    return root


def save_turn_audio(attempt_id: int, data: bytes, ext: str) -> str:
    folder = attempt_audio_dir(attempt_id)
    name = f"{uuid.uuid4().hex}{ext}"
    path = folder / name
    path.write_bytes(data)
    return str(path)


def read_audio_file(path: str | None) -> tuple[bytes | None, str | None]:
    if not path:
        return None, None
    file_path = Path(path)
    if not file_path.is_file():
        return None, None
    ext = file_path.suffix.lower()
    mime = {v: k for k, v in _MIME_EXT.items()}.get(ext, "audio/webm")
    if ext == ".webm":
        mime = "audio/webm"
    return file_path.read_bytes(), mime


def cleanup_attempt_audio(attempt_id: int, *, force: bool = False) -> None:
    store = bool(current_app.config.get("STORE_AUDIO"))
    if store and not force:
        return
    folder = Path(current_app.instance_path) / "exam_audio" / str(int(attempt_id))
    if not folder.is_dir():
        return
    for child in folder.iterdir():
        if child.is_file() and re.match(r"^[a-f0-9]{32}\.[A-Za-z0-9]+$", child.name):
            child.unlink(missing_ok=True)
    try:
        folder.rmdir()
    except OSError:
        pass


def process_upload(file_storage: FileStorage, metrics: dict | None = None) -> dict:
    metrics = metrics or {}
    data = file_storage.read()
    mime = file_storage.mimetype or ""
    duration_ms = int(metrics.get("duration_ms") or 0)
    ext = validate_audio_bytes(data, mime, file_storage.filename or "turn.webm", duration_ms)
    return {"bytes": data, "mime": (mime.split(";")[0].strip() or "audio/webm"), "ext": ext}


def collect_attempt_audio(turns: list[dict]) -> tuple[bytes | None, str | None, bool]:
    """Return the last stored clip and whether any turn has audio on disk."""
    last_bytes = None
    last_mime = None
    any_audio = False
    for turn in turns:
        path = (turn.get("metrics") or {}).get("audio_path") or turn.get("audio_path")
        data, mime = read_audio_file(path)
        if data:
            any_audio = True
            last_bytes, last_mime = data, mime
    return last_bytes, last_mime, any_audio
