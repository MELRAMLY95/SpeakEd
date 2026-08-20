from ai.prompts import PromptBank, meaning_overlap
from tests.conftest import signup


def test_semantic_overlap_detects_paraphrase():
    a = "What are the advantages of recycling?"
    b = "What are the benefits of recycling?"
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
