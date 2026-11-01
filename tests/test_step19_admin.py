"""Tests for Step 19: the admin dashboard (app/admin_store.py, app/admin.py, the small app/api.py changes, web/admin.js)."""

import importlib
import json
import logging
import math
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.tools  # noqa: F401  (fills the tool registry TOOLS)
from app.agent.provider import AIProvider, AIReply
from app.config import Settings
from app.db import open_airport_db
from app.refusals import REFUSALS
from app.store import ChatStore
from app.tools.base import TOOLS, run_tool
from tests.fakes import FakeProvider
from tests.fixtures.tiny_data import build_tiny_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "https://our-page.vercel.app"
OTHER_ORIGIN = "https://someone-else.example.com"
TOKEN = "test-admin-token-0123456789abcdef0123456789"  # made up, 43 characters (P123: 32+)
AUTH = {"Authorization": f"Bearer {TOKEN}"}
UNAUTHORIZED = {"detail": "unauthorized"}
BAD_REQUEST = {"detail": "bad request"}
# The four admin addresses (api.md section 4), as (method, path, json body).
ADMIN_CALLS = [
    ("GET", "/admin/metrics", None),
    ("GET", "/admin/events?limit=100", None),
    ("GET", "/admin/ai", None),
    ("POST", "/admin/ai", {"enabled": True}),
]
# The keys of GET /admin/metrics (api.md section 4).
METRIC_KEYS = {
    "questions", "chats", "cost_usd", "cost_per_question_usd", "input_tokens", "output_tokens",
    "events_since", "requests", "refusal_rate", "duration_p50_ms", "duration_p95_ms",
    "questions_per_day", "refusals_by_cause", "tools", "visitors",
}  # fmt: skip
# The keys of one entry of GET /admin/events (api.md section 4).
EVENT_KEYS = {"time", "conversation_id", "visitor_id", "question", "answer", "refusal_cause", "steps", "tools",
              "cost_usd"}


# ---------------------------------------------------------------- helpers
# The modules under test are imported inside the helpers (not at the top), so the file
# still loads before they exist and each test fails on its own.


def api_module():
    return importlib.import_module("app.api")


def admin_store_module():
    return importlib.import_module("app.admin_store")


def AdminStore(*args, **kwargs):  # noqa: N802  (stands in for the class)
    return admin_store_module().AdminStore(*args, **kwargs)


def empty(value):
    """An "empty" column or field: the docs say "empty" without saying NULL or "".

    # Assumption: an empty conversation_id / cause / events_since may be None or "".
    """
    return value in (None, "")


def text_reply(text, cost=0.001):
    """An AI reply with final text and no tool requests."""
    return AIReply(text=text, tool_calls=None, model="test/model", input_tokens=10, output_tokens=5,
                   cost_usd=cost)  # fmt: skip


class Clock:
    """A clock the test moves by hand: `now()` returns the current fixed UTC time."""

    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def set(self, t):
        self.t = t


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class GateProvider(AIProvider):
    """A fake AI whose first call waits until the test sets `release` (at most 10 s), so a
    turn can be kept running past the time limit. Later calls follow the script."""

    def __init__(self, script):
        self.fake = FakeProvider(script)
        self.release = threading.Event()
        self.count = 0

    def send(self, messages, tools, max_tokens):
        self.count += 1
        if self.count == 1:
            self.release.wait(10)
        return self.fake.send(messages, tools, max_tokens)


class CrashProvider(AIProvider):
    """A fake AI that crashes (not an AIUnavailable), so the turn is an internal error."""

    def send(self, messages, tools, max_tokens):
        raise RuntimeError("boom")


@pytest.fixture
def airports_path(tmp_path):
    path = tmp_path / "tiny.duckdb"
    build_tiny_db(path)
    return path


@pytest.fixture
def make_client(tmp_path, airports_path):
    """make_client(provider, **setting_changes) -> (TestClient, Settings).

    Settings are built explicitly (never from environment variables), with ADMIN_TOKEN set.
    The client does not re-raise server crashes, so a test sees what a browser would see.
    """

    def make(provider=None, **changes):
        values = dict(
            airports_db=str(airports_path),
            chat_db=str(tmp_path / "chat.sqlite"),
            openrouter_api_key="test-key",
            openrouter_model="test/model",
            allowed_origin=ORIGIN,
            admin_token=TOKEN,
        )
        values.update(changes)
        settings = Settings(**values)
        application = api_module().create_app(settings, provider=provider)
        return TestClient(application, raise_server_exceptions=False), settings

    return make


def call(client, method, path, body=None, headers=None):
    if method == "GET":
        return client.get(path, headers=headers or {})
    return client.post(path, json=body, headers=headers or {})


def event_rows(chat_db):
    """Every chat_events row, in the order written: (conversation_id, outcome, cause, duration_ms, language)."""
    con = sqlite3.connect(chat_db)
    try:
        return con.execute(
            "SELECT conversation_id, outcome, cause, duration_ms, language FROM chat_events ORDER BY id"
        ).fetchall()
    finally:
        con.close()


def chat_count(chat_db):
    con = sqlite3.connect(chat_db)
    try:
        return con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    finally:
        con.close()


def table_rows(chat_db, table):
    con = sqlite3.connect(chat_db)
    try:
        return con.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()  # noqa: S608 (fixed names)
    finally:
        con.close()


def table_names(chat_db):
    con = sqlite3.connect(chat_db)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        con.close()


def days_ending(last_day, n=30):
    """The n days ending on last_day, oldest first, as "YYYY-MM-DD"."""
    return [(last_day - timedelta(days=n - 1 - i)).strftime("%Y-%m-%d") for i in range(n)]


def backend_url_of(path):
    """The value of the one `const BACKEND_URL = "...";` line of a .js file (P94, P136)."""
    text = path.read_text(encoding="utf-8")
    found = re.findall(r'^\s*const\s+BACKEND_URL\s*=\s*"([^"]*)"\s*;', text, flags=re.MULTILINE)
    assert len(found) == 1, f"{path.name} must have exactly one BACKEND_URL line, found {len(found)}"
    return found[0]


# ---------------------------------------------------------------- 1. the setting


def test_admin_token_read_from_environment(monkeypatch):
    # P123: the 6th setting, read when Settings() is made; default None.
    monkeypatch.setenv("ADMIN_TOKEN", "some-long-random-text-for-the-test-1234")
    assert Settings().admin_token == "some-long-random-text-for-the-test-1234"
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert Settings().admin_token is None


# ---------------------------------------------------------------- 2-4. the token check


@pytest.mark.parametrize("token_setting", [None, ""])
def test_admin_locked_without_token_setting(make_client, token_setting):
    # P124: no ADMIN_TOKEN setting (or an empty one) -> every admin address is 401, whatever is sent.
    client, _ = make_client(FakeProvider([]), admin_token=token_setting)
    headers_to_try = [
        {},
        {"Authorization": "Bearer "},  # "Bearer " + "" must not open it
        {"Authorization": "Bearer None"},
        {"Authorization": f"Bearer {TOKEN}"},
    ]
    for method, path, body in ADMIN_CALLS:
        for headers in headers_to_try:
            r = call(client, method, path, body, headers)
            assert r.status_code == 401, (method, path, headers)
            assert r.json() == UNAUTHORIZED


