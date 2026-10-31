"""Tests for P106: the Hebrew page asks for answers in Hebrew.

The page sends "language": "he" with each question. The backend then adds one extra
system line, so the AI writes the whole answer in Hebrew, even for an English question.
Without the field (or with "en") nothing changes.
"""

from fastapi.testclient import TestClient

import app.tools  # noqa: F401  (fills the tool registry TOOLS)
from app.agent.prompt import LANGUAGE_NOTES, SYSTEM_PROMPT
from app.agent.provider import AIReply
from app.api import create_app
from app.config import Settings
from tests.fakes import FakeProvider
from tests.fixtures.tiny_data import build_tiny_db

ORIGIN = "https://our-page.vercel.app"


def text_reply(text):
    return AIReply(text=text, tool_calls=None, model="test/model", input_tokens=10, output_tokens=5,
                   cost_usd=0.001, cut_off=False)  # fmt: skip


def make_client(tmp_path, provider):
    path = tmp_path / "tiny.duckdb"
    build_tiny_db(path)
    settings = Settings(
        airports_db=str(path),
        chat_db=str(tmp_path / "chat.sqlite"),
        openrouter_api_key="test-key",
        openrouter_model="test/model",
        allowed_origin=ORIGIN,
    )
    return TestClient(create_app(settings, provider=provider), raise_server_exceptions=False)


def system_texts(call):
    messages = call[0]
    return [m["content"] for m in messages if m["role"] == "system"]


def test_hebrew_request_adds_the_hebrew_note(tmp_path):
    provider = FakeProvider([text_reply("תשובה")])
    client = make_client(tmp_path, provider)
    r = client.post("/chat", json={"message": "Which airports are busiest?", "language": "he"})
    assert r.status_code == 200
    assert r.json()["answer"] == "תשובה"
    assert system_texts(provider.calls[0]) == [SYSTEM_PROMPT, LANGUAGE_NOTES["he"]]


def test_no_language_or_english_sends_only_the_system_prompt(tmp_path):
    provider = FakeProvider([text_reply("a"), text_reply("b")])
    client = make_client(tmp_path, provider)
    r1 = client.post("/chat", json={"message": "Hi"})
    r2 = client.post("/chat", json={"message": "Hi", "language": "en", "conversation_id": r1.json()["conversation_id"]})
    assert r2.status_code == 200
    assert system_texts(provider.calls[0]) == [SYSTEM_PROMPT]
    assert system_texts(provider.calls[1]) == [SYSTEM_PROMPT]


def test_unknown_language_is_a_bad_request_and_costs_nothing(tmp_path):
    provider = FakeProvider([])
    client = make_client(tmp_path, provider)
    for bad in ["fr", 5, None, ""]:
        r = client.post("/chat", json={"message": "Hi", "language": bad})
        assert r.status_code == 400
    assert provider.calls == []


def test_hebrew_note_says_hebrew_and_keeps_the_english_refusal_sentence():
    note = LANGUAGE_NOTES["he"]
    assert "Hebrew" in note
    assert "out of scope" in note
