"""Tests for Step 16: the backend API (app/api.py) and the tables/steps builder (app/presenters.py)."""

import importlib
import json
import logging
import sqlite3
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

import app.tools  # noqa: F401  (fills the tool registry TOOLS)
from app.agent.provider import AIProvider, AIReply, AIUnavailable
from app.config import Settings
from app.db import open_airport_db
from app.measures import MEASURES
from app.refusals import REFUSALS
from app.store import ChatStore
from app.tools.base import TOOLS, Tool, run_tool
from tests.fakes import FakeProvider
from tests.fixtures.tiny_data import build_tiny_db

ORIGIN = "https://our-page.vercel.app"
OTHER_ORIGIN = "https://someone-else.example.com"
REPLY_KEYS = {"conversation_id", "answer", "tables", "steps", "refusal"}
TABLE_KEYS = {"title", "columns", "units", "rows", "about"}
# P89: every unit a column may have.
ALLOWED_UNITS = {"text", "rank", "grade", "year", "month", "miles", "row"} | {m.unit for m in MEASURES.values()}


# ---------------------------------------------------------------- helpers
# The modules under test are imported inside the helpers (not at the top), so the file
# still loads before they exist and each test fails on its own.


def api_module():
    return importlib.import_module("app.api")


def presenters():
    return importlib.import_module("app.presenters")


def text_reply(text, cut_off=False):
    """An AI reply with final text and no tool requests."""
    return AIReply(text=text, tool_calls=None, model="test/model", input_tokens=10, output_tokens=5,
                   cost_usd=0.001, cut_off=cut_off)  # fmt: skip


def tool_reply(calls):
    """An AI reply that asks for tools. `calls` = [(id, name, args), ...]."""
    return AIReply(
        text=None,
        tool_calls=[{"id": i, "name": n, "args": a} for i, n, a in calls],
        model="test/model",
        input_tokens=10,
        output_tokens=5,
        cost_usd=0.001,
    )


class GateProvider(AIProvider):
    """A fake AI that stops and waits on one chosen call, so a turn can be kept "running".

    `block_on` is the call number (1 = first call) that waits. `entered` is set when that
    call starts; the call goes on only when the test sets `release`. No sleep: the test
    decides exactly when the AI "answers". The wait has a 10-second cap so a broken test
    can never hang forever.
    """

    def __init__(self, script, block_on):
        self.fake = FakeProvider(script)
        self.block_on = block_on
        self.entered = threading.Event()
        self.release = threading.Event()
        self.count = 0  # calls started, counted before any wait

    @property
    def calls(self):
        """One entry per call started (also the one still waiting)."""
        return [None] * self.count

    def send(self, messages, tools, max_tokens):
        self.count += 1
        if self.count == self.block_on:
            self.entered.set()
            self.release.wait(10)
        return self.fake.send(messages, tools, max_tokens)


class CrashProvider(AIProvider):
    """A fake AI that crashes with a secret-looking message (not an AIUnavailable)."""

    SECRET = "secret /Users/someone/keys/key=sk-or-abc123"

    def __init__(self):
        self.calls = 0

    def send(self, messages, tools, max_tokens):
        self.calls += 1
        raise RuntimeError(self.SECRET)


@pytest.fixture
def airports_path(tmp_path):
    """A fresh tiny airport database file."""
    path = tmp_path / "tiny.duckdb"
    build_tiny_db(path)
    return path


@pytest.fixture
def make_client(tmp_path, airports_path):
    """make_client(provider, **setting_changes) -> (TestClient, Settings).

    Settings are built explicitly (never from environment variables). The client does not
    re-raise server crashes, so a test sees what a real browser would see.
    """

    def make(provider=None, **changes):
        values = dict(
            airports_db=str(airports_path),
            chat_db=str(tmp_path / "chat.sqlite"),
            openrouter_api_key="test-key",
            openrouter_model="test/model",
            allowed_origin=ORIGIN,
        )
        values.update(changes)
        settings = Settings(**values)
        application = api_module().create_app(settings, provider=provider)
        return TestClient(application, raise_server_exceptions=False), settings

    return make


def chat_count(settings):
    """How many chats are saved in chat.sqlite."""
    con = sqlite3.connect(settings.chat_db)
    try:
        return con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    finally:
        con.close()


def tool_result(settings, name, args):
    """Run the tool directly on the same tiny database, as the agent loop would."""
    con = open_airport_db(settings.airports_db)
    try:
        return json.loads(json.dumps(run_tool(con, name, args)))
    finally:
        con.close()


def event(con, name, args, call_id="c1"):
    """One tool event in the shape run_turn returns (P64): the real run_tool result."""
    return {"id": call_id, "name": name, "args": args, "result": json.loads(json.dumps(run_tool(con, name, args)))}


def refusal_of(cause):
    return {"cause": cause, "message": REFUSALS[cause]}


def assert_refusal_reply(body, cause, conversation_id):
    """A refusal reply: the five keys, empty answer/tables/steps, the fixed message."""
    assert set(body) == REPLY_KEYS
    assert body["conversation_id"] == conversation_id
    assert body["answer"] == ""
    assert body["tables"] == []
    assert body["steps"] == []
    assert body["refusal"] == refusal_of(cause)


