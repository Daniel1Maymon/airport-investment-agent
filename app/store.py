"""Chat history in SQLite: chats and their steps, saved on the server.

What it is:   The `ChatStore` class: starts a chat, saves one step of a chat (a question,
              a tool request, a tool result or an answer) and loads all steps in order.
Why we need:  The browser keeps only the chat ID; the server keeps the history, so a
              follow-up question sees the earlier steps, even after a restart.
Used by:      app/agent/loop.py, app/agent/cli.py.
              tests: test_step13_store.py, test_step14_agent_loop.py.
              app/api.py (ChatStore).
Uses:         the standard library only (sqlite3, json, uuid, datetime, dataclasses).
              No other project file.
Main parts:   ChatStore - new_chat, exists, add_step, load_steps.
              Step - one saved step (a frozen dataclass).
              ChatNotFound - the error for an unknown chat ID.
Design:       docs/schema.md part 2, docs/decisions.md 7.9 and 7.10,
              docs/implementation-plan.md P43-P48.

Every method opens and closes its own connection, so the store is safe to use from
the API's threads. `add_step` gets the next step number inside one BEGIN IMMEDIATE
transaction, so two saves at once can't get the same number.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

ROLES = ("user", "assistant", "tool")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_call_id TEXT,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_usd REAL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (conversation_id, seq)
);
"""


class ChatNotFound(Exception):
    """The chat ID is not in the conversations table."""


@dataclass(frozen=True)
class Step:
    seq: int
    role: str
    content: str | None
    tool_calls: list | None
    tool_call_id: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    created_at: str


def _utc_now():
    return datetime.now(timezone.utc)


class ChatStore:
    def __init__(self, path, now=None):
        self.path = path
        self.now = now or _utc_now
        con = self._connect()
        try:
            con.executescript(_SCHEMA)
        finally:
            con.close()

    def _connect(self):
        # isolation_level=None: no hidden transactions; add_step starts its own.
        con = sqlite3.connect(self.path, isolation_level=None)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _time(self):
        return self.now().astimezone(timezone.utc).isoformat()

    def new_chat(self):
        chat_id = str(uuid.uuid4())
        now = self._time()
        con = self._connect()
        try:
            con.execute(
                "INSERT INTO conversations (id, created_at, last_active_at) VALUES (?, ?, ?)",
                (chat_id, now, now),
            )
        finally:
            con.close()
        return chat_id

    def exists(self, chat_id):
        con = self._connect()
        try:
            row = con.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (chat_id,)
            ).fetchone()
        finally:
            con.close()
        return row is not None

    def add_step(
        self,
        chat_id,
        role,
        content,
        tool_calls=None,
        tool_call_id=None,
        model=None,
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
    ):
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}, got {role!r}")
        calls_json = None if tool_calls is None else json.dumps(tool_calls)
        now = self._time()
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                if con.execute(
                    "SELECT 1 FROM conversations WHERE id = ?", (chat_id,)
                ).fetchone() is None:
                    raise ChatNotFound(chat_id)
                (seq,) = con.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE conversation_id = ?",
                    (chat_id,),
                ).fetchone()
                con.execute(
                    "INSERT INTO messages (conversation_id, seq, role, content, tool_calls,"
                    " tool_call_id, model, input_tokens, output_tokens, cost_usd, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (chat_id, seq, role, content, calls_json, tool_call_id, model,
                     input_tokens, output_tokens, cost_usd, now),
                )
                con.execute(
                    "UPDATE conversations SET last_active_at = ? WHERE id = ?",
                    (now, chat_id),
                )
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()
        return seq

    def load_steps(self, chat_id):
        con = self._connect()
        try:
            if con.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (chat_id,)
            ).fetchone() is None:
                raise ChatNotFound(chat_id)
            rows = con.execute(
                "SELECT seq, role, content, tool_calls, tool_call_id, model,"
                " input_tokens, output_tokens, cost_usd, created_at"
                " FROM messages WHERE conversation_id = ? ORDER BY seq",
                (chat_id,),
            ).fetchall()
        finally:
            con.close()
        return [
            Step(seq, role, content, None if calls is None else json.loads(calls),
                 call_id, model, tin, tout, cost, created)
            for seq, role, content, calls, call_id, model, tin, tout, cost, created in rows
        ]
