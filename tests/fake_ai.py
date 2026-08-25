import json
import re

from ai.ai_provider import AIProvider, AIMessage


class FakeAIProvider(AIProvider):
    """Deterministic in-process examiner for tests. Does not call any network API."""

    name = "fake"

    def __init__(
        self,
        *,
        fail: bool = False,
        invalid_json: bool = False,
        supports_audio_flag: bool = False,
        transcribe_fail: bool = False,
        transcribe_empty: bool = False,
    ):
        self.fail = fail
        self.invalid_json = invalid_json
        self.supports_audio_flag = supports_audio_flag
        self.transcribe_fail = transcribe_fail
        self.transcribe_empty = transcribe_empty
        self.prompts: list[str] = []
        self.audio_calls = 0

    def is_available(self) -> bool:
        return not self.fail

    def supports_audio(self) -> bool:
        return self.supports_audio_flag and not self.fail

    def generate(self, messages: list[AIMessage], *, json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 800) -> str:
        prompt = messages[-1].content if messages else ""
        if json_mode:
            return json.dumps(self._json_for(prompt))
        return self._text_for(prompt)

    def generate_text(self, prompt: str, max_tokens: int = 100, temperature: float = 0.7, json_mode: bool = False, system: str = "") -> str:
        if self.fail:
            raise RuntimeError("provider failure")
        if self.invalid_json and json_mode:
            return "this is not json {"
        self.prompts.append(prompt)
        if json_mode:
            return json.dumps(self._json_for(prompt))
        return self._text_for(prompt)

    def generate_with_audio(self, prompt: str, audio_bytes: bytes, mime_type: str, *, system: str = "", json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 800) -> str:
        if not audio_bytes:
            raise RuntimeError("missing audio")
        self.audio_calls += 1
        if json_mode:
            return self.generate_text(prompt, json_mode=True, system=system, max_tokens=max_tokens, temperature=temperature)
        return self.transcribe_audio(audio_bytes, mime_type)

    def transcribe_audio(self, audio_bytes: bytes, mime_type: str) -> str:
        self.audio_calls += 1
        if self.transcribe_fail:
            raise RuntimeError("transcription failed")
        if self.transcribe_empty:
            return ""
        return "I enjoy football because it gives me the chance to work with other people."

    def _text_for(self, prompt: str) -> str:
        match = re.search(r'STUDENT RESPONSE: "(.*?)"', prompt, re.S)
        excerpt = (match.group(1) if match else prompt)[:80]
        return f"Specific note on: {excerpt}"

    def _student_blob(self, prompt: str) -> str:
        match = re.search(r'STUDENT RESPONSE: "(.*?)"', prompt, re.S)
        if match:
            return match.group(1)
        students = re.findall(r"Student: (.*)", prompt)
        return " ".join(students)

    def _json_for(self, prompt: str) -> dict:
        text = self._student_blob(prompt)
        words = re.findall(r"[A-Za-z']+", text)
        # The feedback prompt lists the task scores, so it contains "Task 1" and
        # would otherwise be mistaken for a role play marking prompt and answered
        # with the wrong JSON shape.
        if "STUDENT QUESTION/ANSWER RECORD" in prompt:
            return self._feedback_json(text, len(words))
        if "Remaining allowed questions" in prompt or "NEXT question" in prompt:
            ids = re.findall(r'"id": "([^"]+)"', prompt)
            return {"prompt_id": ids[0] if ids else "", "reason": "next unused bank prompt"}
        if "Role Play" in prompt or "Task 1" in prompt:
            mark = 0 if len(words) <= 1 else (1 if len(words) < 5 else 2)
            if "QUESTION REQUIRED: yes" in prompt and "?" not in text:
                mark = 0
            return {
                "mark": mark,
                "reasoning": f"Assessed the actual response ({len(words)} words).",
                "evidence": [text[:80] or "(empty)"],
                "strengths": [f"Content: {text[:60]}" if text else "No speech"],
                "weaknesses": ["Very brief." if len(words) < 8 else "Could add more precision."],
                "improvements": ["Extend the answer with a reason." if len(words) < 12 else "Keep developing ideas."],
            }
        if "COMMUNICATION AND CONTENT" in prompt or "communication_score" in prompt or "Task 2" in prompt or "Task 3" in prompt:
            comm = 3 if len(words) < 20 else (7 if len(words) < 80 else 10)
            ling = 2 if len(words) < 20 else (5 if len(words) < 80 else 7)
            return {
                "communication_score": comm,
                "linguistic_score": ling,
                "reasoning": f"Based on the student's {len(words)}-word performance.",
                "evidence": [text[:80] or "(empty)"],
                "strengths": [f"You said: {text[:70]}"],
                "weaknesses": ["Limited development." if len(words) < 20 else "Some ideas could be more precise."],
                "improvements": ["Add a reason and an example." if len(words) < 20 else "Keep extending sequences of speech."],
            }
        return self._feedback_json(text, len(words))

    def _feedback_json(self, text: str, word_count: int) -> dict:
        return {
            "strengths": [f"You developed this idea: {text[:70] or 'n/a'}", "You completed the speaking tasks.", "You addressed the examiner prompts."],
            "weaknesses": [f"This answer stayed at {word_count} words." if text else "No speech captured.", "Some ideas needed more detail.", "Accuracy could be more consistent."],
            "recommendations": [f"Build on “{text[:40]}” with a reason and example." if text else "Give a full spoken answer.", "Practise extending one idea.", "Record again and check you answered the prompt."],
        }


def install_fake(monkeypatch, fake: FakeAIProvider | None = None) -> FakeAIProvider:
    fake = fake or FakeAIProvider()
    monkeypatch.setattr("ai.examiner.get_ai", lambda: fake)
    monkeypatch.setattr("ai.marking.get_ai", lambda: fake)
    monkeypatch.setattr("ai.feedback.get_ai", lambda: fake)
    monkeypatch.setattr("ai.ai_provider.get_ai", lambda: fake)
    return fake
