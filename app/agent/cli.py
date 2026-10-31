"""Command line for trying one question: python -m app.agent.cli "question" [--chat ID].

What it is:   A small command that runs one chat turn with the real AI and prints the
              answer, the tools used with their settings, the cost and the chat ID.
Why we need:  To try the agent on real data before the backend API and chat page exist.
Used by:      a person at the terminal (not unit-tested).
Uses:         app/config.py (Settings), app/db.py (open_airport_db), app/store.py
              (ChatStore), app/agent/provider.py (OpenRouterProvider),
              app/agent/loop.py (run_turn). Settings come from environment variables
              (set -a; source .env; set +a).
Main parts:   main(argv=None) - parse the arguments, run one turn, print the result.
Design:       docs/implementation-plan.md P67.
"""

import argparse
import json
import sys

from app.agent.loop import run_turn
from app.agent.provider import OpenRouterProvider
from app.config import Settings
from app.db import open_airport_db
from app.store import ChatStore


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask the airport agent one question.")
    parser.add_argument("question", help="the question to ask")
    parser.add_argument("--chat", help="the chat ID of an earlier chat, for a follow-up")
    args = parser.parse_args(argv)

    # Read the settings (key, model, database files) from the environment.
    settings = Settings()
    try:
        provider = OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model)
    except ValueError:
        sys.exit("Set OPENROUTER_API_KEY and OPENROUTER_MODEL first (set -a; source .env; set +a).")
    store = ChatStore(settings.chat_db)  # chat history
    con = open_airport_db(settings.airports_db)  # airport data, read-only
    try:
        # Count the steps already in the chat, so we can price only this turn's new steps.
        before = len(store.load_steps(args.chat)) if args.chat and store.exists(args.chat) else 0
        # No --chat -> args.chat is None -> run_turn starts a new chat.
        result = run_turn(store, con, provider, args.chat, args.question)
    finally:
        con.close()

    # Print the answer (or the refusal message), the tools used, the cost and the chat ID.
    print(result.refusal.message if result.refusal else result.answer)
    print("\nTools used:")
    for event in result.tool_events:
        print(f"  {event['name']} {json.dumps(event['args'])}")
    if not result.tool_events:
        print("  none")
    # Cost of this turn = sum of the AI calls saved during it (each AI step has its price).
    cost = 0.0
    if store.exists(result.chat_id):
        new_steps = store.load_steps(result.chat_id)[before:]
        cost = sum(s.cost_usd for s in new_steps if s.cost_usd is not None)
    print(f"Cost of this turn: ${cost:.4f}")
    print(f"Chat ID: {result.chat_id}")


if __name__ == "__main__":
    main()
