from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
import logging

from ai.json_util import parse_json_object

logger = logging.getLogger(__name__)


def _is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "resource_exhausted" in text or "quota" in text


def _is_non_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        _is_quota_error(exc)
        or "timed out" in text
        or "timeout" in text
        or "gemini api error 5" in text
        or "gemini connection error" in text
    )


@dataclass
class AIMessage:
    role: str
    content: str


class AIProvider(ABC):
    """Swap this implementation without changing Flask routes or templates."""

    name = "base"

    @abstractmethod
    def generate(
        self,
        messages: list[AIMessage],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        raise NotImplementedError

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.7,
        json_mode: bool = False,
        system: str = "",
    ) -> str:
        """Simple text generation method for basic prompts.

        json_mode MUST be passed through to generate() — callers that expect a
        JSON object back (marking, feedback) rely on this to get a schema-
        conformant response instead of free-form prose that fails to parse.
        """
        messages = []
        if system:
            messages.append(AIMessage(role="system", content=system))
        messages.append(AIMessage(role="user", content=prompt))
        return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)

    def generate_json(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> dict:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                raw = self.generate_text(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    json_mode=True,
                    system=system,
                )
                return parse_json_object(raw)
            except Exception as exc:
                last_error = exc
                if _is_non_retryable(exc):
                    break
        raise ValueError(f"AI JSON was invalid after retry: {last_error}")

    def supports_audio(self) -> bool:
        return False

    def supports_images(self) -> bool:
        return False

    def generate_with_audio(
        self,
        prompt: str,
        audio_bytes: bytes,
        mime_type: str,
        *,
        system: str = "",
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        raise RuntimeError(f"{self.name} does not accept audio input")

    def generate_json_with_audio(
        self,
        prompt: str,
        audio_bytes: bytes,
        mime_type: str,
        *,
        system: str = "",
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> dict:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                raw = self.generate_with_audio(
                    prompt,
                    audio_bytes,
                    mime_type,
                    system=system,
                    json_mode=True,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return parse_json_object(raw)
            except Exception as exc:
                last_error = exc
                if _is_non_retryable(exc):
                    break
        raise ValueError(f"AI JSON was invalid after retry: {last_error}")

    def generate_with_media(
        self,
        prompt: str,
        media: list[tuple[bytes, str]],
        *,
        system: str = "",
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        if not media:
            return self.generate_text(prompt, max_tokens=max_tokens, temperature=temperature, json_mode=json_mode, system=system)
        audio = next((item for item in media if (item[1] or "").startswith("audio/")), None)
        if audio:
            return self.generate_with_audio(
                prompt, audio[0], audio[1], system=system, json_mode=json_mode, temperature=temperature, max_tokens=max_tokens
            )
        raise RuntimeError(f"{self.name} does not accept image input")

    def generate_json_with_media(
        self,
        prompt: str,
        media: list[tuple[bytes, str]],
        *,
        system: str = "",
        max_tokens: int = 800,
        temperature: float = 0.2,
    ) -> dict:
        last_error: Exception | None = None
        for _ in range(2):
            try:
                raw = self.generate_with_media(
                    prompt,
                    media,
                    system=system,
                    json_mode=True,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return parse_json_object(raw)
            except Exception as exc:
                last_error = exc
                if _is_non_retryable(exc):
                    break
        raise ValueError(f"AI JSON was invalid after retry: {last_error}")

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        raise RuntimeError(f"{self.name} cannot transcribe audio")

    def is_available(self) -> bool:
        return True


def get_provider():
    from flask import current_app

    from ai.local_ai import create_provider

    # Cache the provider on the app itself. Without this, create_provider()
    # ran on EVERY marking/feedback/practice-note call, and in "auto" mode
    # that means a live network probe to Ollama (up to a multi-second
    # timeout) before it even reaches OpenAI -- repeated on every single AI
    # interaction in an exam. This was the main source of the lag.
    cache = current_app.extensions.setdefault("ai_provider_cache", {})
    if "provider" not in cache:
        cache["provider"] = create_provider(current_app.config)
    return cache["provider"]


def get_ai():
    """Simple function to get AI provider for text generation."""
    from flask import current_app
    
    try:
        provider = get_provider()
        if provider and provider.is_available():
            return provider
    except Exception as e:
        logger.warning("Could not get AI provider: %s", e)
    return None