import json
import re


def _as_marking_object(parsed):
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"prompt_marks": parsed}
    return None


def parse_json_object(raw: str) -> dict:
    """Parse a JSON object from a string, with error handling for AI responses.

    Handles markdown fences, surrounding prose, a trailing-comma repair, and a
    bare JSON array of prompt marks (wrapped as {"prompt_marks": [...]}).
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("Input must be a non-empty string")

    try:
        parsed = _as_marking_object(json.loads(raw))
        if parsed is not None:
            return parsed
        raise ValueError("AI JSON was not an object")
    except json.JSONDecodeError:
        pass

    if "```json" in raw:
        start = raw.find("```json") + 7
        end = raw.find("```", start)
        if end != -1:
            try:
                parsed = _as_marking_object(json.loads(raw[start:end].strip()))
                if parsed is not None:
                    return parsed
            except json.JSONDecodeError:
                pass
    elif "```" in raw:
        start = raw.find("```") + 3
        end = raw.find("```", start)
        if end != -1:
            try:
                parsed = _as_marking_object(json.loads(raw[start:end].strip()))
                if parsed is not None:
                    return parsed
            except json.JSONDecodeError:
                pass

    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = raw[first_brace:last_brace + 1]
        for candidate in (snippet, re.sub(r",\s*([}\]])", r"\1", snippet)):
            try:
                parsed = _as_marking_object(json.loads(candidate))
                if parsed is not None:
                    return parsed
            except json.JSONDecodeError:
                pass

    first_bracket = raw.find("[")
    last_bracket = raw.rfind("]")
    if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
        snippet = raw[first_bracket:last_bracket + 1]
        try:
            parsed = _as_marking_object(json.loads(snippet))
            if parsed is not None:
                return parsed
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from: {raw[:200]}...")
