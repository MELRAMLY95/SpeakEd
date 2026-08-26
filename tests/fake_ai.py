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
        fail_feedback: bool = False,
        fail_audio: bool = False,
        fail_images: bool = False,
        timeout: bool = False,
        http_error: int | None = None,
        out_of_range_once: bool = False,
        supports_images_flag: bool = True,
    ):
        self.fail = fail
        self.invalid_json = invalid_json
        self.supports_audio_flag = supports_audio_flag
        self.transcribe_fail = transcribe_fail
        self.transcribe_empty = transcribe_empty
        self.fail_feedback = fail_feedback
        self.fail_audio = fail_audio
        self.fail_images = fail_images
        self.timeout = timeout
        self.http_error = http_error
        self.out_of_range_once = out_of_range_once
        self.supports_images_flag = supports_images_flag
        self.prompts: list[str] = []
        self.audio_calls = 0
        self.json_calls = 0
        self.image_calls = 0
        self.last_image_mime = None
        self.last_image_bytes = 0
        self.last_media = []

    def is_available(self) -> bool:
        return not self.fail

    def supports_audio(self) -> bool:
        return self.supports_audio_flag and not self.fail

    def supports_images(self) -> bool:
        return self.supports_images_flag and not self.fail

    def generate(self, messages: list[AIMessage], *, json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 800) -> str:
        prompt = messages[-1].content if messages else ""
        if self.fail:
            raise RuntimeError("provider failure")
        if self.timeout:
            raise TimeoutError("Gemini connection error: timed out")
        if self.http_error:
            raise RuntimeError(f"Gemini API error {self.http_error}: service unavailable")
        if self.fail_feedback and "STUDENT QUESTION/ANSWER RECORD" in prompt:
            raise RuntimeError("feedback provider failure")
        if json_mode:
            self.json_calls += 1
            return json.dumps(self._json_for(prompt))
        return self._text_for(prompt)

    def generate_text(self, prompt: str, max_tokens: int = 100, temperature: float = 0.7, json_mode: bool = False, system: str = "") -> str:
        if self.fail:
            raise RuntimeError("provider failure")
        if self.timeout:
            raise TimeoutError("Gemini connection error: timed out")
        if self.http_error:
            raise RuntimeError(f"Gemini API error {self.http_error}: service unavailable")
        if self.fail_feedback and "STUDENT QUESTION/ANSWER RECORD" in prompt:
            raise RuntimeError("feedback provider failure")
        if self.invalid_json and json_mode:
            return "this is not json {"
        self.prompts.append(prompt)
        if json_mode:
            self.json_calls += 1
            return json.dumps(self._json_for(prompt))
        return self._text_for(prompt)

    def generate_with_audio(self, prompt: str, audio_bytes: bytes, mime_type: str, *, system: str = "", json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 800) -> str:
        if not audio_bytes:
            raise RuntimeError("missing audio")
        self.audio_calls += 1
        if self.fail_audio:
            raise RuntimeError("audio marking failed")
        if json_mode:
            return self.generate_text(prompt, json_mode=True, system=system, max_tokens=max_tokens, temperature=temperature)
        return self.transcribe_audio(audio_bytes, mime_type)

    def generate_with_media(self, prompt: str, media: list, *, system: str = "", json_mode: bool = False, temperature: float = 0.2, max_tokens: int = 800) -> str:
        if self.fail_images:
            raise RuntimeError("zai does not accept image input")
        self.last_media = []
        for data, mime in media or []:
            item = {"mime": mime, "nbytes": len(data or b"")}
            self.last_media.append(item)
            if (mime or "").startswith("image/"):
                self.image_calls += 1
                self.last_image_mime = mime
                self.last_image_bytes = len(data or b"")
            if (mime or "").startswith("audio/"):
                self.audio_calls += 1
                if self.fail_audio:
                    raise RuntimeError("audio marking failed")
        if json_mode:
            return self.generate_text(prompt, json_mode=True, system=system, max_tokens=max_tokens, temperature=temperature)
        return self._text_for(prompt)

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
        if "comprehensive information" in prompt.lower() or "information about the topic" in prompt.lower():
            return (
                "Key Facts\n"
                "This topic matters for IGCSE ESL speaking because students can give reasons and examples.\n\n"
                "Important Concepts\n"
                "• Cause and effect\n"
                "• Local and global impact\n\n"
                "Examples\n"
                "• A bottle deposit scheme reduces plastic waste.\n\n"
                "Explanations\n"
                "Develop one idea with a reason, then add a short personal example."
            )
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
            responses = re.findall(r'STUDENT RESPONSE: "(.*?)"', prompt, re.S)
            if not responses:
                responses = [text]
            if self.out_of_range_once and self.json_calls <= 1:
                return {
                    "prompt_marks": [{
                        "prompt_index": 1,
                        "mark": 9,
                        "reasoning": "out of range",
                        "evidence": [responses[0][:80] or "(empty)"],
                        "strengths": [f"Content: {responses[0][:60]}"],
                        "weaknesses": ["Range error"],
                        "improvements": ["Retry"],
                    }]
                }
            items = []
            required_flags = re.findall(r"QUESTION REQUIRED: (yes|no)", prompt)
            for i, resp in enumerate(responses):
                words = re.findall(r"[A-Za-z']+", resp)
                mark = 0 if len(words) <= 1 else (1 if len(words) < 5 else 2)
                required = required_flags[i] == "yes" if i < len(required_flags) else "QUESTION REQUIRED: yes" in prompt
                if required and "?" not in resp:
                    mark = 0
                items.append({
                    "prompt_index": i + 1,
                    "mark": mark,
                    "reasoning": f"Assessed the actual response ({len(words)} words).",
                    "evidence": [resp[:80] or "(empty)"],
                    "strengths": [f"Content: {resp[:60]}" if resp else "No speech"],
                    "weaknesses": ["Very brief." if len(words) < 8 else "Could add more precision."],
                    "improvements": ["Extend the answer with a reason." if len(words) < 12 else "Keep developing ideas."],
                })
            if "prompt_marks" in prompt or len(items) > 1:
                return {"prompt_marks": items}
            return items[0]
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
    monkeypatch.setattr("routes.information.get_ai", lambda: fake)
    return fake
