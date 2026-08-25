import json
import urllib.error
import urllib.request
from typing import Any

from ai.ai_provider import AIMessage, AIProvider


class RuleBasedProvider(AIProvider):
    """Works with no paid API and no local model. Used as the $0 default."""

    name = "rule"

    def generate(
        self,
        messages: list[AIMessage],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        last = messages[-1].content if messages else ""
        if json_mode:
            return json.dumps({"ok": True, "note": "rule-based provider", "prompt_excerpt": last[:240]})
        return ""

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.7,
        json_mode: bool = False,
        system: str = "",
    ) -> str:
        """Rule-based fallback for the plain-text practice-note prompt only.

        This is deliberately NOT used for marking/feedback: is_available()
        below returns False, so the real callers (ai/marking.py,
        ai/feedback.py) skip this provider entirely and use their own
        dedicated, better-calibrated rule-based scoring functions instead
        of trying to parse canned sentences as JSON.
        """
        prompt_lower = prompt.lower()

        # Check if this is an information gathering request
        if "comprehensive information" in prompt_lower or "information about the topic" in prompt_lower:
            # Extract the topic from the prompt
            topic_start = prompt_lower.find("topic:") + 6 if "topic:" in prompt_lower else -1
            if topic_start == -1:
                topic_start = prompt_lower.find("topic") + 5 if "topic" in prompt_lower else -1
            
            if topic_start != -1:
                topic_end = prompt.find(".", topic_start)
                topic = prompt[topic_start:topic_end].strip() if topic_end != -1 else prompt[topic_start:].strip()
                topic = topic[:50]  # Limit topic length
            else:
                topic = "this subject"
            
            return f"""Information about {topic}

Key Facts:
• {topic} is an important subject with various aspects to consider
• Understanding the fundamentals is essential for advanced learning
• There are multiple perspectives and approaches to studying {topic}

Important Concepts:
• Core principles form the foundation of {topic}
• Relationships between different concepts help deepen understanding
• Practical application reinforces theoretical knowledge

Examples:
• Real-world applications demonstrate the relevance of {topic}
• Case studies provide concrete illustrations of key concepts
• Historical context shows the development of ideas over time

Explanations:
• Breaking down complex ideas into manageable parts aids comprehension
• Connecting new information to existing knowledge improves retention
• Regular practice and review are essential for mastery

Additional Notes:
• Further research and reading are recommended for deeper understanding
• Discussing topics with peers can provide new insights
• Hands-on experience complements theoretical study"""

        if "short" in prompt_lower and "word" in prompt_lower:
            return "Your answer needs more detail. Try to extend it with more information."
        elif "role-play" in prompt_lower:
            return "Make sure your response addresses the specific role-play situation appropriately."
        elif "topic" in prompt_lower:
            return "Try to develop your ideas with specific examples and clear reasoning."
        elif "picture" in prompt_lower:
            return "Go beyond simple description - add your opinion or personal experience."
        elif "because" in prompt_lower or "reason" in prompt_lower:
            return "Good use of reasoning. Keep supporting your points with evidence."
        elif "question" in prompt_lower and "?" in prompt_lower:
            return "Good job asking your question as required by the prompt."
        else:
            return "Clear communication. Continue developing your ideas with specific details."

    def is_available(self) -> bool:
        # This provider cannot produce the structured JSON that marking and
        # feedback require. Reporting True here (the old behaviour) caused
        # every AI-marking/AI-feedback call to be attempted, fail to parse,
        # and silently fall back to a weaker inline heuristic instead of the
        # proper rule-based engine. Reporting False makes get_ai() return
        # None so callers go straight to the correct fallback path.
        return False


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: int = 20, availability_cache_seconds: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._availability_cache_seconds = availability_cache_seconds
        self._last_check_at: float | None = None
        self._last_available: bool = False

    def is_available(self) -> bool:
        import time

        now = time.monotonic()
        if self._last_check_at is not None and (now - self._last_check_at) < self._availability_cache_seconds:
            return self._last_available
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=2) as response:
                self._last_available = response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            self._last_available = False
        self._last_check_at = now
        return self._last_available

    def generate(
        self,
        messages: list[AIMessage],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if json_mode:
            payload["format"] = "json"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body.get("message", {}).get("content", "")

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.7,
        json_mode: bool = False,
        system: str = "",
    ) -> str:
        messages = []
        if system:
            messages.append(AIMessage(role="system", content=system))
        messages.append(AIMessage(role="user", content=prompt))
        try:
            return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)
        except Exception as e:
            print(f"Ollama text generation failed: {e}")
            raise


