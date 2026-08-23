import json


def parse_json_object(raw: str) -> dict:
    """Parse a JSON object from a string, with error handling for AI responses.
    
    This function is used to parse JSON responses from AI providers.
    It handles common issues like markdown code blocks, extra text, etc.
    
    Args:
        raw: The raw string response from an AI provider
        
    Returns:
        The parsed JSON object as a dictionary
        
    Raises:
        ValueError: If the string cannot be parsed as valid JSON
    """
    if not raw or not isinstance(raw, str):
        raise ValueError("Input must be a non-empty string")
    
    # Try to parse as-is first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON from markdown code blocks
    if "```json" in raw:
        # Extract content between ```json and ```
        start = raw.find("```json") + 7
        end = raw.find("```", start)
        if end != -1:
            try:
                return json.loads(raw[start:end].strip())
            except json.JSONDecodeError:
                pass
    elif "```" in raw:
        # Extract content between first ``` and next ```
        start = raw.find("```") + 3
        end = raw.find("```", start)
        if end != -1:
            try:
                return json.loads(raw[start:end].strip())
            except json.JSONDecodeError:
                pass
    
    # Try to find the first { and last } and parse that
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        try:
            return json.loads(raw[first_brace:last_brace + 1])
        except json.JSONDecodeError:
            pass
    
    # If all else fails, raise an error
    raise ValueError(f"Could not parse JSON from: {raw[:200]}...")
