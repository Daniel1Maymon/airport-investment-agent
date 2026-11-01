"""The admin side of chat.sqlite: the log rows, the AI switch and the dashboard numbers.

What it is:   The `AdminStore` class. It adds two small tables to chat.sqlite
              (`chat_events`: one row per POST /chat request; `app_settings`: the AI on/off
              switch), writes and reads them, and works out the dashboard numbers from them
              and from the chat history that is already saved.
Why we need:  The owner needs to see what the agent costs, what people ask, how often it
              refuses, and which tools the AI picks, and needs one switch that stops all AI
              calls without a redeploy. Some refusals (a question too long, "still
              answering", an unknown chat) and every timeout never reach the chat history,
              so a separate log row is needed for an honest refusal rate.
Used by:      app/api.py (log_event after each POST /chat reply, ai_enabled in check 4).
              app/admin.py (the four admin addresses).
              tests: test_step19_admin.py.
Uses:         chat.sqlite: the tables conversations and messages (read only, never changed),
              chat_events and app_settings (made here). app/store.py (ChatStore.load_steps),
              app/presenters.py (rebuild_turns), app/refusals.py (REFUSALS),
              app/tools/base.py (TOOLS, the tool registry). Standard library sqlite3, json, math.
Main parts:   AdminStore(path, now=None) - log_event, ai_enabled, ai_state, set_ai_enabled,
                metrics, recent_questions.
Design:       docs/admin-dashboard.md; docs/schema.md part 3; docs/api.md section 4;
              docs/decisions.md 7.26, 7.27; docs/implementation-plan.md P122-P135.

How the dashboard numbers are made, in short (example: the owner opens the dashboard):
  1. Questions, chats, cost and tokens come from the chat history the app already keeps:
     every `user` step is one question, every `conversations` row is one chat, cost and
     tokens are added up over the `assistant` steps (an empty cost counts as 0).
  2. Requests, refusal rate and answer times come from `chat_events` only, one row per
     POST /chat reply (also the replies refused before the AI ran).
  3. Questions per day: the last 30 days (UTC), ending today, with 0 for quiet days.
  4. Tools: every tool request the AI made, counted by tool name; tools never picked are
     listed with 0, so an unused tool is easy to spot.
  5. Recent questions: the newest questions of all chats, each with the answer and the
     "How I got this" steps rebuilt by the same code that reloads a chat for the user.

Every method opens and closes its own connection (as ChatStore), so it is safe to use
from the API's threads. Only CREATE TABLE IF NOT EXISTS is run at start, so the chats
already on the live disk stay exactly as they are (P126).
"""

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

import app.tools  # noqa: F401  (fills the tool registry TOOLS, so unused tools can be listed)
from app.presenters import rebuild_turns
from app.refusals import REFUSALS
from app.store import ChatStore
from app.tools.base import TOOLS

