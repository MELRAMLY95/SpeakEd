from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


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
    ) -> str:
        """Simple text generation method for basic prompts.

        json_mode MUST be passed through to generate() — callers that expect a
        JSON object back (marking, feedback) rely on this to get a schema-
        conformant response instead of free-form prose that fails to parse.
        """
        messages = [AIMessage(role="user", content=prompt)]
        return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)

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
        print(f"Could not get AI provider: {e}")
    return None