"""Tests for Step 14: the agent loop (provider layer, system prompt, run_turn, history trimming)."""

import json
import re
import sqlite3
from pathlib import Path

import httpx
import pytest

import app.tools  # noqa: F401  (fills the tool registry)
from app.agent import loop
from app.agent.loop import MAX_TOKENS, run_turn
from app.agent.prompt import SYSTEM_PROMPT
from app.agent.provider import AIReply, AIUnavailable, OpenRouterProvider, QuotaReached
from app.refusals import REFUSALS, Refusal
from app.store import ChatStore
from app.tools.base import tool_specs_for_ai
from tests.fakes import FakeProvider

AGENT_MD = Path(__file__).resolve().parent.parent / "docs" / "agent.md"
PLAN_MD = Path(__file__).resolve().parent.parent / "docs" / "implementation-plan.md"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-sonnet-5.5"


# ---------------------------------------------------------------- helpers


def text_reply(text, model="test/model", input_tokens=100, output_tokens=20, cost_usd=0.001):
    """An AI reply with final text and no tool requests."""
    return AIReply(
        text=text,
        tool_calls=None,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def tool_reply(calls, model="test/model", input_tokens=100, output_tokens=20, cost_usd=0.001):
    """An AI reply that asks for tools. `calls` = [(id, name, args), ...]."""
    return AIReply(
        text=None,
        tool_calls=[{"id": i, "name": n, "args": a} for i, n, a in calls],
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )


def info_call(call_id):
    """A request for data_info, which needs no settings and always works on the tiny data."""
    return (call_id, "data_info", {})


def messages_of(provider, call_index):
    return provider.calls[call_index][0]


def roles(messages):
    return [m["role"] for m in messages]


def assert_steps_valid(steps):
    """The saved history is safe to send again (P59).

    Every assistant tool request is followed right away by exactly its results, in the
    order asked; no tool result without a request; every turn ends with assistant text.
    """
    i = 0
    while i < len(steps):
        step = steps[i]
        if step.role == "assistant" and step.tool_calls:
            ids = [c["id"] for c in step.tool_calls]
            results = steps[i + 1 : i + 1 + len(ids)]
            assert [s.role for s in results] == ["tool"] * len(ids), f"step {step.seq}: results missing"
            assert [s.tool_call_id for s in results] == ids
            i += 1 + len(ids)
            continue
        assert step.role != "tool", f"step {step.seq}: tool result without a request"
        if step.role == "user" and i > 0:
            before = steps[i - 1]
            assert before.role == "assistant" and not before.tool_calls and before.content, (
                f"step {step.seq}: the turn before did not end with assistant text"
            )
        i += 1
    last = steps[-1]
    assert last.role == "assistant" and not last.tool_calls and last.content


def assert_messages_valid(messages):
    """The same rules for a message list sent to the AI (P55 format)."""
    assert messages[0]["role"] == "system"
    i = 1
    while i < len(messages):
        m = messages[i]
        if m["role"] == "assistant" and m.get("tool_calls"):
            ids = [c["id"] for c in m["tool_calls"]]
            results = messages[i + 1 : i + 1 + len(ids)]
            assert [r["role"] for r in results] == ["tool"] * len(ids)
            assert [r["tool_call_id"] for r in results] == ids
            i += 1 + len(ids)
            continue
        assert m["role"] != "tool", "tool message without a request"
        i += 1


def events_from_steps(steps, first_seq):
    """Rebuild tool_events from the saved steps of one turn (P64)."""
    results = {s.tool_call_id: json.loads(s.content) for s in steps if s.role == "tool" and s.seq >= first_seq}
    events = []
    for s in steps:
        if s.seq >= first_seq and s.role == "assistant" and s.tool_calls:
            for c in s.tool_calls:
                events.append({"id": c["id"], "name": c["name"], "args": c["args"], "result": results[c["id"]]})
    return events


def count_rows(path, table):
    con = sqlite3.connect(path)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


# ------------------------------------------------- 1. answer without tools


def test_answer_without_tools(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider([text_reply("Hello, ask me about US airports.")])

    result = run_turn(store, tiny_db, provider, None, "Hi")

    assert result.answer == "Hello, ask me about US airports."
    assert result.refusal is None
    assert result.tool_events == []
    assert len(provider.calls) == 1
    steps = store.load_steps(result.chat_id)
    assert len(steps) == 2
    assert [s.role for s in steps] == ["user", "assistant"]
    assert steps[0].content == "Hi"
    assert steps[1].content == "Hello, ask me about US airports."
    assert steps[1].tool_calls is None


# ------------------------------------------------------- 2. one tool round


def test_one_tool_round(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider(
        [
            tool_reply([("t1", "airport_profile", {"airports": ["BOS"]})]),
            text_reply("BOS is a strong candidate."),
        ]
    )

    result = run_turn(store, tiny_db, provider, None, "Tell me about Boston Logan.")

    assert result.answer == "BOS is a strong candidate."
    assert result.refusal is None
    steps = store.load_steps(result.chat_id)
    assert len(steps) == 4
    assert [s.role for s in steps] == ["user", "assistant", "tool", "assistant"]
    assert steps[1].tool_calls == [{"id": "t1", "name": "airport_profile", "args": {"airports": ["BOS"]}}]
    assert steps[2].tool_call_id == "t1"

    # The tool really ran on the tiny data: the saved result has data and about.
    saved = json.loads(steps[2].content)
    assert set(saved) == {"data", "about"}
    assert [a["iata"] for a in saved["data"]["airports"]] == ["BOS"]
    assert set(saved["about"]) == {"data_period", "filters", "missing", "assumptions"}

    assert len(result.tool_events) == 1
    event = result.tool_events[0]
    assert event["id"] == "t1" and event["name"] == "airport_profile"
    assert event["result"] == saved

    # The AI's second call sees the tool result.
    last = messages_of(provider, 1)[-1]
    assert last["role"] == "tool" and last["tool_call_id"] == "t1"
    assert json.loads(last["content"]) == saved


# ------------------------------------------- 3. tool error goes back to AI


def test_tool_error_goes_back_to_ai(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider(
        [
            # "bogus" is not a setting of airport_profile -> run_tool returns an error.
            tool_reply([("t1", "airport_profile", {"airports": ["BOS"], "bogus": 1})]),
            tool_reply([("t2", "airport_profile", {"airports": ["BOS"]})]),
            text_reply("Here is BOS."),
        ]
    )

    result = run_turn(store, tiny_db, provider, None, "Profile BOS")

    assert result.refusal is None
    assert result.answer == "Here is BOS."
    # The AI saw the error with the allowed setting names (airport_profile has only `airports`).
    error_msg = messages_of(provider, 1)[-1]
    assert error_msg["role"] == "tool" and error_msg["tool_call_id"] == "t1"
    error = json.loads(error_msg["content"])
    assert "error" in error
    assert error["allowed"] == ["airports"]
    # ... and tried again, this time with success.
    assert [e["id"] for e in result.tool_events] == ["t1", "t2"]
    assert "error" in result.tool_events[0]["result"]
    assert "data" in result.tool_events[1]["result"]
    steps = store.load_steps(result.chat_id)
    assert [s.role for s in steps] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]


def test_unreadable_tool_settings_go_back_to_ai(tiny_db, tmp_chat_path):
    # P56: the provider keeps arguments that are not JSON as raw text; run_tool refuses them.
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider(
        [
            tool_reply([("t1", "airport_profile", "{not json")]),
            text_reply("Sorry, let me try differently."),
        ]
    )

    result = run_turn(store, tiny_db, provider, None, "Profile BOS")

    assert result.refusal is None
    assert len(result.tool_events) == 1
    error = result.tool_events[0]["result"]
    assert "name/value pairs" in error["error"]
    last = messages_of(provider, 1)[-1]
    assert last["role"] == "tool" and last["tool_call_id"] == "t1"
    assert json.loads(last["content"]) == error
    assert_steps_valid(store.load_steps(result.chat_id))


# ------------------------------------------------- 4. stops after 5 rounds


def test_stops_after_5_rounds(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    # 6 replies that all ask for a tool; the 6th must not run (P57).
    script = [tool_reply([info_call(f"t{n}")]) for n in range(1, 6)]
    script.append(tool_reply([info_call("sixth-request")]))
    provider = FakeProvider(script)

    result = run_turn(store, tiny_db, provider, None, "Loop forever")

    assert result.refusal == Refusal("too_many_steps", REFUSALS["too_many_steps"])
    assert result.answer == ""
    assert len(provider.calls) == 6  # 5 rounds + the reply after round 5
    assert [e["id"] for e in result.tool_events] == ["t1", "t2", "t3", "t4", "t5"]

    steps = store.load_steps(result.chat_id)
    # user + 5 x (assistant request + tool result) + final refusal text = 12
    assert len(steps) == 12
    assert all("sixth-request" not in json.dumps(s.tool_calls) for s in steps)
    assert all(s.tool_call_id != "sixth-request" for s in steps)
    last = steps[-1]
    assert last.role == "assistant"
    assert last.content == REFUSALS["too_many_steps"]
    assert last.tool_calls is None
    assert last.model is None and last.input_tokens is None and last.output_tokens is None
    assert last.cost_usd is None
    assert_steps_valid(steps)


def test_several_tools_in_one_reply_count_as_one_round(tiny_db, tmp_chat_path):
    # P57: round 1 asks for 3 tools, rounds 2-5 ask for 1 each; 5 rounds are allowed.
    store = ChatStore(tmp_chat_path)
    script = [
        tool_reply(
            [
                ("a1", "data_info", {}),
                ("a2", "airport_profile", {"airports": ["BOS"]}),
                ("a3", "data_info", {}),
            ]
        )
    ]
    script += [tool_reply([info_call(f"b{n}")]) for n in range(2, 6)]
    script.append(text_reply("Done."))
    provider = FakeProvider(script)

    result = run_turn(store, tiny_db, provider, None, "Many tools")

    assert result.refusal is None
    assert result.answer == "Done."
    assert len(provider.calls) == 6
    assert [e["id"] for e in result.tool_events] == ["a1", "a2", "a3", "b2", "b3", "b4", "b5"]
    steps = store.load_steps(result.chat_id)
    # user + (request + 3 results) + 4 x (request + result) + answer = 1 + 4 + 8 + 1
    assert len(steps) == 14
    # The tools ran in the order asked.
    assert [s.tool_call_id for s in steps[2:5]] == ["a1", "a2", "a3"]
    assert_steps_valid(steps)


# ------------------------------------------------------------- 5. chat IDs


def test_no_chat_id_starts_new_chat(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)

    first = run_turn(store, tiny_db, FakeProvider([text_reply("One.")]), None, "Q1")
    second = run_turn(store, tiny_db, FakeProvider([text_reply("Two.")]), None, "Q2")

    assert store.exists(first.chat_id)
    assert len(first.chat_id) == 36  # str(uuid4()) (P43)
    assert first.chat_id != second.chat_id
    assert len(store.load_steps(first.chat_id)) == 2
    assert len(store.load_steps(second.chat_id)) == 2


def test_unknown_chat_id_refused(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider([])

    result = run_turn(store, tiny_db, provider, "no-such-chat", "Hello?")

    assert result.refusal == Refusal("chat_not_found", REFUSALS["chat_not_found"])
    assert result.answer == ""
    assert result.chat_id == "no-such-chat"
    assert result.tool_events == []
    assert provider.calls == []  # the AI is never called (P58)
    assert not store.exists("no-such-chat")
    assert count_rows(tmp_chat_path, "conversations") == 0
    assert count_rows(tmp_chat_path, "messages") == 0


# ------------------------------------------------------- 6. follow-up turn


def test_follow_up_sees_earlier_tool_result(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    first = run_turn(
        store,
        tiny_db,
        FakeProvider(
            [
                tool_reply([("t1", "airport_profile", {"airports": ["BOS"]})]),
                text_reply("BOS scores well."),
            ]
        ),
        None,
        "How is BOS?",
    )
    provider = FakeProvider([text_reply("With more weight on growth, BOS still scores well.")])

    second = run_turn(store, tiny_db, provider, first.chat_id, "What if growth matters more?")

    assert second.chat_id == first.chat_id
    assert second.refusal is None
    assert second.tool_events == []  # only this turn's tool calls (P64)
    sent = messages_of(provider, 0)
    assert roles(sent) == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert sent[1]["content"] == "How is BOS?"
    assert sent[3]["tool_call_id"] == "t1"
    assert json.loads(sent[3]["content"]) == first.tool_events[0]["result"]
    assert sent[4]["content"] == "BOS scores well."
    assert sent[5]["content"] == "What if growth matters more?"
    steps = store.load_steps(first.chat_id)
    assert len(steps) == 6
    assert_steps_valid(steps)


# ------------------------------------------------------- 7. trimming (P60)


def test_history_char_limit_is_60000():
    assert loop.HISTORY_CHAR_LIMIT == 60_000  # P60


def test_trimming_drops_oldest_whole_turns(tiny_db, tmp_chat_path, monkeypatch):
    store = ChatStore(tmp_chat_path)
    # Turn 1: small. Turn 2: very big (20,000 characters). Turn 3: small, with a tool round.
    t1 = run_turn(store, tiny_db, FakeProvider([text_reply("Answer one.")]), None, "Question one")
    chat = t1.chat_id
    run_turn(store, tiny_db, FakeProvider([text_reply("Answer two.")]), chat, "B" * 20_000)
    run_turn(
        store,
        tiny_db,
        FakeProvider([tool_reply([info_call("t3")]), text_reply("Answer three.")]),
        chat,
        "Question three",
    )
    saved_before = len(store.load_steps(chat))  # 2 + 2 + 4 = 8

    # The limit is far above turns 1 + 3 + the current one (a few thousand characters,
    # the data_info result is the biggest part) and far below anything holding turn 2.
    # Correct: drop turn 1 (oldest), still over, drop turn 2, keep turn 3 whole.
    monkeypatch.setattr(loop, "HISTORY_CHAR_LIMIT", 12_000)
    provider = FakeProvider([text_reply("Answer four.")])
    run_turn(store, tiny_db, provider, chat, "Question four")

    sent = messages_of(provider, 0)
    assert roles(sent) == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert sent[1]["content"] == "Question three"
    assert sent[2]["tool_calls"][0]["id"] == "t3"
    assert sent[3]["tool_call_id"] == "t3"  # the request and its result are kept together
    assert sent[5]["content"] == "Question four"
    assert all(m.get("content") not in ("Question one", "B" * 20_000) for m in sent)
    assert_messages_valid(sent)

    # Nothing was deleted from the store.
    assert len(store.load_steps(chat)) == saved_before + 2


def test_current_turn_never_dropped(tiny_db, tmp_chat_path, monkeypatch):
    store = ChatStore(tmp_chat_path)
    first = run_turn(
        store,
        tiny_db,
        FakeProvider([tool_reply([info_call("old")]), text_reply("Old answer.")]),
        None,
        "Old question",
    )
    monkeypatch.setattr(loop, "HISTORY_CHAR_LIMIT", 10)  # smaller than any turn
    provider = FakeProvider([tool_reply([info_call("new")]), text_reply("New answer.")])

    result = run_turn(store, tiny_db, provider, first.chat_id, "C" * 500)

    assert result.answer == "New answer."
    # First call: only the current question; the old turn (with its tool pair) is left out.
    assert roles(messages_of(provider, 0)) == ["system", "user"]
    assert messages_of(provider, 0)[1]["content"] == "C" * 500
    # Second call: the current turn whole, with its own tool request and result.
    second = messages_of(provider, 1)
    assert roles(second) == ["system", "user", "assistant", "tool"]
    assert second[2]["tool_calls"][0]["id"] == "new"
    assert second[3]["tool_call_id"] == "new"
    assert all(m.get("tool_call_id") != "old" for m in second)
    assert_messages_valid(second)
    assert len(store.load_steps(first.chat_id)) == 8  # 4 old + 4 new, nothing deleted


# ------------------------------------------- 8. AI unavailable / quota


def test_quota_reached_gives_ai_unavailable_refusal(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider([QuotaReached("spend cap reached")])

    result = run_turn(store, tiny_db, provider, None, "Rank New England airports")

    assert result.refusal == Refusal("ai_unavailable", REFUSALS["ai_unavailable"])
    assert result.answer == ""
    steps = store.load_steps(result.chat_id)
    # P58/P59: the user step was saved first, then the refusal as the final assistant text.
    assert [s.role for s in steps] == ["user", "assistant"]
    assert steps[1].content == REFUSALS["ai_unavailable"]
    assert steps[1].model is None and steps[1].cost_usd is None


def test_ai_unavailable_mid_turn_keeps_history_valid(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider([tool_reply([info_call("t1")]), AIUnavailable("timeout")])

    result = run_turn(store, tiny_db, provider, None, "Describe the data")

    assert result.refusal == Refusal("ai_unavailable", REFUSALS["ai_unavailable"])
    assert result.answer == ""
    assert [e["id"] for e in result.tool_events] == ["t1"]
    steps = store.load_steps(result.chat_id)
    assert [s.role for s in steps] == ["user", "assistant", "tool", "assistant"]
    assert steps[-1].content == REFUSALS["ai_unavailable"]
    assert_steps_valid(steps)

    # Replay: the next turn sends a valid history.
    replay = FakeProvider([text_reply("Back again.")])
    again = run_turn(store, tiny_db, replay, result.chat_id, "Try again")
    assert again.answer == "Back again."
    sent = messages_of(replay, 0)
    assert roles(sent) == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert_messages_valid(sent)
    assert_steps_valid(store.load_steps(result.chat_id))


def test_replay_after_too_many_steps(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    script = [tool_reply([info_call(f"t{n}")]) for n in range(1, 6)]
    script.append(tool_reply([info_call("sixth-request")]))
    first = run_turn(store, tiny_db, FakeProvider(script), None, "Loop forever")
    assert first.refusal.cause == "too_many_steps"

    replay = FakeProvider([text_reply("A narrower answer.")])
    again = run_turn(store, tiny_db, replay, first.chat_id, "Narrower question")

    assert again.refusal is None
    sent = messages_of(replay, 0)
    # system + user + 5 x (request + result) + refusal text + new user = 14
    assert len(sent) == 14
    assert sent[-2] == {"role": "assistant", "content": REFUSALS["too_many_steps"]}
    assert "sixth-request" not in json.dumps(sent)
    assert_messages_valid(sent)
    assert_steps_valid(store.load_steps(first.chat_id))


# ------------------------------------------------- 9. model, tokens, cost


def test_model_tokens_cost_saved(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider(
        [
            tool_reply([info_call("t1")], model="m-one", input_tokens=1840, output_tokens=210, cost_usd=0.0031),
            text_reply("Done.", model="m-two", input_tokens=2000, output_tokens=50, cost_usd=None),
        ]
    )

    result = run_turn(store, tiny_db, provider, None, "Describe the data")

    steps = store.load_steps(result.chat_id)
    user, request, tool, answer = steps
    assert (request.model, request.input_tokens, request.output_tokens) == ("m-one", 1840, 210)
    assert request.cost_usd == pytest.approx(0.0031)
    assert (answer.model, answer.input_tokens, answer.output_tokens, answer.cost_usd) == ("m-two", 2000, 50, None)
    for step in (user, tool):
        assert step.model is None and step.input_tokens is None
        assert step.output_tokens is None and step.cost_usd is None


# ------------------------------------------------------ 10. system prompt


def _rules_from_agent_md():
    """The numbered rules under '## Rules in the system prompt' in docs/agent.md."""
    rules, inside = [], False
    for line in AGENT_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Rules in the system prompt"
            continue
        match = re.match(r"^\d+\.\s+(.+)$", line.strip())
        if inside and match:
            rules.append(match.group(1).strip())
    return rules


def test_system_prompt_has_five_rules():
    rules = _rules_from_agent_md()
    assert len(rules) == 5
    for rule in rules:
        assert rule in SYSTEM_PROMPT, f"rule missing word for word: {rule}"
    assert REFUSALS["out_of_scope"] in SYSTEM_PROMPT  # P62


def _plan_row(decision):
    """The table row of one small decision (e.g. "P61") in docs/implementation-plan.md."""
    for line in PLAN_MD.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {decision} |"):
            return line
    raise AssertionError(f"{decision} row not found in implementation-plan.md")


def test_system_prompt_asks_for_answer_length():
    # P61: the length is asked for in the prompt; the sentence is read from the plan's P61 row.
    match = re.search(r'the system prompt also says "([^"]+)"', _plan_row("P61"))
    assert match, "P61 row does not quote the prompt sentence"
    sentence = match.group(1)
    assert sentence == "Keep each answer short, at most about 250 words: start with the direct answer and its key number in one or two sentences, then at most 6 short bullets."  # P103 changed the length
    assert sentence in SYSTEM_PROMPT


def test_messages_sent_in_openrouter_format(tiny_db, tmp_chat_path):
    # P55: system first; assistant tool_calls with arguments as JSON text; tool messages with tool_call_id.
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider(
        [
            tool_reply([("t1", "airport_profile", {"airports": ["BOS"]})]),
            text_reply("BOS is busy."),
        ]
    )

    result = run_turn(store, tiny_db, provider, None, "How busy is BOS?")

    first = messages_of(provider, 0)
    assert first == [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "How busy is BOS?"},
    ]
    second = messages_of(provider, 1)
    assert roles(second) == ["system", "user", "assistant", "tool"]
    request = second[2]
    assert "content" in request and request["content"] in (None, "")
    assert len(request["tool_calls"]) == 1
    call = request["tool_calls"][0]
    assert call["id"] == "t1" and call["type"] == "function"
    assert call["function"]["name"] == "airport_profile"
    assert isinstance(call["function"]["arguments"], str)
    assert json.loads(call["function"]["arguments"]) == {"airports": ["BOS"]}
    tool = second[3]
    assert set(tool) == {"role", "tool_call_id", "content"}
    assert tool["tool_call_id"] == "t1"
    assert json.loads(tool["content"]) == result.tool_events[0]["result"]

    # A text-only assistant message has no tool_calls key ("only when there are some").
    follow = FakeProvider([text_reply("Sure.")])
    run_turn(store, tiny_db, follow, result.chat_id, "Thanks")
    answer = messages_of(follow, 0)[4]
    assert answer == {"role": "assistant", "content": "BOS is busy."}


def test_out_of_scope_answer_becomes_refusal(tiny_db, tmp_chat_path):
    # P63: the AI's final text, spaces at the ends removed, equals the out_of_scope sentence.
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider([text_reply("  " + REFUSALS["out_of_scope"] + "\n")])

    result = run_turn(store, tiny_db, provider, None, "Write me a poem")

    assert result.refusal == Refusal("out_of_scope", REFUSALS["out_of_scope"])
    assert result.answer == ""
    assert len(store.load_steps(result.chat_id)) == 2


def test_answer_quoting_out_of_scope_sentence_is_not_a_refusal(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    text = "About BOS: it is in New England. " + REFUSALS["out_of_scope"]
    provider = FakeProvider([text_reply(text)])

    result = run_turn(store, tiny_db, provider, None, "Tell me about BOS and a poem")

    assert result.refusal is None
    assert result.answer == text


# ------------------------------------------------ 11/12. what each call sends


def test_max_tokens_sent(tiny_db, tmp_chat_path):
    # P61 (changed 2026-10-31): 4,000 tokens leaves room for a reasoning model's hidden thinking.
    assert MAX_TOKENS == 4000
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider([tool_reply([info_call("t1")]), text_reply("Done.")])

    run_turn(store, tiny_db, provider, None, "Describe the data")

    assert [call[2] for call in provider.calls] == [4000, 4000]


def test_tool_list_sent_matches_registry(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    provider = FakeProvider([tool_reply([info_call("t1")]), text_reply("Done.")])

    run_turn(store, tiny_db, provider, None, "Describe the data")

    expected = tool_specs_for_ai()
    assert len(provider.calls) == 2
    for _, tools, _ in provider.calls:
        assert tools == expected


# ------------------------------------------------------- P64 tool_events


def test_tool_events_shape_and_rebuilt_from_steps(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    first = run_turn(store, tiny_db, FakeProvider([text_reply("Hi.")]), None, "Hello")
    provider = FakeProvider(
        [
            tool_reply([("p1", "airport_profile", {"airports": ["Boston"]}), info_call("i1")]),
            text_reply("Boston is BOS."),
        ]
    )

    result = run_turn(store, tiny_db, provider, first.chat_id, "Profile Boston")

    assert [e["id"] for e in result.tool_events] == ["p1", "i1"]
    for event in result.tool_events:
        assert set(event) == {"id", "name", "args", "result"}
    profile = result.tool_events[0]
    assert profile["name"] == "airport_profile"
    assert profile["args"] == {"airports": ["Boston"]}  # what the AI asked for
    # "Boston" is an exact city -> only BOS (P25 rule 3).
    assert [a["iata"] for a in profile["result"]["data"]["airports"]] == ["BOS"]
    info = result.tool_events[1]
    # TINY_DATA.md: 4 rows in data_sources, 7 airports.
    assert len(info["result"]["data"]["sources"]) == 4
    assert info["result"]["data"]["scope"]["airports"] == 7

    steps = store.load_steps(result.chat_id)
    # This turn starts at step 3 (turn 1 = steps 1-2).
    assert events_from_steps(steps, first_seq=3) == json.loads(json.dumps(result.tool_events))


# ------------------------------------------------- P68 cut-off answers


def _cut_off_note_from_plan():
    """The CUT_OFF_NOTE sentence as written in the plan's P68 row."""
    match = re.search(r'`CUT_OFF_NOTE` \(a constant in `loop\.py`: "([^"]+)"\)', _plan_row("P68"))
    assert match, "P68 row does not quote the CUT_OFF_NOTE sentence"
    return match.group(1)


def test_aireply_cut_off_defaults_to_false():
    # P68: built without cut_off (as every older test does) -> False.
    reply = text_reply("Hello.")
    assert reply.cut_off is False


def test_cut_off_answer_gets_note(tiny_db, tmp_chat_path):
    assert loop.CUT_OFF_NOTE == _cut_off_note_from_plan()
    store = ChatStore(tmp_chat_path)
    text = "BOS, PVD and MHT are the strongest New England candidates because"
    reply = AIReply(
        text=text, tool_calls=None, model="test/model", input_tokens=100, output_tokens=4000, cost_usd=0.002,
        cut_off=True,
    )
    provider = FakeProvider([reply])

    result = run_turn(store, tiny_db, provider, None, "Which New England airports should we expand?")

    expected = text + "\n\n" + loop.CUT_OFF_NOTE  # the note after a blank line
    assert result.answer == expected
    assert result.refusal is None  # a cut-off answer is not a refusal
    steps = store.load_steps(result.chat_id)
    assert [s.role for s in steps] == ["user", "assistant"]
    assert steps[-1].content == expected
    assert steps[-1].tool_calls is None


def test_not_cut_off_answer_has_no_note(tiny_db, tmp_chat_path):
    store = ChatStore(tmp_chat_path)
    reply = AIReply(
        text="BOS is busy.", tool_calls=None, model="test/model", input_tokens=100, output_tokens=20,
        cost_usd=0.001, cut_off=False,
    )

    result = run_turn(store, tiny_db, FakeProvider([reply]), None, "How busy is BOS?")

    assert result.answer == "BOS is busy."
    assert result.refusal is None
    assert store.load_steps(result.chat_id)[-1].content == "BOS is busy."


def test_cut_off_tool_request_handled_as_usual(tiny_db, tmp_chat_path):
    # P68: a cut-off reply that asks for tools still runs its tools; no note anywhere.
    store = ChatStore(tmp_chat_path)
    request = AIReply(
        text=None, tool_calls=[{"id": "t1", "name": "data_info", "args": {}}], model="test/model",
        input_tokens=100, output_tokens=4000, cost_usd=0.002, cut_off=True,
    )
    provider = FakeProvider([request, text_reply("Done.")])

    result = run_turn(store, tiny_db, provider, None, "Describe the data")

    assert result.answer == "Done."
    assert result.refusal is None
    assert [e["id"] for e in result.tool_events] == ["t1"]
    assert set(result.tool_events[0]["result"]) == {"data", "about"}  # the tool really ran
    assert len(provider.calls) == 2
    steps = store.load_steps(result.chat_id)
    assert [s.role for s in steps] == ["user", "assistant", "tool", "assistant"]
    assert steps[1].tool_calls == [{"id": "t1", "name": "data_info", "args": {}}]
    for step in steps:
        assert loop.CUT_OFF_NOTE not in (step.content or "")


# ------------------------------------------------ 13/14. OpenRouterProvider


def _mock_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_openrouter_request_shape():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "id": "gen-1",
                "model": MODEL,
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "airport_profile", "arguments": '{"airports": ["BOS"]}'},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1840, "completion_tokens": 210, "cost": 0.0031},
            },
        )

    provider = OpenRouterProvider("sk-test-key", MODEL, client=_mock_client(handler))
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "How is BOS?"}]
    tools = [{"type": "function", "function": {"name": "data_info", "description": "d", "parameters": {}}}]

    reply = provider.send(messages, tools, 1100)

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == OPENROUTER_URL
    assert request.headers["authorization"] == "Bearer sk-test-key"
    body = json.loads(request.content)
    assert set(body) == {"model", "messages", "tools", "max_tokens"}
    assert body["model"] == MODEL
    assert body["messages"] == messages  # sent unchanged
    assert body["tools"] == tools
    assert body["max_tokens"] == 1100

    assert isinstance(reply, AIReply)
    assert reply.text in (None, "")
    assert reply.tool_calls == [{"id": "call_1", "name": "airport_profile", "args": {"airports": ["BOS"]}}]
    assert reply.model == MODEL
    assert reply.input_tokens == 1840
    assert reply.output_tokens == 210
    assert reply.cost_usd == pytest.approx(0.0031)


def test_openrouter_text_reply_and_missing_usage():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [{"message": {"role": "assistant", "content": "Hello."}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},  # no cost
            },
        )

    provider = OpenRouterProvider("sk-test-key", MODEL, client=_mock_client(handler))

    reply = provider.send([{"role": "user", "content": "Hi"}], [], 1100)

    assert reply.text == "Hello."
    assert reply.tool_calls is None
    assert (reply.input_tokens, reply.output_tokens, reply.cost_usd) == (50, 5, None)


def test_openrouter_unreadable_arguments_kept_as_text():
    # P56
    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "airport_profile", "arguments": "{not json"},
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0.0},
            },
        )

    provider = OpenRouterProvider("sk-test-key", MODEL, client=_mock_client(handler))

    reply = provider.send([{"role": "user", "content": "Hi"}], [], 1100)

    assert reply.tool_calls == [{"id": "call_1", "name": "airport_profile", "args": "{not json"}]


@pytest.mark.parametrize(
    "choice_extra, expected",
    [({"finish_reason": "length"}, True), ({"finish_reason": "stop"}, False), ({}, False)],
    ids=["length", "stop", "missing"],
)
def test_openrouter_finish_reason_length_sets_cut_off(choice_extra, expected):
    # P68: finish_reason "length" = the reply stopped at max_tokens.
    def handler(request):
        choice = {"message": {"role": "assistant", "content": "BOS is"}, **choice_extra}
        return httpx.Response(
            200,
            json={"model": MODEL, "choices": [choice], "usage": {"prompt_tokens": 50, "completion_tokens": 4000}},
        )

    provider = OpenRouterProvider("sk-test-key", MODEL, client=_mock_client(handler))

    reply = provider.send([{"role": "user", "content": "Hi"}], [], 4000)

    assert reply.text == "BOS is"
    assert reply.cut_off is expected


@pytest.mark.parametrize("status", [402, 429])
def test_openrouter_402_or_429_is_quota(status):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": "limit"}})

    provider = OpenRouterProvider("sk-test-key", MODEL, client=_mock_client(handler))

    with pytest.raises(QuotaReached):
        provider.send([{"role": "user", "content": "Hi"}], [], 1100)
    assert issubclass(QuotaReached, AIUnavailable)  # P65


def _raise_timeout(request):
    raise httpx.ReadTimeout("timed out", request=request)


def _raise_network(request):
    raise httpx.ConnectError("connection refused", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, json={"error": {"message": "server error"}}),
        lambda request: httpx.Response(503, text="unavailable"),
        _raise_timeout,
        _raise_network,
        lambda request: httpx.Response(200, text="this is not JSON"),
        lambda request: httpx.Response(200, json={"model": MODEL}),  # no choices
    ],
    ids=["500", "503", "timeout", "network", "not-json", "no-choices"],
)
def test_openrouter_other_failures_are_unavailable_not_quota(handler):
    provider = OpenRouterProvider("sk-test-key", MODEL, client=_mock_client(handler))

    with pytest.raises(AIUnavailable) as caught:
        provider.send([{"role": "user", "content": "Hi"}], [], 1100)
    assert not isinstance(caught.value, QuotaReached)


@pytest.mark.parametrize("key, model", [(None, MODEL), ("", MODEL), ("sk-test-key", None), ("sk-test-key", "")])
def test_openrouter_needs_key_and_model(key, model):
    # P65: a missing key or model is an error when the provider is made.
    client = _mock_client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(ValueError):
        OpenRouterProvider(key, model, client=client)
