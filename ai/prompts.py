import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from database.database import execute, query_all

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "prompts"

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "your",
    "you", "do", "did", "does", "what", "why", "how", "when", "where", "is", "are",
    "about", "this", "that", "it", "be", "can", "would", "could", "should",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def meaning_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class PromptBank:
    def __init__(self):
        self.warmup = _load("warmup.json")
        self.roleplay = _load("roleplay.json")
        self.topic_talk = _load("topic_talk.json")
        self.picture = _load("picture_conversation.json")

    def choose_warmup(self, user_id: int, count: int = 4) -> list[dict]:
        return self._choose_many(user_id, "warmup", self.warmup["prompts"], count)

    def choose_roleplay(self, user_id: int) -> dict:
        return self._choose_one(user_id, "roleplay", self.roleplay["cards"])

    def choose_picture(self, user_id: int, avoid_topic: str | None = None) -> dict:
        cards = self.picture["cards"]
        if avoid_topic:
            filtered = [c for c in cards if c.get("topic_area") != avoid_topic]
            if filtered:
                cards = filtered
        return self._choose_one(user_id, "picture", cards)

    def choose_picture_by_id(self, picture_id: str) -> dict:
        cards = self.picture["cards"]
        for card in cards:
            if card.get("id") == picture_id:
                # Return a copy to avoid modifying the original
                return dict(card)
        # Fallback to first card if not found
        return dict(cards[0]) if cards else {}

    def choose_topic_followups(self, user_id: int, topic_title: str, count: int = 6) -> list[dict]:
        pool = []
        for item in self.topic_talk["follow_ups"]:
            prompt = item["prompt"].replace("{topic}", topic_title or "your topic")
            pool.append({**item, "prompt": prompt})
        return self._choose_many(user_id, "topic_talk", pool, count)

    def choose_coach_prompts(self, skill: str, count: int = 5) -> list[dict]:
        items = [p for p in self.topic_talk.get("coach_prompts", []) if p.get("skill") == skill]
        if not items:
            items = self.topic_talk.get("coach_prompts", [])
        random.shuffle(items)
        return items[:count]

    def record_usage(self, user_id: int, prompt: dict, task: str):
        execute(
            "INSERT INTO prompt_usage (user_id, prompt_id, meaning_key, task, used_at) VALUES (?, ?, ?, ?, ?)",
            (
                user_id,
                prompt.get("id", ""),
                prompt.get("meaning_key") or prompt.get("prompt", "")[:80],
                task,
                _now(),
            ),
        )

    def _history(self, user_id: int, task: str) -> list[dict]:
        rows = query_all(
            "SELECT prompt_id, meaning_key FROM prompt_usage WHERE user_id = ? AND task = ?",
            (user_id, task),
        )
        return [dict(r) for r in rows]

    def _choose_one(self, user_id: int, task: str, items: list[dict]) -> dict:
        chosen = self._rank(user_id, task, items)[0]
        self.record_usage(user_id, chosen, task)
        return chosen

    def _choose_many(self, user_id: int, task: str, items: list[dict], count: int) -> list[dict]:
        ranked = self._rank(user_id, task, items)
        selected = []
        used_keys = []
        for item in ranked:
            text = item.get("prompt") or item.get("title") or json.dumps(item)
            if any(meaning_overlap(text, prev) >= 0.72 for prev in used_keys):
                continue
            selected.append(item)
            used_keys.append(text)
            self.record_usage(user_id, item, task)
            if len(selected) >= count:
                break
        return selected or ranked[:count]

    def _rank(self, user_id: int, task: str, items: list[dict]) -> list[dict]:
        history = self._history(user_id, task)
        used_ids = {h["prompt_id"] for h in history}
        used_meanings = [h["meaning_key"] for h in history]

        def score(item: dict) -> tuple:
            text = item.get("prompt") or item.get("title") or item.get("id", "")
            overlap = max((meaning_overlap(text, m) for m in used_meanings), default=0.0)
            used = 1 if item.get("id") in used_ids else 0
            return (used, overlap, random.random())

        return sorted(items, key=score)


def _load(name: str) -> dict:
    path = DATA_DIR / name
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
