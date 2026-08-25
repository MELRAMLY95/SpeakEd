import json
from unittest.mock import Mock, patch

import pytest

from ai.ai_provider import AIMessage
from ai.local_ai import GeminiProvider


def _mock_urlopen(body: dict):
    mock_response = Mock()
    mock_response.read.return_value = json.dumps(body).encode("utf-8")
    mock_cm = Mock()
    mock_cm.__enter__ = Mock(return_value=mock_response)
    mock_cm.__exit__ = Mock(return_value=False)
    return mock_cm


def test_gemini3_uses_minimal_thinking_and_omits_temperature():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _mock_urlopen({
            "candidates": [{"content": {"parts": [{"text": '{"mark": 2}'}]}}]
        })

    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.generate([AIMessage(role="user", content="mark this")], json_mode=True, temperature=0.1, max_tokens=280)

    config = captured["body"]["generationConfig"]
    assert config["thinkingConfig"]["thinkingLevel"] == "minimal"
    assert "temperature" not in config
    assert config["responseMimeType"] == "application/json"
    assert captured["timeout"] == 90


def test_gemini25_disables_thinking_budget():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _mock_urlopen({
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
        })

    provider = GeminiProvider("test-key", "gemini-2.5-flash")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.generate([AIMessage(role="user", content="hello")], temperature=0.2, max_tokens=100)

    config = captured["body"]["generationConfig"]
    assert config["thinkingConfig"]["thinkingBudget"] == 0
    assert config["temperature"] == 0.2


def test_thought_parts_are_not_treated_as_the_answer():
    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    text = provider._text_from_body({
        "candidates": [{
            "content": {
                "parts": [
                    {"text": "internal reasoning", "thought": True},
                    {"text": '{"mark": 1}'},
                ]
            }
        }]
    })
    assert text == '{"mark": 1}'


def test_thought_only_response_is_an_error():
    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    with pytest.raises(RuntimeError, match="no visible text"):
        provider._text_from_body({
            "candidates": [{
                "finishReason": "MAX_TOKENS",
                "content": {"parts": [{"text": "thinking...", "thought": True}]},
            }]
        })


def test_quota_errors_are_not_retried():
    import io
    import urllib.error

    calls = {"n": 0}

    def fake_urlopen(request, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent",
            429,
            "Too Many Requests",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"quota"}}'),
        )

    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(ValueError, match="429"):
            provider.generate_json("return json")
    assert calls["n"] == 1
