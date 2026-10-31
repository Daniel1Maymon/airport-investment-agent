"""Runs one chat turn with a time limit, one turn at a time per chat.

What it is:   A small class that keeps one "busy" lock per chat and runs each turn in its
              own thread, waiting at most a given number of seconds for it.
Why we need:  Two safety limits around a turn (docs/api.md "Rules"): a double click must not
              run two turns in the same chat at once, and the page must not wait forever if
              the AI is slow. This is the hardest part of the API, so it lives on its own.
Used by:      app/api.py (POST /chat).
              tests: test_step16_api.py (through the API).
Uses:         app/db.py (open_airport_db), app/agent/loop.py (run_turn).
Main parts:   TurnRunner(store, provider, airports_db) - one per app.
              TurnRunner.run(chat_id, message, timeout) -> (status, TurnResult or None).
Design:       docs/api.md; docs/implementation-plan.md P84, P85, P86.

How one run works, in short (example: two clicks on Send in the same chat):
  1. The first message takes the chat's "busy" lock.
  2. The second message finds the lock taken and gets "busy" at once; nothing runs.
  3. The first message's turn runs in its own thread: open the airport database,
     run_turn, close the database, free the lock.
  4. The request waits for the thread at most `timeout` seconds. After that it stops
     waiting ("timeout"), but the thread goes on, saves its steps and frees the lock.

Words used here:
  - thread: a second line of work running at the same time inside the same program.
  - lock: a "busy" sign. Only one turn at a time can hold a chat's lock.
"""

import logging
import threading

from app.agent.loop import run_turn
from app.db import open_airport_db

# The same log as the API (P86): details of what went wrong go here, never into a reply.
logger = logging.getLogger("app.api")


class TurnRunner:
    """Runs turns: one at a time per chat, each in its own thread, with a time limit."""

    def __init__(self, store, provider, airports_db):
        """store: the chat history. provider: the AI. airports_db: the airport database file."""
        self.store = store
        self.provider = provider
        self.airports_db = airports_db
        # One "busy" lock per chat (P84). Never cleaned up: one small lock per chat is fine
        # for one server.
        self._chat_locks = {}
        self._locks_guard = threading.Lock()  # protects _chat_locks when two requests come at once

    def _lock_for(self, chat_id):
        """The chat's "busy" lock; made the first time the chat is seen."""
        with self._locks_guard:
            return self._chat_locks.setdefault(chat_id, threading.Lock())

    def run(self, chat_id, message, timeout):
        """Run one turn of the chat, waiting at most `timeout` seconds (P84, P85).

        Returns one of:
          ("busy", None)          - the chat is still answering an earlier message;
          ("done", TurnResult)    - the turn finished;
          ("crash", None)         - the turn failed (details in the server log);
          ("timeout", None)       - the turn took too long; it goes on in the background.
        """
        lock = self._lock_for(chat_id)
        if not lock.acquire(blocking=False):  # don't wait: taken means busy
            return "busy", None

        outcome = {}  # the thread writes its result (or "crash") here
        done = threading.Event()  # a flag the thread raises when it has finished

        def work():
            """The turn itself, run inside the thread. It owns the database and the lock."""
            con = None
            try:
                con = open_airport_db(self.airports_db)  # read-only
                outcome["result"] = run_turn(self.store, con, self.provider, chat_id, message)
            except Exception:
                # Full details go to the server log only, never to the reply (P86).
                logger.exception("A chat turn failed.")
                outcome["crash"] = True
            finally:
                try:
                    if con is not None:
                        con.close()
                finally:
                    lock.release()  # freed before "done", so the next message is not busy
                    done.set()

        # daemon=True: a thread still running when the server stops does not keep it alive.
        thread = threading.Thread(target=work, daemon=True)
        try:
            thread.start()
        except Exception:
            lock.release()  # the thread never started, so it can't free the lock itself
            raise
        # Wait for the flag, at most `timeout` seconds. On a timeout the thread goes on and
        # saves its own steps (so the history stays valid); only this request stops waiting.
        if not done.wait(timeout):
            logger.error("A chat turn took longer than %s seconds; it goes on in the background.", timeout)
            return "timeout", None
        if "crash" in outcome:
            return "crash", None
        return "done", outcome["result"]
