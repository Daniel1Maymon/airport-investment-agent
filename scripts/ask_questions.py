"""The question script: asks a fixed list of questions through the agent and saves the answers.

What it is:   Reads the question list (scripts/questions.yaml), asks every question through
              the agent loop, and saves each answer, the tools called with their settings,
              the tokens and the cost to a JSON file and a Markdown file of the same name.
Why we need:  To check the agent on the exam questions, follow-ups, other investor
              questions, "no data" questions and attacks in one run, and to read the
              answers back afterwards (the real-data check of Step 15).
Used by:      a person at the terminal: python -m scripts.ask_questions [--group NAME].
              tests: test_step15_question_script.py.
Uses:         scripts/questions.yaml (read with PyYAML), app/agent/loop.py (run_turn),
              app/store.py (ChatStore), app/agent/provider.py (OpenRouterProvider),
              app/config.py (Settings), app/db.py (open_airport_db).
Main parts:   GROUPS - the five question groups, in the order they run (P72).
              load_questions(path) - read the question file and check its shape.
              run_questions(questions, provider, store, con, out_dir, now=None) - ask
                every question, save the JSON and Markdown files, return the JSON path.
              main(argv=None) - the command: real AI, real data, files in scripts/results/.
Design:       docs/implementation-plan.md Step 15, P72-P74; docs/decisions.md 7.21;
              docs/agent.md "Safety".

How one run works, in short:
  1. Read the question list: 5 groups, each a list of chats, each chat a list of questions.
  2. For each chat, ask its questions in order through run_turn. The first question starts
     a new chat; the next ones reuse its chat ID, so they are follow-ups that see the
     earlier answers.
  3. After each question, note the answer (or refusal), the tools the AI asked for, and
     the tokens and cost of the AI calls saved during that question.
  4. If a question crashes, note the error, skip the rest of that chat (its history may
     be broken), and go on with the next chat.
  5. Save everything to questions-<UTC time>.json, plus a .md file made from it for reading.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.agent.loop import run_turn
from app.agent.provider import OpenRouterProvider
from app.config import Settings
from app.db import open_airport_db
from app.store import ChatStore

# The five question groups, in the order they run (P72).
GROUPS = ["exam", "follow_up", "other", "no_data", "attack"]
# The note for questions not asked because an earlier question in the same chat crashed (P73).
SKIPPED = "skipped: an earlier question in this chat failed"
# Where the command saves its files, and where the question list lives (next to this file).
RESULTS_DIR = Path(__file__).resolve().parent / "results"
QUESTIONS_FILE = Path(__file__).resolve().parent / "questions.yaml"


def load_questions(path):
    """Read the question file: {group: [chat, ...]}, each chat a list of 1+ question texts.

    Raises ValueError if a group is missing, unknown or empty, or a chat is not a list of texts.
    """
    # safe_load only reads plain data (texts, lists); it never runs code from the file.
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    # Exactly the five groups, no more and no fewer.
    if not isinstance(data, dict) or set(data) != set(GROUPS):
        found = list(data) if isinstance(data, dict) else data
        raise ValueError(f"The question file must have exactly the groups {GROUPS}, not {found}.")
    # Each group: a non-empty list of chats; each chat: a non-empty list of question texts.
    for group in GROUPS:
        chats = data[group]
        if not isinstance(chats, list) or not chats:
            raise ValueError(f"Group {group!r} must be a non-empty list of chats.")
        for chat in chats:
            if not isinstance(chat, list) or not chat or not all(isinstance(q, str) for q in chat):
                raise ValueError(f"In group {group!r}, each chat must be a list of 1+ question texts: {chat!r}")
    # Give the groups back in the fixed GROUPS order.
    return {group: data[group] for group in GROUPS}


def _turn_costs(store, chat_id, before):
    """Model, tokens and cost of one turn, from the AI steps saved during it (P74).

    `before` is how many steps the chat had before this turn, so older turns are not counted.
    Every AI reply is saved with its model, tokens and price, so adding them up gives the
    cost of this question. A missing value (None) is skipped.
    """
    # Only this turn's steps, and of those only the AI's replies (role "assistant").
    steps = store.load_steps(chat_id)[before:] if chat_id and store.exists(chat_id) else []
    ai_steps = [s for s in steps if s.role == "assistant"]
    # A refusal saved by Python (e.g. "AI unavailable") has no model, so it is skipped here.
    models = [s.model for s in ai_steps if s.model is not None]
    return {
        "model": models[-1] if models else None,
        "input_tokens": sum(s.input_tokens for s in ai_steps if s.input_tokens is not None),
        "output_tokens": sum(s.output_tokens for s in ai_steps if s.output_tokens is not None),
        "cost_usd": sum(s.cost_usd for s in ai_steps if s.cost_usd is not None),
    }


def _row(group, chat_no, turn_no, chat_id, question):
    """One empty result row; the caller fills in what happened."""
    return {
        "group": group, "chat": chat_no, "turn": turn_no, "chat_id": chat_id, "question": question,
        "answer": "", "refusal": None, "tools": [], "model": None,
        "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "error": None,
    }  # fmt: skip


def _markdown(data):
    """The Markdown report, made only from the saved JSON data (P74).

    Same content as the JSON file, laid out for a person to read: the total cost first,
    then one section per question with the answer, the tools and the cost.
    """
    # The top of the report: when the run started and what it cost in all.
    lines = [
        "# Question run",
        "",
        f"Started (UTC): {data['started_at']}",
        "",
        f"Total cost: ${data['total_cost_usd']:.4f}",
        "",
    ]
    # One section per question, in the order asked.
    for row in data["questions"]:
        lines += [f"## {row['group']} - chat {row['chat']}, turn {row['turn']}", ""]
        lines += [f"**Question:** {row['question']}", ""]
        # A crash or skip, a refusal, or a normal answer: only one of them is shown.
        if row["error"]:
            lines += [f"**Error:** {row['error']}", ""]
        elif row["refusal"]:
            lines += [f"**Refusal ({row['refusal']['cause']}):** {row['refusal']['message']}", ""]
        else:
            lines += ["**Answer:**", "", row["answer"], ""]
        # Each tool the AI asked for, with its settings and whether it ran without error.
        lines.append("**Tools:**")
        for tool in row["tools"]:
            status = "ok" if tool["ok"] else "error"
            lines.append(f"- {tool['name']} `{json.dumps(tool['args'])}` ({status})")
        if not row["tools"]:
            lines.append("- none")
        lines += ["", f"Cost: ${row['cost_usd']:.4f} (model {row['model']})", ""]
    return "\n".join(lines)


def run_questions(questions, provider, store, con, out_dir, now=None):
    """Ask every question, save the JSON and Markdown files in `out_dir`, return the JSON path.

    Groups run in the GROUPS order. In each chat, the first question starts a new chat and
    the rest are follow-ups in that same chat. If a question crashes, the rest of its chat
    are skipped and the run goes on with the next chat (P73).
    questions: the question list, as load_questions gives it.
    provider:  who answers as the AI (OpenRouter for real, a fake one in tests).
    store:     the chat history database (SQLite); each chat is saved there.
    con:       the read-only airport database (DuckDB), used by the tools.
    out_dir:   the folder for the two files (made if missing).
    now:       a function returning a timezone-aware datetime (None = the real UTC clock),
               so tests can fix the time used in the file names.
    """
    # The start time (in UTC) names the files, so each run gets its own pair of files.
    started = (now or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    rows = []
    for group in GROUPS:
        for chat_no, chat in enumerate(questions[group], start=1):
            chat_id = None  # None: the first question starts a new chat
            failed = False  # True once a question in this chat crashed
            for turn_no, question in enumerate(chat, start=1):
                row = _row(group, chat_no, turn_no, chat_id, question)
                rows.append(row)
                # After a crash the chat's history may be broken, so don't ask the rest.
                if failed:
                    row["error"] = SKIPPED
                    continue
                # Steps already in the chat, so only this turn's AI steps are counted.
                before = len(store.load_steps(chat_id)) if chat_id else 0
                try:
                    result = run_turn(store, con, provider, chat_id, question)
                except Exception as exc:  # a crash: note it, skip the rest of this chat
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    row.update(_turn_costs(store, chat_id, before))
                    failed = True
                    continue
                # Keep the chat ID, so the next question in this chat is a follow-up.
                chat_id = result.chat_id
                row["chat_id"] = chat_id
                row["answer"] = result.answer
                if result.refusal:
                    row["refusal"] = {"cause": result.refusal.cause, "message": result.refusal.message}
                # The tools the AI asked for; ok = False when a tool gave back an error.
                row["tools"] = [
                    {"name": e["name"], "args": e["args"], "ok": "error" not in e["result"]}
                    for e in result.tool_events
                ]
                row.update(_turn_costs(store, chat_id, before))

    # Save the whole run: the JSON file is the full record, the .md file is for reading.
    data = {
        "started_at": started.isoformat(),
        "total_cost_usd": sum(row["cost_usd"] for row in rows),
        "questions": rows,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"questions-{started:%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    path.with_suffix(".md").write_text(_markdown(data), encoding="utf-8")
    return path


def main(argv=None):
    """The command: run the question list with the real AI on the real data.

    --group NAME asks only that group (e.g. --group attack), to save time and money.
    """
    parser = argparse.ArgumentParser(description="Ask the fixed question list through the airport agent.")
    parser.add_argument("--group", choices=GROUPS, help="ask only this group of questions")
    args = parser.parse_args(argv)

    questions = load_questions(QUESTIONS_FILE)
    if args.group:
        # Only one group: the other groups get no chats.
        questions = {g: (chats if g == args.group else []) for g, chats in questions.items()}

    # Read the settings (key, model, database files) from the environment.
    settings = Settings()
    try:
        provider = OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model)
    except ValueError:
        sys.exit("Set OPENROUTER_API_KEY and OPENROUTER_MODEL first (set -a; source .env; set +a).")
    store = ChatStore(settings.chat_db)  # chat history
    con = open_airport_db(settings.airports_db)  # airport data, read-only
    try:
        path = run_questions(questions, provider, store, con, RESULTS_DIR)
    finally:
        con.close()

    total = json.loads(path.read_text(encoding="utf-8"))["total_cost_usd"]
    print(f"Saved: {path}")
    print(f"Saved: {path.with_suffix('.md')}")
    print(f"Total cost: ${total:.4f}")


if __name__ == "__main__":
    main()
