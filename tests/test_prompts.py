from ai.prompts import PromptBank, meaning_overlap
from tests.conftest import signup


def test_semantic_overlap_detects_paraphrase():
    a = "What are the advantages of recycling plastic?"
    b = "What are the advantages of recycling plastic bottles?"
    c = "Describe a holiday you enjoyed last year."
    assert meaning_overlap(a, b) >= 0.5
    assert meaning_overlap(a, c) < 0.4


def test_prompt_bank_avoids_immediate_repeat(client, app):
    signup(client)
    with app.app_context():
        bank = PromptBank()
        first = bank.choose_roleplay(1)
        second = bank.choose_roleplay(1)
        assert first["id"] != second["id"]


def test_roleplay_bank_has_topic_variety():
    bank = PromptBank()
    cards = bank.roleplay["cards"]
    ids = {card["id"] for card in cards}
    topics = {card["topic_area"] for card in cards}
    assert len(cards) >= 16
    assert len(ids) == len(cards)
    for required in ("Education", "Travel and tourism", "The environment", "Sport and leisure", "Food and drink"):
        assert required in topics