class GeminiProvider(AIProvider):
    """Google Gemini API — has a free tier (see https://ai.google.dev/pricing).

    Used automatically on Render (no local Ollama to reach there) and as a
    fallback anywhere else once Ollama is unavailable and a key is set.
    """

    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        messages: list[AIMessage],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        # Gemini has no "system" role in `contents` — system text goes in a
        # separate systemInstruction field, and "assistant" turns are "model".
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
                continue
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": ""}]}]

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        data = json.dumps(payload).encode("utf-8")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return self._text_from_body(body)

    def supports_audio(self) -> bool:
        return bool(self.api_key)

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
        import base64

        if not audio_bytes:
            raise RuntimeError("Gemini audio generation requires the student's recording")
        mime = (mime_type or "audio/webm").split(";")[0].strip() or "audio/webm"
        parts: list[dict[str, Any]] = [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio_bytes).decode("ascii")}},
        ]
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return self._text_from_body(body)

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        text = self.generate_with_audio(
            "Transcribe this student's spoken English. Return only the transcript, with no commentary.",
            audio_bytes,
            mime_type,
            temperature=0.0,
            max_tokens=800,
        )
        return (text or "").strip()

    @staticmethod
    def _text_from_body(body: dict[str, Any]) -> str:
        candidates = body.get("candidates") or []
        if not candidates:
            block_reason = (body.get("promptFeedback") or {}).get("blockReason")
            raise RuntimeError(f"Gemini returned no candidates (blockReason={block_reason!r})")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.7,
        json_mode: bool = False,
        system: str = "",
    ) -> str:
        messages = []
        if system:
            messages.append(AIMessage(role="system", content=system))
        messages.append(AIMessage(role="user", content=prompt))
        try:
            return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)
        except Exception as e:
            print(f"Gemini text generation failed: {e}")
            raise


class ZAIProvider(AIProvider):
    """Z.AI (GLM) API provider — primary AI provider for SpeakEd.
    
    Uses the Z.AI API (https://api.z.ai/api/paas/v4) with GLM models.
    Environment variable ZAI_API_KEY is required.
    """

    name = "zai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        messages: list[AIMessage],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        data = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}/chat/completions"
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            
            # Handle Z.AI/GLM response format
            if "choices" in body and len(body["choices"]) > 0:
                return body["choices"][0]["message"]["content"]
            else:
                raise RuntimeError(f"Z.AI returned unexpected response format: {body}")
                
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8")
            raise RuntimeError(f"Z.AI API error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Z.AI connection error: {e.reason}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Z.AI returned invalid JSON: {e}")
        except Exception as e:
            raise RuntimeError(f"Z.AI generation failed: {e}")

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.7,
        json_mode: bool = False,
        system: str = "",
    ) -> str:
        messages = []
        if system:
            messages.append(AIMessage(role="system", content=system))
        messages.append(AIMessage(role="user", content=prompt))
        try:
            return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)
        except Exception as e:
            print(f"Z.AI text generation failed: {e}")
            raise


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str, timeout: int = 30):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        messages: list[AIMessage],
        *,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> str:
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]

    def generate_text(
        self,
        prompt: str,
        max_tokens: int = 100,
        temperature: float = 0.7,
        json_mode: bool = False,
        system: str = "",
    ) -> str:
        messages = []
        if system:
            messages.append(AIMessage(role="system", content=system))
        messages.append(AIMessage(role="user", content=prompt))
        try:
            return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)
        except Exception as e:
            print(f"OpenAI text generation failed: {e}")
            raise


def create_provider(config: dict) -> AIProvider:
    choice = (config.get("AI_PROVIDER") or "auto").lower()
    if choice == "rule":
        return RuleBasedProvider()
    if choice == "ollama":
        return OllamaProvider(config.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"), config.get("OLLAMA_MODEL", "llama3.2"))
    if choice == "gemini":
        return GeminiProvider(config.get("GEMINI_API_KEY", ""), config.get("GEMINI_MODEL", "gemini-3.6-flash"))
    if choice == "openai":
        return OpenAIProvider(config.get("OPENAI_API_KEY", ""), config.get("OPENAI_MODEL", "gpt-4o-mini"))
    if choice == "zai":
        zai = ZAIProvider(
            config.get("ZAI_API_KEY", ""),
            config.get("ZAI_MODEL", "glm-4"),
            config.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
        )
        if not zai.is_available():
            raise RuntimeError("Z.AI provider selected but ZAI_API_KEY is not set")
        return zai

    # --- "auto" mode ---
    # Priority: Z.AI → Gemini → Ollama → rule
    zai = ZAIProvider(
        config.get("ZAI_API_KEY", ""),
        config.get("ZAI_MODEL", "glm-4"),
        config.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4")
    )
    gemini = GeminiProvider(config.get("GEMINI_API_KEY", ""), config.get("GEMINI_MODEL", "gemini-3.6-flash"))
    openai = OpenAIProvider(config.get("OPENAI_API_KEY", ""), config.get("OPENAI_MODEL", "gpt-4o-mini"))

    # Try Z.AI first (primary provider)
    if zai.is_available():
        return zai
    
    # Fallback to Gemini
    if gemini.is_available():
        return gemini
    
    # For local development, try Ollama before OpenAI
    if not config.get("IS_RENDER"):
        ollama = OllamaProvider(config.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"), config.get("OLLAMA_MODEL", "llama3.2"))
        if ollama.is_available():
            return ollama
    
    # Fallback to OpenAI if available
    if openai.is_available():
        return openai
    
    # Final fallback to rule-based provider
    return RuleBasedProvider()