"""Step 13 tests: chat history in SQLite (app/store.py).

What the builder must follow (names the tests rely on)
------------------------------------------------------
app/store.py
* `ChatStore(path, now=None)`. `now` is a function that returns a
  timezone-aware datetime; None means the real UTC clock (P43).
  Tables are made with CREATE TABLE IF NOT EXISTS when ChatStore is made (P48).
* `new_chat() -> str`: `str(uuid.uuid4())` (P43).
* `exists(chat_id) -> bool`: never raises (P46).
* `add_step(chat_id, role, content, tool_calls=None, tool_call_id=None,
  model=None, input_tokens=None, output_tokens=None, cost_usd=None) -> int`:
  the step number (`seq`), 1 for the first step of a chat, then +1 (P48).
  Unknown chat -> ChatNotFound (P46). role not in user/assistant/tool ->
  ValueError (P47). content may be None (P45).
* `load_steps(chat_id) -> list[Step]` in `seq` order; [] for a chat with no
  steps; unknown chat -> ChatNotFound (P46).
* `Step`: frozen dataclass with fields seq, role, content, tool_calls,
  tool_call_id, model, input_tokens, output_tokens, cost_usd, created_at (P44).
  tool_calls comes back exactly as given (a list of dicts) or None.
* Tables as schema.md part 2: `conversations(id, created_at, last_active_at)`,
  times stored as UTC ISO-8601 text (`datetime.isoformat()`, P43).

Every test uses a chat file inside pytest's tmp_path (the `tmp_chat_path`
fixture), never the repo folder. No network, no AI.
"""

import dataclasses
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest

from app.store import ChatNotFound, ChatStore, Step


class FakeClock:
    """A clock the test moves by hand. Calling it gives the current time."""

    def __init__(self, start):
        self.current = start

    def __call__(self):
        return self.current


def _utc(hour, minute):
    return datetime(2026, 10, 30, hour, minute, tzinfo=timezone.utc)


# The 4-step SFO example from schema.md part 2.
SFO_QUESTION = "What is the unmet flight demand at SFO and why?"
SFO_TOOL_CALLS = [{"id": "t1", "name": "unmet_demand", "args": {"airports": ["SFO"]}}]
SFO_TOOL_RESULT = '{"data": {"iata": "SFO"}, "about": {"data_period": "2025"}}'
SFO_ANSWER = "SFO is short of about 150,000 to 1,060,000 seats a year ..."


def _save_sfo_example(store, chat_id):
    """Save the 4 SFO steps; return the 4 step numbers add_step gave back."""
    return [
        store.add_step(chat_id, "user", SFO_QUESTION),
        store.add_step(chat_id, "assistant", None, tool_calls=SFO_TOOL_CALLS),
        store.add_step(chat_id, "tool", SFO_TOOL_RESULT, tool_call_id="t1"),
        store.add_step(chat_id, "assistant", SFO_ANSWER),
    ]


def _read_conversation_row(path, chat_id):
    """Read (created_at, last_active_at) straight from the conversations table."""
    con = sqlite3.connect(path)
    try:
        return con.execute(
            "SELECT created_at, last_active_at FROM conversations WHERE id = ?",
            (chat_id,),
        ).fetchone()
    finally:
        con.close()