def post_until_not_busy(client, chat_id, message, seconds=5):
    """Send `message` until it is no longer refused as busy (the turn thread releases the
    chat's lock a moment after it finishes). A busy refusal costs nothing: no AI call."""
    deadline = time.monotonic() + seconds
    while True:
        r = client.post("/chat", json={"conversation_id": chat_id, "message": message})
        refusal = r.json().get("refusal")
        if not (refusal and refusal.get("cause") == "busy") or time.monotonic() > deadline:
            return r
        time.sleep(0.02)


def rank_expected(result):
    """Columns, units and rows of a rank_airports table, built from the tool result by the
    P90 rule. "Region rank" only when the rows have `region_rank` (added by Step 15)."""
    data = result["data"]
    rows = data["airports"]
    has_region = bool(rows) and "region_rank" in rows[0]
    measure = MEASURES[data["sort_by"]]
    columns = ["National rank"] + (["Region rank"] if has_region else []) + [
        "Code", "Name", "State", "Size", measure.label, "Grade"]  # fmt: skip
    units = ["rank"] + (["rank"] if has_region else []) + ["text", "text", "text", "text", measure.unit, "grade"]
    expected_rows = []
    for a in rows:
        row = [a["national_rank"]] + ([a["region_rank"]] if has_region else [])
        row += [a["iata"], a["name"], a["state"], a["size"], a["value"], a["grade"]]
        if data["sort_by"] == "score":
            row += [a["demand_score"], a["strain_score"]]
        expected_rows.append(row)
    if data["sort_by"] == "score":
        columns += ["Demand score", "Strain score"]
        units += ["points", "points"]
    return columns, units, expected_rows


# ---------------------------------------------------------------- 1. health


def test_health_ok(make_client):
    client, _ = make_client(FakeProvider([]))
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_fails_without_airport_db(make_client, tmp_path):
    # P80: create_app never raises, even when the airport file is missing.
    client, _ = make_client(FakeProvider([]), airports_db=str(tmp_path / "missing.duckdb"))
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "error"}  # no details


# ---------------------------------------------------------------- 2. first message


def test_first_message_starts_chat_and_returns_id(make_client):
    provider = FakeProvider([text_reply("Hello from the agent."), text_reply("Second answer.")])
    client, settings = make_client(provider)

    r = client.post("/chat", json={"message": "Hi"})
    assert r.status_code == 200
    body = r.json()
    chat_id = body["conversation_id"]
    # P43: a new chat ID is str(uuid4()), 36 characters.
    assert isinstance(chat_id, str) and len(chat_id) == 36
    assert str(uuid.UUID(chat_id)) == chat_id
    assert body["answer"] == "Hello from the agent."
    assert body["refusal"] is None

    store = ChatStore(settings.chat_db)
    assert store.exists(chat_id)
    assert chat_count(settings) == 1

    # The same ID continues the same chat: no new chat, 2 + 2 saved steps.
    r2 = client.post("/chat", json={"conversation_id": chat_id, "message": "And then?"})
    assert r2.status_code == 200
    assert r2.json()["conversation_id"] == chat_id
    assert r2.json()["answer"] == "Second answer."
    assert chat_count(settings) == 1
    assert [s.role for s in store.load_steps(chat_id)] == ["user", "assistant", "user", "assistant"]


# ---------------------------------------------------------------- 3. reply shape