def test_admin_refuses_missing_or_wrong_token(make_client):
    client, settings = make_client(FakeProvider([]))
    wrong_headers = [
        {},  # no header
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": TOKEN},  # no "Bearer " in front
        {"Authorization": f"Bearer {TOKEN}x"},  # one character too many
        {"Authorization": f"Bearer {TOKEN[:-1]}"},  # one character too few
        {"Authorization": f"Basic {TOKEN}"},
    ]
    for method, path, body in ADMIN_CALLS:
        for headers in wrong_headers:
            r = call(client, method, path, body, headers)
            assert r.status_code == 401, (method, path, headers)
            assert r.json() == UNAUTHORIZED  # nothing else in the body (P124)
    # A refused POST /admin/ai changes nothing: the switch is still on.
    assert AdminStore(settings.chat_db).ai_enabled() is True


def test_admin_allows_right_token(make_client):
    client, _ = make_client(FakeProvider([]))
    r = client.get("/admin/metrics", headers=AUTH)
    assert r.status_code == 200
    assert set(r.json()) == METRIC_KEYS
    r = client.get("/admin/events?limit=100", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"events": [], "total": 0}  # no questions yet
    r = client.get("/admin/ai", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"enabled": True, "updated_at": None, "note": None}  # api.md: no row -> on
    r = client.post("/admin/ai", json={"enabled": True}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["enabled"] is True
    # The default limit (100) is used when none is given.
    assert client.get("/admin/events", headers=AUTH).status_code == 200


def test_admin_router_can_be_included_on_its_own(tmp_path):
    # Interface: admin_router(settings, admin_store) -> APIRouter with the four addresses.
    admin = importlib.import_module("app.admin")
    path = tmp_path / "chat.sqlite"
    ChatStore(path)
    settings = Settings(chat_db=str(path), admin_token=TOKEN)
    application = FastAPI()
    application.include_router(admin.admin_router(settings, AdminStore(path)))
    client = TestClient(application, raise_server_exceptions=False)
    assert client.get("/admin/ai").status_code == 401
    assert client.get("/admin/ai", headers=AUTH).json() == {"enabled": True, "updated_at": None, "note": None}


# ---------------------------------------------------------------- 5. CORS


def test_cors_allows_authorization_from_our_page_only(make_client):
    client, _ = make_client(FakeProvider([]))
    preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "Authorization"}

    # Our page may send the Authorization header (P125).
    r = client.options("/admin/metrics", headers={"Origin": ORIGIN, **preflight})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    allowed = {h.strip().lower() for h in r.headers.get("access-control-allow-headers", "").split(",")}
    assert {"authorization", "content-type"} <= allowed
    assert "access-control-allow-credentials" not in r.headers  # still no credentials (P87)

    # The chat page's own preflight still works.
    r = client.options("/chat", headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST",
                                         "Access-Control-Request-Headers": "Content-Type"})  # fmt: skip
    assert r.headers.get("access-control-allow-origin") == ORIGIN

    # Any other site: no allow-origin header, so the browser blocks it.
    r = client.options("/admin/metrics", headers={"Origin": OTHER_ORIGIN, **preflight})
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/admin/metrics", headers={"Origin": OTHER_ORIGIN, **AUTH})
    assert "access-control-allow-origin" not in r.headers


# ---------------------------------------------------------------- 6. old chats kept


def test_new_tables_keep_old_chats(make_client, tmp_path, airports_path):
    # A chat saved before the admin tables exist (as on the live disk).
    path = tmp_path / "chat.sqlite"
    store = ChatStore(path)
    chat_id = store.new_chat()
    store.add_step(chat_id, "user", "Which New England airports are strong candidates?")
    store.add_step(chat_id, "assistant", None, tool_calls=[{"id": "t1", "name": "data_info", "args": {}}],
                   model="test/model", input_tokens=100, output_tokens=10, cost_usd=0.0002)  # fmt: skip
    con = open_airport_db(airports_path)
    try:
        store.add_step(chat_id, "tool", json.dumps(run_tool(con, "data_info", {})), tool_call_id="t1")
    finally:
        con.close()
    store.add_step(chat_id, "assistant", "BOS is first.", model="test/model", input_tokens=200,
                   output_tokens=20, cost_usd=0.0003)  # fmt: skip
    assert "chat_events" not in table_names(path)

    before_steps = store.load_steps(chat_id)
    before_conversations = table_rows(path, "conversations")
    before_messages = table_rows(path, "messages")
    # The reload reply of the old code path, before any admin table exists, is built from
    # rebuild_turns directly (the same function GET /chat uses).
    from app.presenters import rebuild_turns

    before_reload = rebuild_turns(before_steps)

    AdminStore(path)  # makes the two new tables (P126)
    client, _ = make_client(FakeProvider([]), chat_db=str(path))  # the app makes its own AdminStore too

    assert {"chat_events", "app_settings"} <= table_names(path)
    assert table_rows(path, "conversations") == before_conversations
    assert table_rows(path, "messages") == before_messages
    assert ChatStore(path).load_steps(chat_id) == before_steps
    r = client.get(f"/chat/{chat_id}")
    assert r.status_code == 200
    assert r.json() == {"conversation_id": chat_id, "turns": json.loads(json.dumps(before_reload)), "refusal": None}


# ---------------------------------------------------------------- 7-8. the log row