# 1
def test_new_chat_id_is_long_and_random(tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    first = store.new_chat()
    second = store.new_chat()

    assert isinstance(first, str)
    # uuid4 text: 32 hex digits + 4 dashes = 36 characters (P43).
    assert len(first) >= 32
    assert len(first) == 36
    assert first != second
    # It parses as a version-4 (random) UUID and is in the standard text form.
    parsed = uuid.UUID(first)
    assert parsed.version == 4
    assert str(parsed) == first
    assert store.exists(first)
    assert store.exists(second)


# 2
def test_steps_load_in_order(tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    chat_id = store.new_chat()

    numbers = _save_sfo_example(store, chat_id)
    assert numbers == [1, 2, 3, 4]

    steps = store.load_steps(chat_id)
    assert all(isinstance(s, Step) for s in steps)
    assert [s.seq for s in steps] == [1, 2, 3, 4]
    assert [s.role for s in steps] == ["user", "assistant", "tool", "assistant"]
    assert [s.content for s in steps] == [SFO_QUESTION, None, SFO_TOOL_RESULT, SFO_ANSWER]
    # Only step 2 asks for tools; only step 3 answers one.
    assert [s.tool_calls for s in steps] == [None, SFO_TOOL_CALLS, None, None]
    assert [s.tool_call_id for s in steps] == [None, None, "t1", None]


# 3
def test_tool_request_and_result_stay_linked(tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    chat_id = store.new_chat()
    two_calls = [
        {"id": "t1", "name": "airport_profile", "args": {"airports": ["LAX"]}},
        {"id": "t2", "name": "airport_profile", "args": {"airports": ["SNA"]}},
    ]
    store.add_step(chat_id, "user", "Compare congestion at LAX and SNA.")
    store.add_step(chat_id, "assistant", None, tool_calls=two_calls)
    store.add_step(chat_id, "tool", '{"data": "LAX"}', tool_call_id="t1")
    store.add_step(chat_id, "tool", '{"data": "SNA"}', tool_call_id="t2")

    request, result_1, result_2 = store.load_steps(chat_id)[1:]
    # The request comes back exactly as given: a list of dicts, same order.
    assert request.tool_calls == two_calls
    assert isinstance(request.tool_calls, list)
    # Each result points at one request id, and its content is its own.
    request_ids = [call["id"] for call in request.tool_calls]
    assert [result_1.tool_call_id, result_2.tool_call_id] == ["t1", "t2"]
    assert result_1.tool_call_id in request_ids
    assert result_2.tool_call_id in request_ids
    assert result_1.content == '{"data": "LAX"}'
    assert result_2.content == '{"data": "SNA"}'


# 4
def test_cost_fields_saved(tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    chat_id = store.new_chat()
    store.add_step(chat_id, "user", "Hi")
    store.add_step(
        chat_id,
        "assistant",
        "Hello",
        model="openai/gpt-4o-mini",
        input_tokens=1840,
        output_tokens=210,
        cost_usd=0.0031,
    )
    # An assistant reply where OpenRouter gave no cost: cost stays empty.
    store.add_step(
        chat_id, "assistant", "Again", model="openai/gpt-4o-mini",
        input_tokens=1900, output_tokens=15,
    )

    user, reply, no_cost = store.load_steps(chat_id)
    assert (user.model, user.input_tokens, user.output_tokens, user.cost_usd) == (
        None, None, None, None,
    )
    assert reply.model == "openai/gpt-4o-mini"
    assert reply.input_tokens == 1840
    assert reply.output_tokens == 210
    assert reply.cost_usd == pytest.approx(0.0031)
    assert no_cost.input_tokens == 1900
    assert no_cost.output_tokens == 15
    assert no_cost.cost_usd is None


# 5
def test_unknown_chat_raises_not_found(tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    store.new_chat()  # another chat exists, but not this one
    unknown = str(uuid.uuid4())

    assert store.exists(unknown) is False
    with pytest.raises(ChatNotFound):
        store.add_step(unknown, "user", "Hello")
    with pytest.raises(ChatNotFound):
        store.load_steps(unknown)
    # The failed save left nothing behind and did not create the chat.
    assert store.exists(unknown) is False


# 6
def test_last_active_updated(tmp_chat_path):
    clock = FakeClock(_utc(11, 2))
    store = ChatStore(tmp_chat_path, now=clock)
    chat_id = store.new_chat()  # made at 11:02

    created_at, last_active_at = _read_conversation_row(tmp_chat_path, chat_id)
    # A new chat: both times are the moment it was made, 11:02 UTC.
    assert datetime.fromisoformat(created_at) == _utc(11, 2)
    assert datetime.fromisoformat(last_active_at) == _utc(11, 2)

    clock.current = _utc(11, 5)
    store.add_step(chat_id, "user", "First question")
    clock.current = _utc(11, 15)
    store.add_step(chat_id, "assistant", "Answer")

    created_at, last_active_at = _read_conversation_row(tmp_chat_path, chat_id)
    # created_at stays 11:02; last_active_at moves to the last save, 11:15.
    assert datetime.fromisoformat(created_at) == _utc(11, 2)
    assert datetime.fromisoformat(last_active_at) == _utc(11, 15)

    # Each step keeps the time it was saved: 11:05 and 11:15.
    first, second = store.load_steps(chat_id)
    assert datetime.fromisoformat(first.created_at) == _utc(11, 5)
    assert datetime.fromisoformat(second.created_at) == _utc(11, 15)


# 7
def test_survives_reopen(tmp_chat_path):
    first_store = ChatStore(tmp_chat_path)
    chat_id = first_store.new_chat()
    _save_sfo_example(first_store, chat_id)
    before = first_store.load_steps(chat_id)
    del first_store

    # A new ChatStore on the same file (as after a server restart).
    reopened = ChatStore(tmp_chat_path)
    assert reopened.exists(chat_id)
    after = reopened.load_steps(chat_id)
    assert after == before
    assert [s.seq for s in after] == [1, 2, 3, 4]
    assert after[1].tool_calls == SFO_TOOL_CALLS
    assert after[2].tool_call_id == "t1"
    assert after[3].content == SFO_ANSWER


# 8
def test_step_numbers_continue_after_reopen(tmp_chat_path):
    first_store = ChatStore(tmp_chat_path)
    chat_id = first_store.new_chat()
    _save_sfo_example(first_store, chat_id)  # steps 1-4
    del first_store

    reopened = ChatStore(tmp_chat_path)
    # A follow-up after the restart: 4 steps already saved, so 4 + 1 = 5.
    assert reopened.add_step(chat_id, "user", "And for LAX?") == 5
    assert reopened.add_step(chat_id, "assistant", "LAX ...") == 6
    assert [s.seq for s in reopened.load_steps(chat_id)] == [1, 2, 3, 4, 5, 6]


# Extra tests (decisions P44-P47)

def test_new_chat_has_no_steps(tmp_chat_path):
    # P46: a chat that exists with no steps gives [] (not an error).
    store = ChatStore(tmp_chat_path)
    chat_id = store.new_chat()
    assert store.load_steps(chat_id) == []


def test_step_numbers_are_per_chat(tmp_chat_path):
    # Each chat counts its own steps from 1.
    store = ChatStore(tmp_chat_path)
    chat_a = store.new_chat()
    chat_b = store.new_chat()
    assert store.add_step(chat_a, "user", "a1") == 1
    assert store.add_step(chat_a, "assistant", "a2") == 2
    assert store.add_step(chat_b, "user", "b1") == 1
    assert [s.content for s in store.load_steps(chat_a)] == ["a1", "a2"]
    assert [s.content for s in store.load_steps(chat_b)] == ["b1"]


def test_bad_role_raises_value_error(tmp_chat_path):
    # P47: only user, assistant and tool are allowed.
    store = ChatStore(tmp_chat_path)
    chat_id = store.new_chat()
    with pytest.raises(ValueError):
        store.add_step(chat_id, "system", "You are ...")
    assert store.load_steps(chat_id) == []


def test_step_is_frozen_dataclass_with_schema_fields(tmp_chat_path):
    # P44: the fields are the messages columns (without conversation_id).
    store = ChatStore(tmp_chat_path)
    chat_id = store.new_chat()
    store.add_step(chat_id, "user", "Hi")
    step = store.load_steps(chat_id)[0]

    assert dataclasses.is_dataclass(step)
    assert [f.name for f in dataclasses.fields(Step)] == [
        "seq", "role", "content", "tool_calls", "tool_call_id",
        "model", "input_tokens", "output_tokens", "cost_usd", "created_at",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        step.seq = 99


def test_exists_never_raises_on_odd_ids(tmp_chat_path):
    # P46: exists answers True/False, even for text that is not a UUID.
    store = ChatStore(tmp_chat_path)
    assert store.exists("") is False
    assert store.exists("not-a-real-id") is False
    assert store.exists("'; DROP TABLE conversations; --") is False