def test_reply_has_answer_tables_steps_refusal(make_client):
    provider = FakeProvider([
        tool_reply([("c1", "find_airports", {"region": "New England"}), ("c2", "data_info", {})]),
        text_reply("Here are the New England airports."),
    ])  # fmt: skip
    client, _ = make_client(provider)

    r = client.post("/chat", json={"message": "Which airports are in New England?"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == REPLY_KEYS
    assert body["answer"] == "Here are the New England airports."
    assert body["refusal"] is None
    # One table per tool: "Airports found" and "Data sources" (P90), in the order run.
    assert [t["title"] for t in body["tables"]] == ["Airports found", "Data sources"]
    for table in body["tables"]:
        assert set(table) == TABLE_KEYS
        assert len(table["units"]) == len(table["columns"])
        assert all(len(row) == len(table["columns"]) for row in table["rows"])
    # One plain-words step per tool (P88).
    assert body["steps"] == ["Looked up airports (region: New England)", "Checked which data we have"]


# ---------------------------------------------------------------- 4. table numbers


def test_table_numbers_come_from_tool_not_ai(make_client):
    args = {"region": "New England", "top_n": 2}
    provider = FakeProvider([
        tool_reply([("c1", "rank_airports", args)]),
        # The AI writes a made-up number into its text.
        text_reply("MHT is first with a score of 99.9 points."),
    ])  # fmt: skip
    client, settings = make_client(provider)

    body = client.post("/chat", json={"message": "Rank New England"}).json()
    assert "99.9" in body["answer"]  # the AI's text is passed on as it is

    result = tool_result(settings, "rank_airports", args)
    columns, units, rows = rank_expected(result)
    [table] = body["tables"]
    # P90 title: "Airports ranked by <label of sort_by> (highest first)".
    assert table["title"] == f"Airports ranked by {MEASURES['score'].label} (highest first)"
    assert table["columns"] == columns
    assert table["units"] == units
    # The rows hold the tool's own numbers, unchanged (P89) ...
    assert table["rows"] == rows
    assert table["about"] == result["about"]
    # ... and the AI's number appears nowhere in the table.
    cells = [cell for row in table["rows"] for cell in row]
    assert 99.9 not in cells
    assert "99.9" not in json.dumps(table)
    # Hand check: New England airports with 100,000+ boardings are BOS, MHT, BTV (BHB has
    # 55,000); top_n 2 keeps two of them.
    assert len(table["rows"]) == 2
    assert {row[columns.index("Code")] for row in table["rows"]} <= {"BOS", "MHT", "BTV"}


# ---------------------------------------------------------------- 5. steps


def test_steps_in_plain_words(make_client):
    provider = FakeProvider([
        tool_reply([
            ("c1", "find_airports", {"region": "New England"}),
            ("c2", "rank_airports", {"region": "New England", "top_n": 5}),
        ]),
        tool_reply([("c3", "rank_airports", {"top_n": 99})]),  # out of range: not run
        text_reply("Done."),
    ])  # fmt: skip
    client, settings = make_client(provider)

    body = client.post("/chat", json={"message": "Strong New England candidates?"}).json()
    # The error text is our own, from run_tool.
    error = tool_result(settings, "rank_airports", {"top_n": 99})["error"]
    assert body["steps"] == [
        "Looked up airports (region: New England)",  # api.md example
        "Ranked airports (region: New England; top n: 5)",  # P88 example: "_" -> space
        f"Ranked airports (top n: 99) – not run: {error}",
    ]
    # The failed tool gives no table (P89): only find + rank.
    assert len(body["tables"]) == 2


# ---------------------------------------------------------------- 6. question length


def test_message_over_1000_refused_before_ai(make_client):
    provider = FakeProvider([text_reply("Answer to the 1,000-character question.")])
    client, settings = make_client(provider)

    r = client.post("/chat", json={"message": "a" * 1001})
    assert r.status_code == 200  # refusals are HTTP 200 (P81)
    assert_refusal_reply(r.json(), "question_too_long", None)
    assert provider.calls == []  # the AI never saw it
    assert chat_count(settings) == 0  # nothing saved, no chat made

    # Exactly 1,000 characters is allowed.
    r = client.post("/chat", json={"message": "a" * 1000})
    assert r.status_code == 200
    assert r.json()["refusal"] is None
    assert r.json()["answer"] == "Answer to the 1,000-character question."
    assert len(provider.calls) == 1

    # In an existing chat, a too-long message saves no step and keeps the ID.
    chat_id = r.json()["conversation_id"]
    steps_before = len(ChatStore(settings.chat_db).load_steps(chat_id))
    r = client.post("/chat", json={"conversation_id": chat_id, "message": "b" * 1001})
    assert_refusal_reply(r.json(), "question_too_long", chat_id)
    assert len(ChatStore(settings.chat_db).load_steps(chat_id)) == steps_before
    assert len(provider.calls) == 1


# ---------------------------------------------------------------- 7. reload


def test_reload_rebuilds_tables_and_steps(make_client):
    provider = FakeProvider([
        # Turn 1: two rounds, three tools (route_mix gives two tables).
        tool_reply([("c1", "route_mix", {"airport": "ANC"}), ("c2", "rank_airports", {"top_n": 99})]),
        tool_reply([("c3", "unmet_demand", {"airports": ["BOS"]})]),
        text_reply("Half of ANC's passenger flights are long-haul."),
        # Turn 2: text only.
        text_reply("A follow-up answer."),
        # Turn 3: one tool round, then the AI is down -> ai_unavailable refusal (saved as
        # text, P59). The refusal still carries the table and step of the tool that ran (P81).
        tool_reply([("c4", "data_info", {})]),
        AIUnavailable("down"),
        # Turn 4: out of scope.
        text_reply("  " + REFUSALS["out_of_scope"] + " "),
    ])  # fmt: skip
    client, _ = make_client(provider)

    questions = ["Long-haul at ANC?", "Tell me more", "Still there?", "Write me a poem"]
    live = []
    chat_id = None
    for q in questions:
        payload = {"message": q} if chat_id is None else {"conversation_id": chat_id, "message": q}
        r = client.post("/chat", json=payload)
        assert r.status_code == 200
        live.append(r.json())
        chat_id = r.json()["conversation_id"]
    # Sanity: the live replies are what we scripted.
    assert len(live[0]["tables"]) == 2 + 2  # route_mix 2, unmet_demand 2, failed rank 0
    assert len(live[0]["steps"]) == 3
    assert live[2]["refusal"] == refusal_of("ai_unavailable")
    assert live[2]["answer"] == ""
    assert [t["title"] for t in live[2]["tables"]] == ["Data sources"]  # P81: tables of the tools that ran
    assert live[2]["steps"] == ["Checked which data we have"]
    assert live[3]["refusal"] == refusal_of("out_of_scope")
    assert live[3]["answer"] == ""

    r = client.get(f"/chat/{chat_id}")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"conversation_id", "turns", "refusal"}
    assert body["conversation_id"] == chat_id
    assert body["refusal"] is None
    assert len(body["turns"]) == 4
    # Each reloaded turn equals the live reply exactly (P91).
    for q, turn, reply in zip(questions, body["turns"], live):
        assert set(turn) == {"question", "answer", "tables", "steps", "refusal"}
        assert turn == {"question": q, "answer": reply["answer"], "tables": reply["tables"],
                        "steps": reply["steps"], "refusal": reply["refusal"]}  # fmt: skip


# ---------------------------------------------------------------- 8. unknown chat


def test_unknown_chat_gives_chat_not_found(make_client):
    provider = FakeProvider([])
    client, settings = make_client(provider)
    unknown = str(uuid.uuid4())

    r = client.post("/chat", json={"conversation_id": unknown, "message": "Hello?"})
    assert r.status_code == 200
    assert_refusal_reply(r.json(), "chat_not_found", unknown)
    assert provider.calls == []
    assert chat_count(settings) == 0

    r = client.get(f"/chat/{unknown}")
    assert r.status_code == 200
    assert r.json() == {"conversation_id": unknown, "turns": [], "refusal": refusal_of("chat_not_found")}


# ---------------------------------------------------------------- 9. busy


def test_second_message_while_busy_refused(make_client):
    # Call 1 answers turn 1 at once; call 2 (turn 2) waits until the test releases it;
    # call 3 answers the message sent after turn 2 has finished.
    provider = GateProvider(
        [text_reply("First answer."), text_reply("Slow answer."), text_reply("Third answer.")], block_on=2
    )
    client, settings = make_client(provider)
    chat_id = client.post("/chat", json={"message": "First"}).json()["conversation_id"]
    store = ChatStore(settings.chat_db)

    slow = {}
    slow_client = TestClient(client.app, raise_server_exceptions=False)  # its own client for the thread

    def send_slow():
        slow["reply"] = slow_client.post("/chat", json={"conversation_id": chat_id, "message": "Slow one"})

    thread = threading.Thread(target=send_slow)
    thread.start()
    try:
        assert provider.entered.wait(5), "the slow turn never reached the AI"
        steps_before = len(store.load_steps(chat_id))

        r = client.post("/chat", json={"conversation_id": chat_id, "message": "Double click"})
        assert r.status_code == 200
        assert_refusal_reply(r.json(), "busy", chat_id)
        assert len(provider.calls) == 2  # the busy message never reached the AI
        assert len(store.load_steps(chat_id)) == steps_before  # nothing saved
    finally:
        provider.release.set()
        thread.join(10)
    assert not thread.is_alive()

    assert slow["reply"].status_code == 200
    assert slow["reply"].json()["answer"] == "Slow answer."
    # Once the slow turn is over, the chat takes messages again.
    r = post_until_not_busy(client, chat_id, "Third")
    assert r.json()["answer"] == "Third answer."


# ---------------------------------------------------------------- 10. time limit


def test_turn_over_60_seconds_gives_internal_error(make_client, monkeypatch, caplog):
    api = api_module()
    assert api.TURN_TIMEOUT_SECONDS == 60  # P85
    monkeypatch.setattr(api, "TURN_TIMEOUT_SECONDS", 0.2)  # read at request time
    provider = GateProvider([text_reply("Late answer."), text_reply("Next answer.")], block_on=1)
    client, settings = make_client(provider)
    store = ChatStore(settings.chat_db)

    try:
        with caplog.at_level(logging.INFO, logger="app.api"):
            r = client.post("/chat", json={"message": "A slow question"})
        assert r.status_code == 500
        body = r.json()
        chat_id = body["conversation_id"]
        # P85: the reply carries the new chat's ID; tables and steps are empty.
        assert isinstance(chat_id, str) and store.exists(chat_id)
        assert_refusal_reply(body, "internal_error", chat_id)
        assert any(rec.name == "app.api" for rec in caplog.records)  # the event is logged

        # The timed-out turn is still running, so the chat is busy (P84).
        r = client.post("/chat", json={"conversation_id": chat_id, "message": "Hello?"})
        assert_refusal_reply(r.json(), "busy", chat_id)
        assert len(provider.calls) == 1
    finally:
        provider.release.set()

    # The turn finishes in the background and saves its own steps (P85, P59).
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(store.load_steps(chat_id)) < 2:
        time.sleep(0.01)
    steps = store.load_steps(chat_id)
    assert [(s.role, s.content) for s in steps] == [("user", "A slow question"), ("assistant", "Late answer.")]

    # Then the lock is released and the chat goes on.
    r = post_until_not_busy(client, chat_id, "Next")
    assert r.status_code == 200
    assert r.json()["answer"] == "Next answer."


# ---------------------------------------------------------------- 11. internal errors


def test_internal_error_hides_details(make_client, caplog):
    provider = CrashProvider()
    client, _ = make_client(provider)

    with caplog.at_level(logging.ERROR, logger="app.api"):
        r = client.post("/chat", json={"message": "Anything"})
    assert r.status_code == 500
    body = r.json()
    assert provider.calls == 1
    assert isinstance(body["conversation_id"], str)
    assert_refusal_reply(body, "internal_error", body["conversation_id"])
    # No exception text, type or path in the reply (P86).
    for secret in (CrashProvider.SECRET, "secret", "sk-or-abc123", "/Users/someone", "RuntimeError", "Traceback"):
        assert secret not in r.text
    # Full details go to the server log only.
    logged = [rec for rec in caplog.records if rec.name == "app.api" and rec.exc_info]
    assert logged, "the crash was not logged with logger.exception"


def test_tool_crash_is_internal_error(make_client, monkeypatch):
    # A tool's own crash is not caught by run_tool (P24); the API turns it into internal_error.
    def crash(con, settings):
        raise ValueError("boom at /srv/app/secret.py")

    original = TOOLS["data_info"]
    monkeypatch.setitem(TOOLS, "data_info", Tool(original.name, original.description, original.settings_model, crash))
    provider = FakeProvider([tool_reply([("c1", "data_info", {})])])
    client, _ = make_client(provider)

    r = client.post("/chat", json={"message": "Which data do you have?"})
    assert r.status_code == 500
    assert_refusal_reply(r.json(), "internal_error", r.json()["conversation_id"])
    assert "boom" not in r.text and "secret.py" not in r.text and "ValueError" not in r.text


def test_airport_db_missing_in_turn_is_internal_error(make_client, tmp_path):
    # P80: the airport database is opened per turn; if it can't open, that turn is an internal error.
    provider = FakeProvider([text_reply("never sent")])
    client, _ = make_client(provider, airports_db=str(tmp_path / "missing.duckdb"))
    r = client.post("/chat", json={"message": "Hello"})
    assert r.status_code == 500
    assert r.json()["refusal"] == refusal_of("internal_error")
    assert "missing.duckdb" not in r.text
    assert provider.calls == []


@pytest.mark.parametrize(
    "content",
    [
        b"this is not json",
        b"[1, 2, 3]",
        b"{}",  # message missing
        b'{"message": 123}',  # message not text
        b'{"message": "   "}',  # empty after removing spaces at the ends
        b'{"message": "Hi", "conversation_id": 5}',  # conversation_id not text
    ],
)
def test_bad_body_gives_400_without_details(make_client, content):
    provider = FakeProvider([])
    client, settings = make_client(provider)
    r = client.post("/chat", content=content, headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    body = r.json()
    assert_refusal_reply(body, "internal_error", None)  # P81: the five keys, no "detail"
    assert provider.calls == []
    assert chat_count(settings) == 0


# ---------------------------------------------------------------- order of checks (P82)


def test_too_long_is_checked_before_unknown_chat(make_client):
    client, _ = make_client(FakeProvider([]))
    unknown = str(uuid.uuid4())
    r = client.post("/chat", json={"conversation_id": unknown, "message": "x" * 1001})
    assert_refusal_reply(r.json(), "question_too_long", unknown)


def test_unknown_chat_is_checked_before_missing_ai(make_client):
    # No key -> no provider (P80); the unknown chat is still reported first.
    client, _ = make_client(None, openrouter_api_key=None)
    unknown = str(uuid.uuid4())
    r = client.post("/chat", json={"conversation_id": unknown, "message": "Hi"})
    assert r.status_code == 200
    assert_refusal_reply(r.json(), "chat_not_found", unknown)


def test_no_ai_key_gives_ai_unavailable_and_saves_nothing(make_client):
    # P80: no key or no model -> the app still starts; messages get ai_unavailable,
    # no chat is made and no AI is called (provider=None and no key: no real call possible).
    for changes in ({"openrouter_api_key": None}, {"openrouter_model": None}):
        client, settings = make_client(None, **changes)
        assert client.get("/health").status_code == 200
        r = client.post("/chat", json={"message": "Hi"})
        assert r.status_code == 200
        assert_refusal_reply(r.json(), "ai_unavailable", None)
        assert chat_count(settings) == 0


# ---------------------------------------------------------------- 12. CORS


def test_cors_allows_only_our_page(make_client):
    client, _ = make_client(FakeProvider([]))
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "Content-Type"}

    # Our page: allowed, on a preflight and on a simple request.
    r = client.options("/chat", headers={"Origin": ORIGIN, **preflight})
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    r = client.get("/health", headers={"Origin": ORIGIN})
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    assert "access-control-allow-credentials" not in r.headers  # no credentials (P87)

    # Any other site: no allow-origin header, so the browser blocks it.
    r = client.options("/chat", headers={"Origin": OTHER_ORIGIN, **preflight})
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/health", headers={"Origin": OTHER_ORIGIN})
    assert "access-control-allow-origin" not in r.headers


def test_cors_without_allowed_origin_allows_no_page(make_client):
    client, _ = make_client(FakeProvider([]), allowed_origin=None)
    r = client.get("/health", headers={"Origin": ORIGIN})
    assert r.status_code == 200  # curl-like calls still work
    assert "access-control-allow-origin" not in r.headers


# ---------------------------------------------------------------- presenters: steps (P88)


def test_build_steps_settings_formats(tiny_db):
    build_steps = presenters().build_steps
    events = [
        event(tiny_db, "airport_profile", {"airports": ["BOS", "LAX"]}, "c1"),  # list -> "BOS, LAX"
        event(tiny_db, "route_mix", {"airport": "ANC", "passengers_only": False}, "c2"),  # bool -> no
        event(tiny_db, "rank_airports", {"weights": {"D1": 50, "S1": 50}}, "c3"),  # dict -> "D1 50, S1 50"
        event(tiny_db, "data_info", {}, "c4"),  # no settings -> no brackets
        event(tiny_db, "unmet_demand", {"airports": ["BOS"], "target_load_factor": 0.9}, "c5"),
        event(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"], "by": "month"}, "c6"),
        event(tiny_db, "delay_causes", {"airports": ["BOS"]}, "c7"),
    ]
    assert build_steps(events) == [
        "Looked up airport profiles (airports: BOS, LAX)",
        "Split departures into groups (airport: ANC; passengers only: no)",
        "Ranked airports (weights: D1 50, S1 50)",
        "Checked which data we have",
        "Estimated unmet demand (airports: BOS; target load factor: 0.9)",
        "Looked at traffic over time (measure: passengers; airports: BOS; by: month)",
        "Looked at delay causes (airports: BOS)",
    ]
    assert build_steps([]) == []


def test_build_steps_live_status_and_true(tiny_db):
    build_steps = presenters().build_steps
    # Hand-made events (no network): the step text only reads the name, args and result.
    live = {"id": "c1", "name": "live_status", "args": {"airport": "SFO"},
            "result": {"data": {"airport": "SFO", "feed_available": True, "updated": "", "events": []},
                       "about": {"data_period": "", "filters": [], "missing": [], "assumptions": []}}}  # fmt: skip
    mix = event(tiny_db, "route_mix", {"airport": "ANC", "passengers_only": True}, "c2")
    assert build_steps([live, mix]) == [
        "Checked today's FAA status (airport: SFO)",
        "Split departures into groups (airport: ANC; passengers only: yes)",
    ]


def test_build_steps_errors_unknown_tool_and_raw_settings(tiny_db):
    build_steps = presenters().build_steps
    raw = event(tiny_db, "find_airports", '{"region": "New Eng', "c1")  # unreadable settings (P56)
    unknown = event(tiny_db, "fly_me_there", {}, "c2")
    [raw_line, unknown_line] = build_steps([raw, unknown])
    assert raw_line == f"Looked up airports (settings could not be read) – not run: {raw['result']['error']}"
    assert unknown_line.startswith('Asked for an unknown tool "fly_me_there"')


# ---------------------------------------------------------------- presenters: tables (P89, P90)


def check_shape(table):
    """Every table: the five keys, one unit per column, units from P89, rows as long as columns."""
    assert set(table) == TABLE_KEYS
    assert len(table["units"]) == len(table["columns"])
    assert set(table["units"]) <= ALLOWED_UNITS
    assert all(len(row) == len(table["columns"]) for row in table["rows"])


def test_tables_find_airports(tiny_db):
    build_tables = presenters().build_tables
    ev = event(tiny_db, "find_airports", {"region": "New England"})
    [table] = build_tables([ev])
    check_shape(table)
    assert table["title"] == "Airports found"
    assert table["columns"] == ["Code", "Name", "City", "State", "Size"]
    assert table["units"] == ["text"] * 5
    assert table["rows"] == [[a["iata"], a["name"], a["city"], a["state"], a["size"]]
                             for a in ev["result"]["data"]["airports"]]  # fmt: skip
    # Hand check: the 4 New England airports, sorted by code (P27).
    assert [row[0] for row in table["rows"]] == ["BHB", "BOS", "BTV", "MHT"]
    assert table["about"] == ev["result"]["about"]

    near = event(tiny_db, "find_airports", {"near_airport": "LAX"})
    [table] = build_tables([near])
    check_shape(table)
    assert table["columns"] == ["Code", "Name", "City", "State", "Size", "Distance (miles)"]
    assert table["units"][-1] == "miles"
    # Only SNA is within 50 miles of LAX (about 35 miles, TINY_DATA.md).
    [row] = table["rows"]
    assert row[0] == "SNA"
    assert row[-1] == near["result"]["data"]["airports"][0]["distance_mi"]


def test_tables_rank_airports_by_measure_and_order(tiny_db):
    build_tables = presenters().build_tables
    for order, words in (("highest_first", "highest first"), ("lowest_first", "lowest first")):
        ev = event(tiny_db, "rank_airports", {"sort_by": "load_factor", "order": order, "top_n": 3})
        [table] = build_tables([ev])
        check_shape(table)
        columns, units, rows = rank_expected(ev["result"])
        assert table["title"] == f"Airports ranked by {MEASURES['load_factor'].label} ({words})"
        assert table["columns"] == columns
        assert table["units"] == units  # load_factor -> "share"
        assert table["rows"] == rows
    # Hand check (TINY_DATA.md, load factor 2025): highest MHT 90%, lowest BTV 72.8%.
    high = build_tables([event(tiny_db, "rank_airports", {"sort_by": "load_factor", "top_n": 1})])[0]
    assert high["rows"][0][high["columns"].index("Code")] == "MHT"
    assert high["rows"][0][high["columns"].index(MEASURES["load_factor"].label)] == 0.9  # 1,800 / 2,000


def test_tables_airport_profile(tiny_db):
    build_tables = presenters().build_tables
    ev = event(tiny_db, "airport_profile", {"airports": ["BOS", "LAX"]})
    [table] = build_tables([ev])
    check_shape(table)
    bos, lax = ev["result"]["data"]["airports"]
    assert table["title"] == "Profile: BOS, LAX"
    assert table["columns"] == ["Measure", "Unit", "BOS", "BOS grade", "LAX", "LAX grade"]
    assert table["units"] == ["text", "text", "row", "grade", "row", "grade"]
    expected = [
        [MEASURES[name].label, MEASURES[name].unit, bos["measures"][name]["value"], bos["measures"][name]["grade"],
         lax["measures"][name]["value"], lax["measures"][name]["grade"]]
        for name in bos["measures"]
    ]  # fmt: skip
    expected += [
        ["Score", "points", bos["final_score"], None, lax["final_score"], None],
        ["Demand score", "points", bos["demand_score"], None, lax["demand_score"], None],
        ["Strain score", "points", bos["strain_score"], None, lax["strain_score"], None],
        ["National rank", "rank", bos["national_rank"], None, lax["national_rank"], None],
    ]
    assert table["rows"] == expected
    # Hand check: BOS load factor 3,168 / 4,000 = 0.792 (TINY_DATA.md).
    lf_row = next(r for r in table["rows"] if r[0] == MEASURES["load_factor"].label)
    assert lf_row[1] == "share" and lf_row[2] == 0.792


def test_tables_traffic_trend(tiny_db):
    build_tables = presenters().build_tables
    label = MEASURES["passengers"].label
    [by_year] = build_tables([event(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"]})])
    check_shape(by_year)
    assert by_year["title"] == f"{label} by year"
    assert by_year["columns"] == ["Airport or area", "Year", "Value", "Change from first year"]
    assert by_year["units"] == ["text", "year", "passengers", "share"]
    # Hand check (TINY_DATA.md): BOS 2,880 / 3,000 / 3,168; change vs 2019: 0, 120/2,880, 288/2,880 = 0.1.
    assert [r[:3] for r in by_year["rows"]] == [["BOS", 2019, 2880], ["BOS", 2024, 3000], ["BOS", 2025, 3168]]
    assert by_year["rows"][0][3] == 0
    assert by_year["rows"][1][3] == pytest.approx(120 / 2880)
    assert by_year["rows"][2][3] == pytest.approx(0.1)

    [by_month] = build_tables(
        [event(tiny_db, "traffic_trend", {"measure": "passengers", "airports": ["BOS"], "by": "month"})]
    )
    check_shape(by_month)
    assert by_month["title"] == f"{label} by month"
    assert by_month["columns"] == ["Airport or area", "Year", "Month", "Value"]
    assert by_month["units"] == ["text", "year", "month", "passengers"]
    # Hand check: 2025 July = 884 + 884 = 1,768.
    assert ["BOS", 2025, 7, 1768] in by_month["rows"]
    assert len(by_month["rows"]) == 6  # 3 years x 2 months


def test_tables_route_mix_gives_two_tables_with_long_haul_share(tiny_db):
    build_tables = presenters().build_tables
    ev = event(tiny_db, "route_mix", {"airport": "ANC"})
    tables = build_tables([ev])
    assert len(tables) == 2
    mix, groups = tables
    for t in tables:
        check_shape(t)
        assert t["about"] == ev["result"]["about"]

    assert mix["title"] == "ANC flight mix, 2025"
    assert mix["columns"] == ["Long-haul share", "International share", "Cargo share"]
    assert mix["units"] == ["share", "share", "share"]
    # Hand check (TINY_DATA.md): long-haul 20 of 40 = 0.5, international 0, cargo 50 of 90.
    [[long_haul, international, cargo]] = mix["rows"]
    assert long_haul == 0.5
    assert international == 0
    assert cargo == pytest.approx(50 / 90)
    assert cargo == ev["result"]["data"]["cargo_share"]  # raw, not rounded (P89)

    assert groups["title"] == "ANC departures by destination, 2025"
    assert groups["columns"] == ["Group", "Departures", "Seats", "Passengers",
                                 "Departures share", "Seats share", "Passengers share"]  # fmt: skip
    assert groups["units"] == ["text", "departures", "seats", "passengers", "share", "share", "share"]
    assert groups["rows"] == [
        [g["group"], g["departures"], g["seats"], g["passengers"],
         g["departures_share"], g["seats_share"], g["passengers_share"]]
        for g in ev["result"]["data"]["groups"]
    ]  # fmt: skip
    # Hand check: ATL and SEA, 20 departures each (10 x 2 months).
    assert sorted((r[0], r[1]) for r in groups["rows"]) == [("ATL", 20), ("SEA", 20)]


def test_tables_route_mix_by_airline_and_band(tiny_db):
    build_tables = presenters().build_tables
    _, groups = build_tables([event(tiny_db, "route_mix", {"airport": "ANC", "group_by": "airline"})])
    check_shape(groups)
    assert groups["title"] == "ANC departures by airline, 2025"
    assert groups["columns"][:2] == ["Group", "Airline"]
    assert sorted(r[:2] for r in groups["rows"]) == [["AS", "Alaska Airlines Inc."], ["DL", "Delta Air Lines Inc."]]

    _, bands = build_tables([event(tiny_db, "route_mix", {"airport": "ANC", "group_by": "distance_band"})])
    check_shape(bands)
    assert bands["title"] == "ANC departures by distance band, 2025"  # "_" -> space


def test_tables_delay_causes(tiny_db):
    build_tables = presenters().build_tables
    ev = event(tiny_db, "delay_causes", {"airports": ["BOS"]})
    [table] = build_tables([ev])
    check_shape(table)
    assert table["title"] == "Delay causes, 2025 (arriving flights)"
    assert table["columns"] == ["Airport", "Cause", "Minutes", "Minutes per flight", "Share of delay"]
    assert table["units"] == ["text", "text", "minutes", "minutes", "share"]
    causes = ev["result"]["data"]["airports"][0]["causes"]
    labels = [("carrier", "Airline"), ("weather", "Weather"), ("nas", "Airspace/airport (NAS)"),
              ("late_aircraft", "Late incoming plane"), ("security", "Security")]  # fmt: skip
    assert table["rows"] == [
        ["BOS", label, causes[key]["minutes"], causes[key]["per_flight"], causes[key]["share"]] for key, label in labels
    ]
    # Hand check (TINY_DATA.md): BOS NAS 800 x 2 months = 1,600 minutes, / 200 flights = 8.
    nas = table["rows"][2]
    assert nas[2:4] == [1600, 8]

    [by_month] = build_tables([event(tiny_db, "delay_causes", {"airports": ["BOS"], "by": "month"})])
    check_shape(by_month)
    assert by_month["columns"] == ["Airport", "Month", "Cause", "Minutes", "Minutes per flight", "Share of delay"]
    assert len(by_month["rows"]) == 2 * 5  # 2 months x 5 causes
    assert [r[1] for r in by_month["rows"]] == [1] * 5 + [7] * 5
    assert by_month["rows"][2][:4] == ["BOS", 1, "Airspace/airport (NAS)", 800]


def test_tables_unmet_demand_gives_two_tables(tiny_db):
    build_tables = presenters().build_tables
    ev = event(tiny_db, "unmet_demand", {"airports": ["BOS"]})
    tables = build_tables([ev])
    assert len(tables) == 2
    estimates, months = tables
    for t in tables:
        check_shape(t)
        assert t["about"] == ev["result"]["about"]

    assert estimates["title"] == "Unmet demand estimates, 2025"
    assert estimates["columns"] == ["Airport", "Estimate", "Target load factor", "Missing seats",
                                    "Missing flights", "Missing seats share"]  # fmt: skip
    # Hand check (TINY_DATA.md): 80% -> 210 seats, 2.1 flights, 210 / 4,000 = 0.0525;
    # 85% -> 80 seats, 0.8 flights, 80 / 4,000 = 0.02.
    assert estimates["rows"] == [
        ["BOS", "high estimate", 0.8, pytest.approx(210), pytest.approx(2.1), pytest.approx(0.0525)],
        ["BOS", "low estimate", 0.85, pytest.approx(80), pytest.approx(0.8), pytest.approx(0.02)],
    ]

    assert months["title"] == "Load factor by month, 2025"
    assert months["columns"] == ["Airport", "Month", "Passengers", "Seats", "Load factor"]
    assert months["units"] == ["text", "month", "passengers", "seats", "share"]
    # Hand check: Jan 1,400 / 2,000 = 0.7; Jul 1,768 / 2,000 = 0.884.
    assert months["rows"] == [["BOS", 1, 1400, 2000, pytest.approx(0.7)], ["BOS", 7, 1768, 2000, pytest.approx(0.884)]]


def test_tables_data_info(tiny_db):
    build_tables = presenters().build_tables
    ev = event(tiny_db, "data_info", {})
    [table] = build_tables([ev])
    check_shape(table)
    assert table["title"] == "Data sources"
    assert table["columns"] == ["Source", "URL", "Period", "Loaded at", "Rows"]
    assert table["rows"] == [[s["source"], s["url"], s["period"], s["loaded_at"], s["row_count"]]
                             for s in ev["result"]["data"]["sources"]]  # fmt: skip
    # Hand check: 4 sources in the tiny data; OurAirports has 7 rows.
    assert len(table["rows"]) == 4
    assert ["OurAirports", 7] in [[r[0], r[4]] for r in table["rows"]]


def test_tables_live_status():
    build_tables = presenters().build_tables
    about = {"data_period": "now", "filters": [], "missing": [], "assumptions": ["Live status is context only."]}
    result = {"data": {"airport": "SFO", "feed_available": True, "updated": "Fri Oct 31 12:00:00 2026 GMT",
                       "events": [{"type": "Ground Delay", "reason": "weather / low ceilings",
                                   "avg": "45 minutes", "max": "1 hour 10 minutes"}]},
              "about": about}  # fmt: skip
    [table] = build_tables([{"id": "c1", "name": "live_status", "args": {"airport": "SFO"}, "result": result}])
    check_shape(table)
    assert table["title"] == "FAA live status for SFO"
    assert table["columns"] == ["Type", "Reason", "Details"]
    # Details: the event's other fields as "key: value", joined by "; ".
    assert table["rows"] == [["Ground Delay", "weather / low ceilings", "avg: 45 minutes; max: 1 hour 10 minutes"]]
    assert table["about"] == about

    quiet = {"data": {"airport": "SFO", "feed_available": True, "updated": "", "events": []}, "about": about}
    [table] = build_tables([{"id": "c2", "name": "live_status", "args": {"airport": "SFO"}, "result": quiet}])
    assert table["rows"] == []


def test_tables_skip_errors_and_unknown_tools_and_keep_order(tiny_db):
    build_tables = presenters().build_tables
    bad = event(tiny_db, "rank_airports", {"top_n": 99}, "c1")  # error result
    unknown = event(tiny_db, "fly_me_there", {}, "c2")  # unknown tool
    raw = event(tiny_db, "find_airports", "not a dict", "c3")  # unreadable settings
    assert "error" in bad["result"] and "error" in unknown["result"] and "error" in raw["result"]
    assert build_tables([bad, unknown, raw]) == []
    assert build_tables([]) == []

    # Good and bad mixed: only the good ones, in the order run.
    good1 = event(tiny_db, "data_info", {}, "c4")
    good2 = event(tiny_db, "route_mix", {"airport": "LAX"}, "c5")
    titles = [t["title"] for t in build_tables([good1, bad, good2])]
    assert titles == ["Data sources", "LAX flight mix, 2025", "LAX departures by destination, 2025"]


def test_tables_do_not_change_tool_events(tiny_db):
    build_tables = presenters().build_tables
    events = [event(tiny_db, "route_mix", {"airport": "ANC"}), event(tiny_db, "unmet_demand", {"airports": ["BOS"]})]
    copy_before = json.loads(json.dumps(events))
    build_tables(events)
    presenters().build_steps(events)
    assert events == copy_before