def test_every_chat_request_is_logged(make_client, monkeypatch):
    api = api_module()
    monkeypatch.setattr(api, "TURN_TIMEOUT_SECONDS", 0.2)  # read at request time (P85)
    out_of_scope = REFUSALS["out_of_scope"]
    provider = GateProvider([
        text_reply("Late answer."),  # 1st call: held back until release -> timeout
        text_reply("Hello."),        # the answered question
        text_reply(out_of_scope),    # the agent's own refusal
    ])  # fmt: skip
    client, settings = make_client(provider)
    unknown = str(uuid.uuid4())

    try:
        # a) a timeout (error, timeout); the reply carries the new chat ID.
        r = client.post("/chat", json={"message": "A slow question"})
        assert r.status_code == 500
        slow_id = r.json()["conversation_id"]
        # b) busy: the timed-out turn still runs (refused, busy).
        r = client.post("/chat", json={"conversation_id": slow_id, "message": "Hello?"})
        assert r.json()["refusal"]["cause"] == "busy"
    finally:
        provider.release.set()
    # Wait until the background turn has saved its answer, so the provider script is in order.
    store = ChatStore(settings.chat_db)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(store.load_steps(slow_id)) < 2:
        time.sleep(0.01)

    # c) answered, in Hebrew.
    r = client.post("/chat", json={"message": "Hi", "language": "he"})
    answered_id = r.json()["conversation_id"]
    assert r.json()["answer"] == "Hello."
    # d) too long (refused before the agent; no chat made, so no ID).
    r = client.post("/chat", json={"message": "x" * 1001})
    assert r.json()["refusal"]["cause"] == "question_too_long"
    # e) unknown chat (the reply's ID is the unknown one).
    r = client.post("/chat", json={"conversation_id": unknown, "message": "Hi"})
    assert r.json()["refusal"]["cause"] == "chat_not_found"
    # f) the agent's own refusal (out_of_scope, P63).
    r = client.post("/chat", json={"message": "What's the weather in Paris?"})
    scope_id = r.json()["conversation_id"]
    assert r.json()["refusal"]["cause"] == "out_of_scope"
    # g) a bad body (error, bad_request).
    r = client.post("/chat", content=b"this is not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400

    rows = event_rows(settings.chat_db)
    assert len(rows) == 7  # one row per POST /chat reply (P127), the late turn adds none
    got = [(cid, outcome, cause, lang) for cid, outcome, cause, _ms, lang in rows]
    expected = [
        (slow_id, "error", "timeout", "en"),
        (slow_id, "refused", "busy", "en"),
        (answered_id, "answered", None, "he"),
        (None, "refused", "question_too_long", "en"),
        (unknown, "refused", "chat_not_found", "en"),
        (scope_id, "refused", "out_of_scope", "en"),
        (None, "error", "bad_request", None),
    ]
    for (cid, outcome, cause, lang), (e_cid, e_outcome, e_cause, e_lang) in zip(got, expected):
        assert outcome == e_outcome
        assert (empty(cid) and e_cid is None) or cid == e_cid, (cid, e_cid)
        assert (empty(cause) and e_cause is None) or cause == e_cause, (cause, e_cause)
        if e_lang is not None:
            assert lang == e_lang
    # Assumption: for a body we could not read, the language column is not checked (no language was read).
    # Durations are whole milliseconds (P128); the timeout waited at least 0.2 s = 200 ms.
    for _cid, _o, _c, ms, _l in rows:
        assert isinstance(ms, int) and ms >= 0
    assert rows[0][3] >= 150
    # The question text is never in the log (P127).
    con = sqlite3.connect(settings.chat_db)
    try:
        dump = "\n".join(con.iterdump())
    finally:
        con.close()
    log_lines = [line for line in dump.splitlines() if "chat_events" in line]
    for question in ("A slow question", "What's the weather in Paris?", "x" * 1001):
        assert not any(question in line for line in log_lines)


def test_crash_is_logged_as_error(make_client):
    client, settings = make_client(CrashProvider())
    r = client.post("/chat", json={"message": "Anything"})
    assert r.status_code == 500
    rows = event_rows(settings.chat_db)
    assert len(rows) == 1
    cid, outcome, cause, _ms, _lang = rows[0]
    assert (outcome, cause) == ("error", "crash")
    assert cid == r.json()["conversation_id"]


def _replies_for_three_requests(client):
    """An answered question, a too-long one, a bad body: [(status, body without the chat ID)]."""
    out = []
    r = client.post("/chat", json={"message": "Hi"})
    body = r.json()
    assert isinstance(body["conversation_id"], str)
    body["conversation_id"] = "<new chat>"  # a new random ID each time
    out.append((r.status_code, body))
    r = client.post("/chat", json={"message": "x" * 1001})
    out.append((r.status_code, r.json()))
    r = client.post("/chat", content=b"[1, 2]", headers={"Content-Type": "application/json"})
    out.append((r.status_code, r.json()))
    return out


def test_log_failure_does_not_change_the_reply(make_client, tmp_path, monkeypatch, caplog):
    # A normal app first, for the replies to compare with.
    normal_client, _ = make_client(FakeProvider([text_reply("Hello.")]), chat_db=str(tmp_path / "normal.sqlite"))
    normal = _replies_for_three_requests(normal_client)

    # Choice: the AdminStore *class* method is replaced, so whatever instance create_app makes
    # (app/api.py builds it from settings.chat_db itself) fails to write its log row (P129).
    tried = []

    def broken_log_event(self, *args, **kwargs):
        tried.append(True)  # proves the log row really goes through log_event()
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(admin_store_module().AdminStore, "log_event", broken_log_event)
    client, settings = make_client(FakeProvider([text_reply("Hello.")]), chat_db=str(tmp_path / "broken.sqlite"))
    with caplog.at_level(logging.ERROR):
        broken = _replies_for_three_requests(client)

    assert len(tried) == 3, "each POST /chat reply must write its row with AdminStore.log_event (P127)"
    assert broken == normal  # status and body exactly the same
    assert any(rec.exc_info for rec in caplog.records), "the log failure went to the server log (logger.exception)"
    assert event_rows(settings.chat_db) == []


def test_admin_store_failing_to_start_still_chats(make_client, monkeypatch):
    # P129: AdminStore failing to start at all means no logging, and the chat still works.
    def broken_init(self, *args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(admin_store_module().AdminStore, "__init__", broken_init)
    client, _ = make_client(FakeProvider([text_reply("Hello.")]))
    r = client.post("/chat", json={"message": "Hi"})
    assert r.status_code == 200
    assert r.json()["answer"] == "Hello."
    assert r.json()["refusal"] is None


# ---------------------------------------------------------------- 9-13. the AI switch


def test_switch_is_on_by_default(make_client, tmp_path):
    path = tmp_path / "fresh.sqlite"
    ChatStore(path)
    store = AdminStore(path)
    assert store.ai_enabled() is True  # no row means ON (schema.md part 3)
    assert store.ai_state() == {"enabled": True, "updated_at": None, "note": None}
    client, _ = make_client(FakeProvider([]), chat_db=str(path))
    assert client.get("/admin/ai", headers=AUTH).json() == {"enabled": True, "updated_at": None, "note": None}


def test_switch_off_refuses_before_ai(make_client):
    provider = FakeProvider([text_reply("Old answer."), text_reply("Back on.")])
    client, settings = make_client(provider)
    old = client.post("/chat", json={"message": "Hi"}).json()
    old_id = old["conversation_id"]
    reload_before = client.get(f"/chat/{old_id}").json()
    assert len(provider.calls) == 1

    r = client.post("/admin/ai", json={"enabled": False, "note": "cost check"}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["enabled"] is False and r.json()["note"] == "cost check"

    chats_before = chat_count(settings.chat_db)
    r = client.post("/chat", json={"message": "Which airports grow fastest?"})
    assert r.status_code == 200
    assert r.json() == {"conversation_id": None, "answer": "", "tables": [], "steps": [],
                        "refusal": {"cause": "ai_unavailable", "message": REFUSALS["ai_unavailable"]}}  # fmt: skip
    r = client.post("/chat", json={"conversation_id": old_id, "message": "And then?"})
    assert r.json()["refusal"]["cause"] == "ai_unavailable"
    assert r.json()["conversation_id"] == old_id
    assert len(provider.calls) == 1  # the AI was never called while off
    assert chat_count(settings.chat_db) == chats_before  # no new chat made (P82 check 4 saves nothing)
    assert len(ChatStore(settings.chat_db).load_steps(old_id)) == 2  # nothing added to the old chat

    # The order of the other checks is unchanged (P130).
    r = client.post("/chat", json={"message": "x" * 1001})
    assert r.json()["refusal"]["cause"] == "question_too_long"
    r = client.post("/chat", json={"conversation_id": str(uuid.uuid4()), "message": "Hi"})
    assert r.json()["refusal"]["cause"] == "chat_not_found"

    # Reloading old chats and /health are not affected.
    assert client.get(f"/chat/{old_id}").json() == reload_before
    assert client.get("/health").status_code == 200
    # Logged as a refusal.
    assert ("refused", "ai_unavailable") in [(o, c) for _cid, o, c, _ms, _l in event_rows(settings.chat_db)]

    # Back on: answers again.
    client.post("/admin/ai", json={"enabled": True}, headers=AUTH)
    r = client.post("/chat", json={"message": "Hi again"})
    assert r.json()["answer"] == "Back on."


def test_switch_saves_wanted_state(tmp_path, make_client):
    path = tmp_path / "chat.sqlite"
    ChatStore(path)
    clock = Clock(utc(2026, 11, 2, 10, 0, 0))
    store = AdminStore(path, now=clock)

    state = store.set_ai_enabled(False, note="cost check")
    assert state == {"enabled": False, "updated_at": "2026-11-02T10:00:00+00:00", "note": "cost check"}
    # Assumption: updated_at is written like ChatStore's times: UTC datetime.isoformat().
    clock.set(utc(2026, 11, 2, 10, 5, 0))
    state = store.set_ai_enabled(False)  # "off" twice stays off (not a flip)
    assert state == {"enabled": False, "updated_at": "2026-11-02T10:05:00+00:00", "note": None}
    # Assumption: a second save without a note replaces the row, so the note becomes None (P131 "insert or replace").
    assert store.ai_enabled() is False
    assert store.ai_state() == state

    # It survives a new AdminStore on the same file (a restart or redeploy).
    again = AdminStore(path)
    assert again.ai_enabled() is False
    assert again.ai_state() == state
    # Stored as text in app_settings (schema.md part 3).
    con = sqlite3.connect(path)
    try:
        rows = con.execute("SELECT key, value, updated_at, note FROM app_settings").fetchall()
    finally:
        con.close()
    assert rows == [("ai_enabled", "false", "2026-11-02T10:05:00+00:00", None)]

    # Through the address too: off twice is still off, and the reply has the three keys.
    client, _ = make_client(FakeProvider([]), chat_db=str(path))
    for _ in range(2):
        r = client.post("/admin/ai", json={"enabled": False, "note": "again"}, headers=AUTH)
        assert r.status_code == 200
        assert set(r.json()) == {"enabled", "updated_at", "note"}
        assert r.json()["enabled"] is False and r.json()["note"] == "again"
    assert client.get("/admin/ai", headers=AUTH).json()["enabled"] is False
    assert set(store.set_ai_enabled(True)) == {"enabled", "updated_at", "note"}
    assert AdminStore(path).ai_enabled() is True


def test_switch_read_failure_counts_as_on(make_client, monkeypatch, caplog):
    # Choice: the AdminStore class method is replaced, so the instance create_app makes fails
    # to read the switch. P130: it counts as ON and the error goes to the server log.
    tried = []

    def broken_ai_enabled(self):
        tried.append(True)  # proves the /chat switch check really goes through ai_enabled()
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(admin_store_module().AdminStore, "ai_enabled", broken_ai_enabled)
    provider = FakeProvider([text_reply("The turn still ran.")])
    client, _ = make_client(provider)
    with caplog.at_level(logging.ERROR):
        r = client.post("/chat", json={"message": "Hi"})
    assert r.status_code == 200
    assert r.json()["answer"] == "The turn still ran."
    assert r.json()["refusal"] is None
    assert len(provider.calls) == 1
    assert tried, "POST /chat must read the switch with AdminStore.ai_enabled() (P130)"
    assert any(rec.exc_info for rec in caplog.records)


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"enabled": "no"}).encode(),
        json.dumps({"enabled": False, "note": "x" * 201}).encode(),  # 201 > 200 characters
        json.dumps({"enabled": 0}).encode(),  # must be JSON true/false, not a number
        json.dumps({"enabled": None}).encode(),
        json.dumps({"note": "no enabled"}).encode(),
        json.dumps({"enabled": False, "note": 5}).encode(),  # note must be text
        json.dumps([False]).encode(),
        b"not json",
    ],
)
def test_switch_bad_body_gives_400(make_client, content):
    client, settings = make_client(FakeProvider([]))
    r = client.post("/admin/ai", content=content, headers={**AUTH, "Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json() == BAD_REQUEST
    assert AdminStore(settings.chat_db).ai_enabled() is True  # nothing saved


def test_switch_note_of_200_characters_is_allowed(make_client):
    client, _ = make_client(FakeProvider([]))
    r = client.post("/admin/ai", json={"enabled": False, "note": "x" * 200}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["note"] == "x" * 200


# ---------------------------------------------------------------- 14-17. the numbers


def _build_known_chats(path, clock):
    """Three chats with known steps (made-up numbers). Returns the chat IDs.

    chat 1 (2026-11-19 10:00, follow-up on 2026-11-20 09:00):
      user q1
      assistant asks rank_airports + find_airports   in 1000, out 100, cost 0.002
      tool, tool
      assistant text                                 in 1500, out 200, cost 0.003
      user q2                                        (2026-11-20 09:00)
      assistant text                                 in  500, out None, cost None
    chat 2 (2026-11-20 11:00):
      user q3
      assistant asks rank_airports                   in  800, out  50, cost 0.001
      tool
      assistant text                                 in 1200, out 150, cost 0.0015
    chat 3 (2026-11-20 12:00):
      user q4
      assistant the ai_unavailable message           (no tokens, no cost; P59)
    """
    store = ChatStore(path, now=clock)
    clock.set(utc(2026, 11, 19, 10, 0, 0))
    c1 = store.new_chat()
    store.add_step(c1, "user", "q1")
    store.add_step(c1, "assistant", None, tool_calls=[{"id": "a", "name": "rank_airports", "args": {}},
                                                      {"id": "b", "name": "find_airports", "args": {"text": "x"}}],
                   model="m", input_tokens=1000, output_tokens=100, cost_usd=0.002)  # fmt: skip
    store.add_step(c1, "tool", "{}", tool_call_id="a")
    store.add_step(c1, "tool", "{}", tool_call_id="b")
    store.add_step(c1, "assistant", "a1", model="m", input_tokens=1500, output_tokens=200, cost_usd=0.003)
    clock.set(utc(2026, 11, 20, 9, 0, 0))
    store.add_step(c1, "user", "q2")
    store.add_step(c1, "assistant", "a2", model="m", input_tokens=500, output_tokens=None, cost_usd=None)

    clock.set(utc(2026, 11, 20, 11, 0, 0))
    c2 = store.new_chat()
    store.add_step(c2, "user", "q3")
    store.add_step(c2, "assistant", None, tool_calls=[{"id": "c", "name": "rank_airports", "args": {}}],
                   model="m", input_tokens=800, output_tokens=50, cost_usd=0.001)  # fmt: skip
    store.add_step(c2, "tool", "{}", tool_call_id="c")
    store.add_step(c2, "assistant", "a3", model="m", input_tokens=1200, output_tokens=150, cost_usd=0.0015)

    clock.set(utc(2026, 11, 20, 12, 0, 0))
    c3 = store.new_chat()
    store.add_step(c3, "user", "q4")
    store.add_step(c3, "assistant", REFUSALS["ai_unavailable"])
    return c1, c2, c3


def _log_known_events(store, clock, c1, c2, c3):
    """Eight log rows (made-up durations), one minute apart, the first at 2026-11-19 10:00:05."""
    rows = [
        (c1, "answered", None, 4200, "en"),
        (None, "refused", "question_too_long", 3, "en"),
        (c1, "answered", None, 9000, "en"),
        (c2, "refused", "airport_not_found", 6100, "he"),
        (None, "refused", "question_too_long", 2, "en"),
        (c3, "error", "timeout", 60010, "en"),
        (c2, "answered", None, 7400, "en"),
        (c3, "answered", None, 5000, "en"),
    ]
    start = utc(2026, 11, 19, 10, 0, 5)
    for i, (cid, outcome, cause, ms, lang) in enumerate(rows):
        clock.set(start + timedelta(minutes=i))
        store.log_event(cid, outcome, cause, ms, lang)


def test_metrics_numbers(tmp_path, make_client):
    path = tmp_path / "chat.sqlite"
    chat_clock = Clock(utc(2026, 11, 19, 10, 0, 0))
    c1, c2, c3 = _build_known_chats(path, chat_clock)
    admin_clock = Clock(utc(2026, 11, 19, 10, 0, 5))
    store = AdminStore(path, now=admin_clock)
    _log_known_events(store, admin_clock, c1, c2, c3)
    admin_clock.set(utc(2026, 11, 20, 15, 0, 0))  # "today" = 2026-11-20

    m = store.metrics()
    assert set(m) == METRIC_KEYS
    assert m["questions"] == 4  # q1, q2, q3, q4 (user steps)
    assert m["chats"] == 3  # conversations rows
    # 0.002 + 0.003 + 0 (None counts 0) + 0.001 + 0.0015 = 0.0075
    assert m["cost_usd"] == pytest.approx(0.0075)
    # 0.0075 / 4 = 0.001875 -> rounded to 4 decimals = 0.0019
    assert m["cost_per_question_usd"] == pytest.approx(0.0019)
    assert m["input_tokens"] == 5000  # 1000 + 1500 + 500 + 800 + 1200
    assert m["output_tokens"] == 500  # 100 + 200 + 0 (None) + 50 + 150 + 0 (no tokens)
    # The first chat_events row (P132; written like ChatStore's times).
    assert m["events_since"] == "2026-11-19T10:00:05+00:00"
    assert m["requests"] == 8  # all eight log rows
    # refused rows: question_too_long, airport_not_found, question_too_long = 3; the error is not
    # a refusal (api.md). 3 refused / 8 requests = 0.375
    assert m["refusal_rate"] == pytest.approx(0.375)
    # Sorted times: 2, 3, 4200, 5000, 6100, 7400, 9000, 60010 (n = 8, every row counts).
    # Assumption: every chat_events row counts for the durations (answered, refused and error).
    # p50 = position ceil(0.5 * 8) = 4 -> 5000; p95 = position ceil(0.95 * 8) = ceil(7.6) = 8 -> 60010
    assert math.ceil(0.5 * 8) == 4 and math.ceil(0.95 * 8) == 8
    assert m["duration_p50_ms"] == 5000
    assert m["duration_p95_ms"] == 60010
    # 30 days ending 2026-11-20: 2026-10-22 ... 2026-11-20; q1 on 11-19, q2/q3/q4 on 11-20.
    days = days_ending(datetime(2026, 11, 20))
    assert days[0] == "2026-10-22" and days[-1] == "2026-11-20"
    expected_days = [{"day": d, "count": {"2026-11-19": 1, "2026-11-20": 3}.get(d, 0)} for d in days]
    assert m["questions_per_day"] == expected_days
    # Only refused rows, by cause, highest count first.
    # Assumption: the error causes (timeout) are not in refusals_by_cause (errors are not refusals).
    assert m["refusals_by_cause"] == [
        {"cause": "question_too_long", "count": 2},
        {"cause": "airport_not_found", "count": 1},
    ]
    # rank_airports: 1 (chat 1) + 1 (chat 2) = 2; find_airports 1; the other seven tools 0, by name.
    unused = sorted(set(TOOLS) - {"rank_airports", "find_airports"})
    assert m["tools"] == (
        [{"name": "rank_airports", "count": 2}, {"name": "find_airports", "count": 1}]
        + [{"name": n, "count": 0} for n in unused]
    )

    # The address gives the same numbers (its own AdminStore runs on the real clock, so the
    # per-day list is only checked for its length).
    client, _ = make_client(FakeProvider([]), chat_db=str(path))
    r = client.get("/admin/metrics", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert len(body["questions_per_day"]) == 30
    for key in METRIC_KEYS - {"questions_per_day"}:
        if isinstance(m[key], float):
            assert body[key] == pytest.approx(m[key]), key
        else:
            assert body[key] == m[key], key


def test_metrics_on_empty_file_are_zero(tmp_path):
    path = tmp_path / "chat.sqlite"
    ChatStore(path)  # the app always makes the chat tables first (create_app)
    # Assumption: "an empty file" = a chat.sqlite with the four tables and no rows.
    store = AdminStore(path, now=Clock(utc(2026, 11, 20, 15, 0, 0)))
    m = store.metrics()
    assert set(m) == METRIC_KEYS
    for key in ("questions", "chats", "cost_usd", "cost_per_question_usd", "input_tokens", "output_tokens",
                "requests", "refusal_rate", "duration_p50_ms", "duration_p95_ms"):  # fmt: skip
        assert m[key] == 0, key
    assert empty(m["events_since"])
    assert m["refusals_by_cause"] == []
    assert m["questions_per_day"] == [{"day": d, "count": 0} for d in days_ending(datetime(2026, 11, 20))]
    # Assumption: P134 wins over "empty lists" for tools: every registered tool is listed with 0, by name.
    assert m["tools"] == [{"name": n, "count": 0} for n in sorted(TOOLS)]


def test_questions_per_day_has_30_days_with_zeros(tmp_path):
    path = tmp_path / "chat.sqlite"
    clock = Clock(utc(2026, 10, 1))
    store = ChatStore(path, now=clock)
    chat_id = store.new_chat()
    times = [
        utc(2026, 10, 21, 23, 59, 59),  # the day before the window: not counted
        utc(2026, 10, 22, 0, 0, 0),  # the first day of the window (2026-11-20 minus 29 days)
        utc(2026, 11, 1, 12, 0, 0),
        utc(2026, 11, 1, 18, 0, 0),
        utc(2026, 11, 20, 0, 0, 0),  # today, early
        utc(2026, 11, 20, 14, 59, 0),  # today
    ]
    for i, t in enumerate(times):
        clock.set(t)
        store.add_step(chat_id, "user", f"q{i}")
        store.add_step(chat_id, "assistant", f"a{i}")  # not a question

    m = AdminStore(path, now=Clock(utc(2026, 11, 20, 15, 0, 0))).metrics()
    per_day = m["questions_per_day"]
    assert len(per_day) == 30
    # Oct 22..31 = 10 days, Nov 1..20 = 20 days -> 30, oldest first.
    assert [e["day"] for e in per_day] == days_ending(datetime(2026, 11, 20))
    counts = {e["day"]: e["count"] for e in per_day}
    assert counts["2026-10-22"] == 1
    assert counts["2026-11-01"] == 2
    assert counts["2026-11-20"] == 2
    assert sum(counts.values()) == 5  # 6 questions, one outside the window
    assert sum(1 for c in counts.values() if c == 0) == 27  # 30 days - 3 with questions
    assert m["questions"] == 6  # the total counts every question, not only the window


def test_tools_counted_including_unused(tmp_path):
    path = tmp_path / "chat.sqlite"
    store = ChatStore(path)
    chat_id = store.new_chat()
    store.add_step(chat_id, "user", "q")
    # One step asking for two tools, then a step asking for three: each entry counts once.
    store.add_step(chat_id, "assistant", None, tool_calls=[
        {"id": "1", "name": "unmet_demand", "args": {}},
        {"id": "2", "name": "rank_airports", "args": {}},
    ])  # fmt: skip
    store.add_step(chat_id, "assistant", None, tool_calls=[
        {"id": "3", "name": "rank_airports", "args": {}},
        {"id": "4", "name": "route_mix", "args": {}},
        {"id": "5", "name": "rank_airports", "args": {}},
    ])  # fmt: skip
    store.add_step(chat_id, "assistant", None, tool_calls=[{"id": "6", "name": "find_airports", "args": {}}])
    store.add_step(chat_id, "assistant", "done")

    tools = AdminStore(path).metrics()["tools"]
    # rank_airports 3; find_airports, route_mix, unmet_demand 1 each (ties by name A->Z);
    # then the five tools never called, with 0, by name.
    assert tools == [
        {"name": "rank_airports", "count": 3},
        {"name": "find_airports", "count": 1},
        {"name": "route_mix", "count": 1},
        {"name": "unmet_demand", "count": 1},
        {"name": "airport_profile", "count": 0},
        {"name": "data_info", "count": 0},
        {"name": "delay_causes", "count": 0},
        {"name": "live_status", "count": 0},
        {"name": "traffic_trend", "count": 0},
    ]
    assert {t["name"] for t in tools} == set(TOOLS)  # every registered tool, once


# ---------------------------------------------------------------- 18-19. recent questions


def test_recent_questions_newest_first_with_answer_steps_cost_refusal(tmp_path, make_client, airports_path):
    path = tmp_path / "chat.sqlite"
    clock = Clock(utc(2026, 11, 2, 9, 0, 0))
    store = ChatStore(path, now=clock)
    con = open_airport_db(airports_path)
    try:
        ma_result = json.dumps(run_tool(con, "find_airports", {"states": ["MA"]}))
    finally:
        con.close()

    # Chat A, question 1 at 09:00: one tool, then the answer.
    chat_a = store.new_chat()
    store.add_step(chat_a, "user", "Airports in Massachusetts?")
    store.add_step(chat_a, "assistant", None, tool_calls=[{"id": "t1", "name": "find_airports", "args": {"states": ["MA"]}}],
                   model="m", input_tokens=100, output_tokens=10, cost_usd=0.002)  # fmt: skip
    store.add_step(chat_a, "tool", ma_result, tool_call_id="t1")
    store.add_step(chat_a, "assistant", "BOS is the largest.", model="m", input_tokens=200, output_tokens=20,
                   cost_usd=0.003)  # fmt: skip
    # Chat B at 09:05: refused (the AI was unavailable; the refusal text was saved, P59).
    clock.set(utc(2026, 11, 2, 9, 5, 0))
    chat_b = store.new_chat()
    store.add_step(chat_b, "user", "Compare <b>LAX</b> and SNA")
    store.add_step(chat_b, "assistant", REFUSALS["ai_unavailable"])
    # Chat A, question 2 at 09:10: an answer whose cost OpenRouter did not report.
    clock.set(utc(2026, 11, 2, 9, 10, 0))
    store.add_step(chat_a, "user", "And Vermont?")
    store.add_step(chat_a, "assistant", "BTV.", model="m", input_tokens=50, output_tokens=5, cost_usd=None)

    admin = AdminStore(path)
    events = admin.recent_questions(10)
    # Assumption: recent_questions(limit) returns the same dicts as the "events" list of GET /admin/events,
    # and "time" is the created_at of the question's user step.
    assert [e["question"] for e in events] == ["And Vermont?", "Compare <b>LAX</b> and SNA",
                                               "Airports in Massachusetts?"]  # fmt: skip
    for e in events:
        assert set(e) == EVENT_KEYS

    newest, refused, oldest = events
    assert newest["time"] == "2026-11-02T09:10:00+00:00"
    assert newest["conversation_id"] == chat_a
    assert newest["answer"] == "BTV."
    assert newest["refusal_cause"] is None
    assert newest["steps"] == []  # no tool in that turn
    assert newest["tools"] == []
    assert newest["cost_usd"] == pytest.approx(0.0)  # None counts as 0

    assert refused["time"] == "2026-11-02T09:05:00+00:00"
    assert refused["conversation_id"] == chat_b
    assert refused["refusal_cause"] == "ai_unavailable"
    assert refused["answer"] == REFUSALS["ai_unavailable"]  # api.md: answer holds the fixed message
    assert refused["steps"] == []
    assert refused["tools"] == []
    assert refused["cost_usd"] == pytest.approx(0.0)

    assert oldest["time"] == "2026-11-02T09:00:00+00:00"
    assert oldest["conversation_id"] == chat_a
    assert oldest["answer"] == "BOS is the largest."
    assert oldest["refusal_cause"] is None
    assert oldest["steps"] == ["Looked up airports (states: MA)"]  # P88 label + settings
    assert oldest["tools"] == ["find_airports"]  # tool names in the order the AI asked for them
    assert oldest["cost_usd"] == pytest.approx(0.005)  # 0.002 + 0.003

    # The limit keeps the newest ones.
    assert [e["question"] for e in admin.recent_questions(1)] == ["And Vermont?"]

    # The address gives the same list.
    client, _ = make_client(FakeProvider([]), chat_db=str(path))
    r = client.get("/admin/events?limit=2", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["events"] == json.loads(json.dumps(events[:2]))


@pytest.mark.parametrize("limit", ["0", "501", "-1", "abc", "1.5"])
def test_recent_questions_limit_bounds(make_client, limit):
    client, _ = make_client(FakeProvider([]))
    r = client.get(f"/admin/events?limit={limit}", headers=AUTH)
    assert r.status_code == 400


def test_recent_questions_limit_edges_allowed(make_client):
    client, _ = make_client(FakeProvider([]))
    for limit in (1, 500):
        r = client.get(f"/admin/events?limit={limit}", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == {"events": [], "total": 0}


# ---------------------------------------------------------------- 20-21. the admin page


def test_admin_page_backend_url_matches_chat_page():
    # P136: admin.js has its own BACKEND_URL line with the same value as app.js. Both are read now.
    chat_url = backend_url_of(PROJECT_ROOT / "web" / "app.js")
    admin_url = backend_url_of(PROJECT_ROOT / "web" / "admin.js")
    assert admin_url == chat_url


def test_admin_page_never_uses_innerhtml():
    # P137 (as P95): server text is shown with textContent only, never as HTML.
    text = (PROJECT_ROOT / "web" / "admin.js").read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert banned not in text, banned


# ---------------------------------------------------------------- visitor ID and pages (added after the first build)
# A visitor ID is a random ID the chat page makes once per browser and sends with every
# question ("visitor_id" in the POST /chat body). It is saved in chat_events only. A
# missing or odd value is never a reason to refuse the question: it is saved as empty.

VISITOR = "3f2b8c1e-9d4a-4c7e-8b21-6a0f5e7d9c13"  # the shape crypto.randomUUID() makes


def visitor_ids(chat_db):
    con = sqlite3.connect(chat_db)
    try:
        return [row[0] for row in con.execute("SELECT visitor_id FROM chat_events ORDER BY id")]
    finally:
        con.close()


def test_chat_saves_the_visitor_id(make_client, tmp_path):
    client, settings = make_client(FakeProvider([text_reply("Hi.")]))
    r = client.post("/chat", json={"message": "hello", "visitor_id": VISITOR})
    assert r.status_code == 200 and r.json()["refusal"] is None
    assert visitor_ids(settings.chat_db) == [VISITOR]


@pytest.mark.parametrize(
    "body_extra",
    [{}, {"visitor_id": None}, {"visitor_id": 12345}, {"visitor_id": "<script>alert(1)</script>"},
     {"visitor_id": "a" * 65}, {"visitor_id": "short"}, {"visitor_id": ""}],
)  # fmt: skip
def test_missing_or_odd_visitor_id_is_saved_empty_and_the_chat_still_answers(make_client, body_extra):
    client, settings = make_client(FakeProvider([text_reply("Hi.")]))
    r = client.post("/chat", json={"message": "hello", **body_extra})
    assert r.status_code == 200
    assert r.json()["answer"] == "Hi." and r.json()["refusal"] is None
    [saved] = visitor_ids(settings.chat_db)
    assert empty(saved)


def test_a_refusal_before_the_ai_also_keeps_the_visitor_id(make_client):
    client, settings = make_client(FakeProvider([]))
    r = client.post("/chat", json={"message": "x" * 1001, "visitor_id": VISITOR})
    assert r.json()["refusal"]["cause"] == "question_too_long"
    assert visitor_ids(settings.chat_db) == [VISITOR]


def test_an_old_chat_events_table_gets_the_visitor_column_and_keeps_its_rows(tmp_path):
    path = tmp_path / "chat.sqlite"
    ChatStore(path)
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE chat_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,"
        " conversation_id TEXT, outcome TEXT NOT NULL, cause TEXT, duration_ms INTEGER, language TEXT);"
        "INSERT INTO chat_events (created_at, conversation_id, outcome, cause, duration_ms, language)"
        " VALUES ('2026-11-01T10:00:00+00:00', 'c1', 'answered', NULL, 5, 'en');"
    )
    con.close()
    admin = AdminStore(path)
    AdminStore(path)  # a second start must not fail on the column that is now there
    admin.log_event("c2", "answered", None, 7, "en", VISITOR)
    assert visitor_ids(path)[0] is None
    assert visitor_ids(path)[1] == VISITOR
    assert len(event_rows(path)) == 2


def test_metrics_count_different_visitors(tmp_path):
    path = tmp_path / "chat.sqlite"
    ChatStore(path)
    admin = AdminStore(path)
    assert admin.metrics()["visitors"] == 0
    admin.log_event("c1", "answered", None, 5, "en", "visitor-aaaa-1111")
    admin.log_event("c1", "answered", None, 5, "en", "visitor-aaaa-1111")
    admin.log_event("c2", "refused", "out_of_scope", 5, "en", "visitor-bbbb-2222")
    admin.log_event("c3", "answered", None, 5, "en", None)  # no ID: not a visitor
    assert admin.metrics()["visitors"] == 2


def test_recent_questions_show_the_visitor_of_their_chat(tmp_path):
    path = tmp_path / "chat.sqlite"
    store = ChatStore(path)
    admin = AdminStore(path)
    old_chat = store.new_chat()  # from before visitor IDs: no log row
    store.add_step(old_chat, "user", "old question")
    store.add_step(old_chat, "assistant", "old answer")
    new_chat = store.new_chat()
    store.add_step(new_chat, "user", "new question")
    store.add_step(new_chat, "assistant", "new answer")
    admin.log_event(new_chat, "answered", None, 5, "en", VISITOR)
    by_question = {e["question"]: e for e in admin.recent_questions(10)}
    assert by_question["new question"]["visitor_id"] == VISITOR
    assert by_question["new question"]["conversation_id"] == new_chat
    assert empty(by_question["old question"]["visitor_id"])


def test_events_pages_of_30(make_client, tmp_path):
    path = tmp_path / "chat.sqlite"
    clock = Clock(utc(2026, 11, 2, 9, 0, 0))
    store = ChatStore(path, now=clock)
    for i in range(65):
        clock.set(utc(2026, 11, 2, 9, 0, 0) + timedelta(minutes=i))
        chat = store.new_chat()
        store.add_step(chat, "user", f"question {i}")
        store.add_step(chat, "assistant", f"answer {i}")
    client, _ = make_client(FakeProvider([]), chat_db=str(path))

    pages = []
    for offset in (0, 30, 60):
        r = client.get(f"/admin/events?limit=30&offset={offset}", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["total"] == 65
        pages.append([e["question"] for e in r.json()["events"]])
    assert [len(p) for p in pages] == [30, 30, 5]
    everything = pages[0] + pages[1] + pages[2]
    assert everything == [f"question {i}" for i in range(64, -1, -1)]  # newest first, none twice, none missed

    # Past the end: an empty page, still with the total.
    r = client.get("/admin/events?limit=30&offset=90", headers=AUTH)
    assert r.json() == {"events": [], "total": 65}
    # No offset means the first page.
    r = client.get("/admin/events?limit=30", headers=AUTH)
    assert [e["question"] for e in r.json()["events"]] == pages[0]


@pytest.mark.parametrize("offset", ["-1", "abc", "1.5", "", "99999999999"])
def test_events_bad_offset_is_400(make_client, offset):
    client, _ = make_client(FakeProvider([]))
    r = client.get(f"/admin/events?limit=30&offset={offset}", headers=AUTH)
    assert r.status_code == 400
    assert r.json() == BAD_REQUEST


def test_admin_page_shows_30_rows_per_page_with_visitor_and_chat_columns():
    js = (PROJECT_ROOT / "web" / "admin.js").read_text()
    html = (PROJECT_ROOT / "web" / "admin.html").read_text()
    assert re.search(r"PAGE_SIZE\s*=\s*30\b", js)
    assert "offset=" in js
    for header in ("Visitor", "Chat"):
        assert re.search(rf"<th[^>]*>(<button[^>]*>)?{header}\b", html)
    assert 'id="prev-page"' in html and 'id="next-page"' in html


def test_admin_page_has_numbered_page_buttons():
    """The user asked for page numbers (1 2 3 ...), not only Previous / Next."""
    js = (PROJECT_ROOT / "web" / "admin.js").read_text()
    html = (PROJECT_ROOT / "web" / "admin.html").read_text()
    assert 'id="page-numbers"' in html
    assert "aria-current" in js  # the current page is marked for screen readers too


def test_chat_page_sends_a_visitor_id():
    js = (PROJECT_ROOT / "web" / "app.js").read_text()
    assert "visitor_id" in js
    assert "randomUUID" in js


# ---------------------------------------------------------------- sorting the recent questions
# GET /admin/events?sort=<column>&order=asc|desc sorts ALL questions on the server, then cuts
# the page, so page 2 continues page 1. Columns: time, visitor, chat, question, result,
# tools, cost. Default: time, newest first. Empty values (no visitor) go last either way.
# Equal values keep newest first, so the order is the same on every request.


@pytest.fixture
def sort_db(tmp_path):
    """Four questions in four chats, one minute apart (q0 oldest … q3 newest)."""
    path = tmp_path / "chat.sqlite"
    clock = Clock(utc(2026, 11, 2, 9, 0, 0))
    store = ChatStore(path, now=clock)
    admin = AdminStore(path, now=clock)
    plan = [
        # question,        visitor,              tools,                                cost,  refused
        ("banana flights", "visitor-cccc-3333", ["route_mix"],                         0.003, False),
        ("Apple airports", None,                [],                                    0.0,   True),
        ("cherry delays",  "visitor-aaaa-1111", ["find_airports", "airport_profile"],  0.009, False),
        ("date growth",    "visitor-bbbb-2222", ["rank_airports"],                     0.001, False),
    ]  # fmt: skip
    chats = []
    for i, (question, visitor, tools, cost, refused) in enumerate(plan):
        clock.set(utc(2026, 11, 2, 9, i, 0))
        chat = store.new_chat()
        chats.append(chat)
        store.add_step(chat, "user", question)
        if tools:
            store.add_step(chat, "assistant", None, tool_calls=[{"id": f"t{j}", "name": n, "args": {}}
                                                                for j, n in enumerate(tools)],
                           model="m", input_tokens=1, output_tokens=1, cost_usd=cost)  # fmt: skip
        store.add_step(chat, "assistant", REFUSALS["out_of_scope"] if refused else "ok")
        admin.log_event(chat, "refused" if refused else "answered", "out_of_scope" if refused else None, 5, "en",
                        visitor)  # fmt: skip
    return path, chats


def questions(events):
    return [e["question"] for e in events]


@pytest.mark.parametrize(
    "sort, order, expected",
    [
        ("time", "desc", ["date growth", "cherry delays", "Apple airports", "banana flights"]),
        ("time", "asc", ["banana flights", "Apple airports", "cherry delays", "date growth"]),
        ("question", "asc", ["Apple airports", "banana flights", "cherry delays", "date growth"]),  # A-Z, any case
        ("question", "desc", ["date growth", "cherry delays", "banana flights", "Apple airports"]),
        ("cost", "desc", ["cherry delays", "banana flights", "date growth", "Apple airports"]),
        ("cost", "asc", ["Apple airports", "date growth", "banana flights", "cherry delays"]),
        # visitor IDs aaaa < bbbb < cccc; the question without a visitor is last both ways
        ("visitor", "asc", ["cherry delays", "date growth", "banana flights", "Apple airports"]),
        ("visitor", "desc", ["banana flights", "date growth", "cherry delays", "Apple airports"]),
        # tools as shown: the names joined, A-Z; no tools ("none") is empty, so last
        ("tools", "asc", ["cherry delays", "date growth", "banana flights", "Apple airports"]),
        # result: "answered" before "refused (…)"; equal ones newest first
        ("result", "asc", ["date growth", "cherry delays", "banana flights", "Apple airports"]),
        ("result", "desc", ["Apple airports", "date growth", "cherry delays", "banana flights"]),
    ],
)
def test_recent_questions_sorted_by_any_column(sort_db, sort, order, expected):
    path, _ = sort_db
    assert questions(AdminStore(path).recent_questions(10, 0, sort, order)) == expected


def test_sort_by_chat_follows_the_chat_ids(sort_db):
    path, chats = sort_db
    events = AdminStore(path).recent_questions(10, 0, "chat", "asc")
    assert [e["conversation_id"] for e in events] == sorted(chats)


def test_sorted_pages_continue_each_other(sort_db, make_client):
    path, _ = sort_db
    client, _ = make_client(FakeProvider([]), chat_db=str(path))
    full = client.get("/admin/events?limit=4&sort=cost&order=desc", headers=AUTH).json()
    first = client.get("/admin/events?limit=2&offset=0&sort=cost&order=desc", headers=AUTH).json()
    second = client.get("/admin/events?limit=2&offset=2&sort=cost&order=desc", headers=AUTH).json()
    assert questions(first["events"]) + questions(second["events"]) == questions(full["events"])
    assert first["total"] == second["total"] == 4


def test_no_sort_means_newest_first(sort_db, make_client):
    path, _ = sort_db
    client, _ = make_client(FakeProvider([]), chat_db=str(path))
    r = client.get("/admin/events?limit=10", headers=AUTH)
    assert questions(r.json()["events"]) == ["date growth", "cherry delays", "Apple airports", "banana flights"]


@pytest.mark.parametrize("query", ["sort=price", "sort=", "order=up", "sort=cost&order=DESC", "sort=time;drop"])
def test_bad_sort_is_400(make_client, query):
    client, _ = make_client(FakeProvider([]))
    r = client.get(f"/admin/events?limit=30&{query}", headers=AUTH)
    assert r.status_code == 400
    assert r.json() == BAD_REQUEST


def test_admin_page_sorts_by_header_click_and_starts_newest_first():
    js = (PROJECT_ROOT / "web" / "admin.js").read_text()
    html = (PROJECT_ROOT / "web" / "admin.html").read_text()
    for column in ("time", "visitor", "chat", "question", "result", "tools", "cost"):
        assert f'data-sort="{column}"' in html
    assert "sort=" in js and "order=" in js
    # Every page load starts with Time, newest first (the user's choice): the sort is not saved.
    assert "localStorage" not in js
    assert re.search(r'DEFAULT_SORT\s*=\s*\{\s*sort:\s*"time",\s*order:\s*"desc"\s*\}', js)
    assert re.search(r"let currentSort\s*=\s*\{\s*\.\.\.DEFAULT_SORT\s*\}", js)
