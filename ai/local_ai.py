import json
import urllib.error
import urllib.request

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
    ) -> str:
        """Rule-based fallback for the plain-text practice-note prompt only.

        This is deliberately NOT used for marking/feedback: is_available()
        below returns False, so the real callers (ai/marking.py,
        ai/feedback.py) skip this provider entirely and use their own
        dedicated, better-calibrated rule-based scoring functions instead
        of trying to parse canned sentences as JSON.
        """
        prompt_lower = prompt.lower()

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

    def __init__(self, base_url: str, model: str, timeout: int = 20):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=2) as response:
                return response.status == 200
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

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
    ) -> str:
        """Simple text generation using Ollama."""
        messages = [AIMessage(role="user", content=prompt)]
        try:
            return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)
        except Exception as e:
            print(f"Ollama text generation failed: {e}")
            if json_mode:
                raise
            return "Good response. Keep practicing to improve your speaking skills."


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
    ) -> str:
        """Simple text generation using OpenAI."""
        messages = [AIMessage(role="user", content=prompt)]
        try:
            return self.generate(messages, temperature=temperature, json_mode=json_mode, max_tokens=max_tokens)
        except Exception as e:
            print(f"OpenAI text generation failed: {e}")
            if json_mode:
                raise
            return "Good response. Keep practicing to improve your speaking skills."


def create_provider(config: dict) -> AIProvider:
    choice = (config.get("AI_PROVIDER") or "auto").lower()
    if choice == "rule":
        return RuleBasedProvider()
    if choice == "ollama":
        return OllamaProvider(config["OLLAMA_BASE_URL"], config["OLLAMA_MODEL"])
    if choice == "openai":
        return OpenAIProvider(config.get("OPENAI_API_KEY", ""), config.get("OPENAI_MODEL", "gpt-4o-mini"))

    ollama = OllamaProvider(config.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"), config.get("OLLAMA_MODEL", "llama3.2"))
    if ollama.is_available():
        return ollama
    openai = OpenAIProvider(config.get("OPENAI_API_KEY", ""), config.get("OPENAI_MODEL", "gpt-4o-mini"))
    if openai.is_available():
        return openai
    return RuleBasedProvider()