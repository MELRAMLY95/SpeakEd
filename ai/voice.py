"""Browser-first TTS. Server helpers exist so a later neural voice can replace speechSynthesis."""

DEFAULT_VOICE_SETTINGS = {
    "lang": "en-GB",
    "rate": 0.95,
    "pitch": 1.0,
    "engine": "browser",
}


def examiner_voice_payload(text: str) -> dict:
    return {"text": text, "voice": DEFAULT_VOICE_SETTINGS}
