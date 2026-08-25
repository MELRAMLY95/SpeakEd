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
    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    config = provider._generation_config_for(
        "gemini-3.6-flash", temperature=0.1, max_tokens=280, json_mode=True
    )
    assert config["thinkingConfig"]["thinkingLevel"] == "minimal"
    assert "temperature" not in config
    assert config["responseMimeType"] == "application/json"


def test_gemini3_calls_25_flash_first():
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _mock_urlopen({
            "candidates": [{"content": {"parts": [{"text": '{"mark": 2}'}]}}]
        })

    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        provider.generate([AIMessage(role="user", content="mark this")], json_mode=True, temperature=0.1, max_tokens=280)

    assert "gemini-2.5-flash:" in captured["url"]
    assert captured["timeout"] == 45
    assert captured["body"]["generationConfig"]["thinkingConfig"]["thinkingBudget"] == 0
    assert provider.model == "gemini-2.5-flash"


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
            request.full_url,
            429,
            "Too Many Requests",
            hdrs={},
            fp=io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"quota"}}'),
        )

    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        with pytest.raises(ValueError, match="429"):
            provider.generate_json("return json")
    assert calls["n"] == len(provider._models_to_try())


def test_empty_thought_response_falls_back_to_another_model():
    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if "gemini-2.5-flash:" in request.full_url:
            return _mock_urlopen({
                "candidates": [{
                    "finishReason": "MAX_TOKENS",
                    "content": {"parts": [{"text": "thinking...", "thought": True}]},
                }]
            })
        return _mock_urlopen({
            "candidates": [{"content": {"parts": [{"text": "Photosynthesis converts light into chemical energy."}]}}]
        })

    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        text = provider.generate_text("Explain photosynthesis", max_tokens=200)
    assert "Photosynthesis" in text
    assert provider.model == "gemini-2.5-flash-lite"
    assert any("gemini-2.5-flash-lite" in url for url in calls)


def test_quota_falls_back_to_another_gemini_model():
    import io
    import urllib.error

    calls = []

    def fake_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if "gemini-2.5-flash:" in request.full_url:
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                hdrs={},
                fp=io.BytesIO(b'{"error":{"status":"RESOURCE_EXHAUSTED","message":"quota"}}'),
            )
        return _mock_urlopen({
            "candidates": [{"content": {"parts": [{"text": '{"mark": 2}'}]}}]
        })

    provider = GeminiProvider("test-key", "gemini-3.6-flash")
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = provider.generate_json("return json")
    assert result == {"mark": 2}
    assert provider.model == "gemini-2.5-flash-lite"
    assert any("gemini-2.5-flash:" in url for url in calls)
    assert any("gemini-2.5-flash-lite" in url for url in calls)