# The two new tables (schema.md part 3). IF NOT EXISTS: made on the first start after the
# deploy, left alone after that; conversations and messages are never touched.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    conversation_id TEXT,
    outcome TEXT NOT NULL,
    cause TEXT,
    duration_ms INTEGER,
    language TEXT,
    visitor_id TEXT
);
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    note TEXT
);
"""

# The columns the recent questions can be sorted by (GET /admin/events?sort=), each with how
# one question's value is read. None = empty, always listed last.
SORT_KEYS = {
    "time": lambda e: e["time"],
    "visitor": lambda e: e["visitor_id"] or None,
    "chat": lambda e: e["conversation_id"] or None,
    "question": lambda e: (e["question"] or "").casefold() or None,
    # As the page shows it: "answered" comes before "refused (cause)".
    "result": lambda e: "refused (" + e["refusal_cause"] + ")" if e["refusal_cause"] else "answered",
    # As the page shows it: the tool names joined; no tools is empty.
    "tools": lambda e: ", ".join(e["tools"]) or None,
    "cost": lambda e: e["cost_usd"] or 0,
}
SORT_ORDERS = ("asc", "desc")

# The one key of app_settings in version 1: the AI on/off switch. No row means ON.
AI_ENABLED_KEY = "ai_enabled"
# How many days the "questions per day" bars cover, ending today (P133).
DAYS_SHOWN = 30


def _utc_now():
    """The real clock, in UTC (the default for `now`)."""
    return datetime.now(timezone.utc)


def _nearest_rank(sorted_values, share):
    """The value at position ceil(share × n), counting from 1 (the "nearest rank" rule, P132).

    Example: times [2, 3, 4200, 5000, 6100, 7400, 9000, 60010] (n = 8, made up):
    share 0.5 → position 4 → 5000; share 0.95 → position ceil(7.6) = 8 → 60010.
    An empty list gives 0.
    """
    if not sorted_values:
        return 0
    position = max(1, math.ceil(share * len(sorted_values)))
    return sorted_values[position - 1]


class AdminStore:
    """The two admin tables in chat.sqlite, plus the dashboard numbers (P122-P135)."""

    def __init__(self, path, now=None):
        """path: the chat.sqlite file. now: a function giving the time (tests pass a fixed clock).

        Makes the two admin tables if they are not there yet (P126).
        """
        self.path = path
        self.now = now or _utc_now
        con = self._connect()
        try:
            con.executescript(_SCHEMA)
            # A chat_events table made before visitor IDs gets the new column; its rows are kept.
            columns = {row[1] for row in con.execute("PRAGMA table_info(chat_events)")}
            if "visitor_id" not in columns:
                con.execute("ALTER TABLE chat_events ADD COLUMN visitor_id TEXT")
        finally:
            con.close()

    def _connect(self):
        """A new connection; isolation_level=None means each statement is saved at once."""
        return sqlite3.connect(self.path, isolation_level=None)

    def _time(self):
        """The current time as UTC ISO text, written like ChatStore's, e.g. "2026-11-02T10:00:00+00:00"."""
        return self.now().astimezone(timezone.utc).isoformat()

    # ---------------------------------------------------------------- the log row (P127)

    def log_event(self, conversation_id, outcome, cause, duration_ms, language, visitor_id=None):
        """Save one row for one POST /chat reply. The question text is never saved here.

        Example: log_event("c7f3…", "refused", "airport_not_found", 6100, "en", "3f2b8c1e-…").
        visitor_id: the random ID the chat page keeps per browser, or None.
        outcome: "answered", "refused" or "error". cause: the refusal key, or "timeout",
        "crash", "bad_request" for an error, or None when answered.
        """
        con = self._connect()
        try:
            con.execute(
                "INSERT INTO chat_events (created_at, conversation_id, outcome, cause, duration_ms, language,"
                " visitor_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self._time(), conversation_id, outcome, cause, duration_ms, language, visitor_id),
            )
        finally:
            con.close()

    # ---------------------------------------------------------------- the AI switch (P130, P131)

    def ai_state(self):
        """The switch as the admin page gets it, e.g. {"enabled": False, "updated_at": "…", "note": "cost check"}.

        No saved row → {"enabled": True, "updated_at": None, "note": None} (no row means ON).
        """
        con = self._connect()
        try:
            row = con.execute(
                "SELECT value, updated_at, note FROM app_settings WHERE key = ?", (AI_ENABLED_KEY,)
            ).fetchone()
        finally:
            con.close()
        if row is None:
            return {"enabled": True, "updated_at": None, "note": None}
        value, updated_at, note = row
        # Only the exact text "false" turns the AI off; anything else counts as ON.
        return {"enabled": value != "false", "updated_at": updated_at, "note": note}

    def ai_enabled(self):
        """True when the AI may answer, False when the owner switched it off."""
        return self.ai_state()["enabled"]

    def set_ai_enabled(self, enabled, note=None):
        """Save the wanted state (not a flip) with the time and the note, and return the new state.

        Pressing "off" twice leaves it off, and two open dashboards can't undo each other.
        The row is replaced, so a save without a note clears the old note.
        """
        con = self._connect()
        try:
            con.execute(
                "INSERT OR REPLACE INTO app_settings (key, value, updated_at, note) VALUES (?, ?, ?, ?)",
                (AI_ENABLED_KEY, "true" if enabled else "false", self._time(), note),
            )
        finally:
            con.close()
        return self.ai_state()

    # ---------------------------------------------------------------- the numbers (P132-P134)

    def metrics(self):
        """Every number of GET /admin/metrics (api.md section 4), as one dict.

        Example (made-up numbers): {"questions": 4, "chats": 3, "cost_usd": 0.0075,
        "cost_per_question_usd": 0.0019, …, "questions_per_day": [{"day": "2026-10-22",
        "count": 0}, …], "refusals_by_cause": [{"cause": "question_too_long", "count": 2}],
        "tools": [{"name": "rank_airports", "count": 2}, …]}.
        """
        today = self.now().astimezone(timezone.utc).date()
        first_day = today - timedelta(days=DAYS_SHOWN - 1)
        con = self._connect()
        try:
            # 1. From the chat history: questions, chats, cost, tokens. An empty value counts as 0.
            (questions,) = con.execute("SELECT COUNT(*) FROM messages WHERE role = 'user'").fetchone()
            (chats,) = con.execute("SELECT COUNT(*) FROM conversations").fetchone()
            cost, input_tokens, output_tokens = con.execute(
                "SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0)"
                " FROM messages WHERE role = 'assistant'"
            ).fetchone()
            # 3. Questions per day. ChatStore always writes UTC ISO text ("2026-11-20T09:00:00+00:00"),
            # so its first 10 characters are the UTC day.
            per_day_rows = con.execute(
                "SELECT substr(created_at, 1, 10), COUNT(*) FROM messages"
                " WHERE role = 'user' AND substr(created_at, 1, 10) >= ? GROUP BY 1",
                (first_day.isoformat(),),
            ).fetchall()
            # 4. Every tool request the AI made (one JSON list per assistant step).
            call_lists = con.execute(
                "SELECT tool_calls FROM messages WHERE role = 'assistant' AND tool_calls IS NOT NULL"
            ).fetchall()
            # 2. From the log rows only.
            event_rows = con.execute("SELECT created_at, outcome, duration_ms FROM chat_events ORDER BY id").fetchall()
            refusal_rows = con.execute(
                "SELECT cause, COUNT(*) FROM chat_events WHERE outcome = 'refused' GROUP BY cause"
            ).fetchall()
            # Different browsers that sent a question (rows without a visitor ID don't count).
            (visitors,) = con.execute(
                "SELECT COUNT(DISTINCT visitor_id) FROM chat_events WHERE visitor_id IS NOT NULL"
            ).fetchone()
        finally:
            con.close()

        # Questions per day: one entry for each of the 30 days, oldest first, 0 when quiet.
        counts_by_day = dict(per_day_rows)
        questions_per_day = []
        for i in range(DAYS_SHOWN):
            day = (first_day + timedelta(days=i)).isoformat()
            questions_per_day.append({"day": day, "count": counts_by_day.get(day, 0)})

        # Tools: each entry of a tool request counts once; registered tools never used get 0.
        tool_counts = {name: 0 for name in TOOLS}
        for (calls_json,) in call_lists:
            for call in json.loads(calls_json) or []:
                tool_counts[call["name"]] = tool_counts.get(call["name"], 0) + 1
        # Highest count first, then by name A→Z.
        tools = [{"name": n, "count": c} for n, c in sorted(tool_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

        # Requests, refusal rate and answer times: from chat_events only. Errors are not refusals.
        requests = len(event_rows)
        refused = sum(1 for _t, outcome, _ms in event_rows if outcome == "refused")
        durations = sorted(ms for _t, _o, ms in event_rows if ms is not None)
        refusals_by_cause = [
            {"cause": cause, "count": count}
            for cause, count in sorted(refusal_rows, key=lambda row: (-row[1], row[0] or ""))
        ]

        return {
            "questions": questions,
            "chats": chats,
            "cost_usd": cost,
            # 0 when there are no questions (no division by zero).
            "cost_per_question_usd": round(cost / questions, 4) if questions else 0,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            # The first log row's time: requests, refusal rate and times count only from then.
            "events_since": event_rows[0][0] if event_rows else None,
            "requests": requests,
            "refusal_rate": refused / requests if requests else 0,
            "duration_p50_ms": _nearest_rank(durations, 0.5),
            "duration_p95_ms": _nearest_rank(durations, 0.95),
            "questions_per_day": questions_per_day,
            "refusals_by_cause": refusals_by_cause,
            "tools": tools,
            "visitors": visitors,
        }

    # ---------------------------------------------------------------- recent questions (P135)

    def question_count(self):
        """How many questions there are in all chats (the "total" of GET /admin/events)."""
        con = self._connect()
        try:
            return con.execute("SELECT COUNT(*) FROM messages WHERE role = 'user'").fetchone()[0]
        finally:
            con.close()

    def recent_questions(self, limit, offset=0, sort="time", order="desc"):
        """One page of the questions of all chats, as GET /admin/events lists them.

        offset: how many questions to skip first (for pages: 0, 30, 60, …).
        sort: a key of SORT_KEYS; order: "asc" or "desc". The default is newest first.
        Every question is sorted before the page is cut, so page 2 continues page 1.
        Equal values keep newest first, and empty values go last in both directions.
        Each: {"time", "conversation_id", "visitor_id", "question", "answer", "refusal_cause", "steps", "tools", "cost_usd"}.
        "tools" is the tool names the AI asked for in that turn, in order (a repeat is listed again).
        Example (made up): {"time": "2026-11-02T09:00:00+00:00", "conversation_id": "c7f3…",
        "question": "Airports in Massachusetts?", "answer": "BOS is the largest.",
        "refusal_cause": None, "steps": ["Looked up airports (states: MA)"], "tools": ["find_airports"],
        "cost_usd": 0.005}.
        """
        if sort not in SORT_KEYS or order not in SORT_ORDERS:
            raise ValueError(f"unknown sort {sort!r} {order!r}")
        # 1. The user steps, newest first (rowid breaks a tie between two at the same time).
        # Sorted by time, SQL cuts the page, so only 30 questions are rebuilt. Sorted by
        # anything else, every question is rebuilt and sorted here, then the page is cut.
        by_time = sort == "time"
        direction = "DESC" if order == "desc" or not by_time else "ASC"
        page_sql = " LIMIT ? OFFSET ?" if by_time else ""
        con = self._connect()
        try:
            rows = con.execute(
                "SELECT conversation_id, seq FROM messages WHERE role = 'user'"
                f" ORDER BY created_at {direction}, rowid {direction}{page_sql}",
                (limit, offset) if by_time else (),
            ).fetchall()
            # The visitor of each chat: the newest log row of that chat with a visitor ID.
            # Chats from before visitor IDs have none.
            visitor_of = dict(
                con.execute(
                    "SELECT conversation_id, visitor_id FROM chat_events WHERE visitor_id IS NOT NULL"
                    " ORDER BY id"
                ).fetchall()
            )
        finally:
            con.close()

        # 2. Each chat is loaded and rebuilt once, with the same code as reloading a chat.
        chat_store = ChatStore(self.path)
        chats = {}
        events = []
        for chat_id, seq in rows:
            if chat_id not in chats:
                steps = chat_store.load_steps(chat_id)
                chats[chat_id] = (steps, rebuild_turns(steps))
            steps, turns = chats[chat_id]
            # 3. Find this question's turn. A turn = a user step up to the next user step,
            # grouped the same way as rebuild_turns, so group number i is turns[i].
            groups = []
            for step in steps:
                if step.role == "user":
                    groups.append([step])
                elif groups:
                    groups[-1].append(step)
            turn_index = next(i for i, group in enumerate(groups) if group[0].seq == seq)
            turn_steps = groups[turn_index]
            turn = turns[turn_index]
            question_step = turn_steps[0]
            cause = turn["refusal"]["cause"] if turn["refusal"] else None
            events.append(
                {
                    "time": question_step.created_at,
                    "conversation_id": chat_id,
                    "visitor_id": visitor_of.get(chat_id),
                    "question": question_step.content,
                    # For a refusal the answer holds the fixed refusal message (api.md section 4).
                    "answer": REFUSALS[cause] if cause else turn["answer"],
                    "refusal_cause": cause,
                    "steps": turn["steps"],
                    "tools": [
                        call["name"] for s in turn_steps if s.role == "assistant" for call in (s.tool_calls or [])
                    ],
                    # The turn's cost: its assistant steps added up, an empty cost counts as 0.
                    "cost_usd": sum(s.cost_usd or 0 for s in turn_steps if s.role == "assistant"),
                }
            )
        if by_time:
            return events
        # 4. Sort everything (Python's sort keeps equal values in their newest-first order),
        # empty values last, then cut the page.
        key = SORT_KEYS[sort]
        filled = [e for e in events if key(e) is not None]
        empty = [e for e in events if key(e) is None]
        filled.sort(key=key, reverse=order == "desc")
        return (filled + empty)[offset : offset + limit]
