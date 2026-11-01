"""The backend API: the three web addresses the chat page talks to.

What it is:   A FastAPI web app with POST /chat (send a question, get the answer, tables,
              steps and refusal), GET /chat/{conversation_id} (reload a whole chat) and
              GET /health (is the server up and does the airport database open).
Why we need:  The chat page in the browser can't run Python. It sends the question over the
              web; this file checks it, runs one agent turn, and sends back a reply the page
              can show as it is. It also holds the safety limits around a turn: question
              length, one message at a time per chat, 60 seconds per turn, which web page may
              call us (CORS), and error replies that never show technical details.
Used by:      a person or Railway starting the server:
                uvicorn --factory app.api:main_app
              Dockerfile (the start command of the online container, Step 18).
              scripts/smoke_test.py (over HTTP only).
              tests: test_step16_api.py, test_step19_admin.py.
Uses:         app/config.py (Settings), app/db.py (open_airport_db, for /health),
              app/store.py (ChatStore), app/agent/provider.py (OpenRouterProvider),
              app/turn_runner.py (TurnRunner: the lock and the time limit),
              app/presenters.py (build_tables, build_steps, rebuild_turns, refusal_dict).
              app/admin_store.py (AdminStore: the log row and the AI switch, Step 19),
              app/admin.py (admin_router: the four admin addresses, Step 19).
              FastAPI and Starlette.
Main parts:   create_app(settings, provider=None) -> FastAPI - the app; never raises.
              main_app() - create_app(Settings()), for `uvicorn --factory`.
              TURN_TIMEOUT_SECONDS - the most seconds a request waits for its turn (60).
              MAX_MESSAGE_CHARS - the longest question allowed (1,000 characters).
Design:       docs/api.md; docs/agent.md "Safety"; docs/decisions.md 7.19, 7.22, 7.23;
              docs/implementation-plan.md P80-P91. Step 19 (decisions 7.26, 7.27) changes
              only three things here: the CORS header (P125), the AI switch in check 4
              (P130), and one log row per POST /chat reply (P127-P129).

How one question works, in short (example: "What % of flights out of Anchorage are long-haul?"):
  1. The page sends {"message": "...", "conversation_id": null} to POST /chat.
  2. Quick checks, in a fixed order, that cost nothing: is the body readable, is the question
     at most 1,000 characters, do we know this chat, is there an AI to ask (and has the owner
     not switched it off on the admin dashboard). A failed check
     gives a fixed refusal message at once; nothing is saved and the AI is not called.
  3. A new chat gets its ID here. The chat's "busy" sign is taken (one message at a time).
  4. The turn runs in its own thread (turn_runner.py): open the airport database, run_turn
     (the AI picks tools, Python runs them, the AI writes the answer), close the database,
     free the sign.
  5. The request waits at most 60 seconds for that thread.
  6. The reply: the answer, plus tables and "How I got this" steps that Python builds
     straight from the tool results (presenters.py), so the AI can't change their numbers.
  If anything breaks, the reply is the fixed "internal error" message; the details go only
  to the server log.
  7. One log row is saved for the reply (answered / refused / error, the cause, how long it
     took; never the question text), for the admin dashboard. If saving it fails, the
     reply goes out exactly the same.

Words used here:
  - CORS: a browser rule. A web page from one site may call our server only if our server
    says that site is allowed. We allow only our own chat page.
"""

import json
import logging
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

from app.admin import admin_router
from app.admin_store import AdminStore
from app.agent.provider import OpenRouterProvider
from app.config import Settings
from app.db import open_airport_db
from app.presenters import build_steps, build_tables, rebuild_turns, refusal_dict
from app.store import ChatStore
from app.turn_runner import TurnRunner

# Errors are written here (the server log), never into a reply.
logger = logging.getLogger("app.api")

# The longest a request waits for its turn. Read when each request runs (not copied at
# start-up), so tests can lower it (P85).
TURN_TIMEOUT_SECONDS = 60
# The longest question allowed. Longer ones are refused before the AI sees them, so a huge
# pasted text can't cost us money.
MAX_MESSAGE_CHARS = 1_000


def _reply(conversation_id, answer="", tables=None, steps=None, refusal=None, status=200):
    """The five-key reply of POST /chat (P81)."""
    body = {
        "conversation_id": conversation_id,
        "answer": answer,
        "tables": tables or [],
        "steps": steps or [],
        "refusal": refusal,
    }
    return JSONResponse(body, status_code=status)


def _internal_error(conversation_id, status=500):
    """The "something went wrong" reply. Never holds any detail of what went wrong (P86)."""
    return _reply(conversation_id, refusal=refusal_dict("internal_error"), status=status)


def _read_body(raw):
    """(conversation_id, message, language) from the request body, or None if it is not one we accept.

    language is optional: "en" (the default) or "he" for the Hebrew page (P106).

    We check the body ourselves (not with FastAPI's model checks) so a bad body gets our
    own short reply, never FastAPI's detailed error text (P81).
    """
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    message = body.get("message")
    conversation_id = body.get("conversation_id")
    if not isinstance(message, str) or not message.strip():
        return None
    if conversation_id is not None and not isinstance(conversation_id, str):
        return None
    language = body.get("language", "en")
    if language not in ("en", "he"):
        return None
    return conversation_id, message, language


# A visitor ID is the random ID the chat page keeps per browser (crypto.randomUUID()).
# Only letters, digits and "-", 8-64 characters; anything else is saved as empty.
_VISITOR_ID = re.compile(r"[A-Za-z0-9-]{8,64}")


def _visitor_id(raw):
    """The visitor ID from the request body, or None when it is missing or odd. Never raises.

    It is only for the admin numbers, so a bad value never refuses the question.
    """
    try:
        value = json.loads(raw).get("visitor_id")
    except Exception:
        return None
    if isinstance(value, str) and _VISITOR_ID.fullmatch(value):
        return value
    return None


def create_app(settings, provider=None):
    """Build the web app. Never raises, so the server always starts and can say what is wrong (P80).

    settings: where the two databases are, the AI key and model, the allowed web page.
    provider: who answers as the AI; None = OpenRouter with the key and model from settings.
    """
    if provider is None:
        try:
            provider = OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model)
        except ValueError:  # no key or no model: start anyway; questions get ai_unavailable
            provider = None

    # The chat history file. If it can't be made now, every request gets an internal error.
    try:
        store = ChatStore(settings.chat_db)
    except Exception:
        logger.exception("Could not open the chat database.")
        store = None

    # The admin tables: the log rows and the AI switch (Step 19). If they can't be made, the
    # chat still works, only without logging and without the switch (P129).
    try:
        admin_store = AdminStore(settings.chat_db)
    except Exception:
        logger.exception("Could not open the admin tables.")
        admin_store = None

    app = FastAPI(title="Airport Investment Intelligence Agent")
    # Only our own chat page may call us from a browser (P87). Authorization is allowed for
    # the admin page, which sends its token in that header (P125).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.allowed_origin] if settings.allowed_origin else [],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=False,
    )

    # Runs each turn: one at a time per chat, with the time limit (P84, P85).
    runner = TurnRunner(store, provider, settings.airports_db)

    def ai_switch_on():
        """Is the owner's AI switch on? A switch that can't be read counts as ON (P130)."""
        if admin_store is None:
            return True
        try:
            return admin_store.ai_enabled()
        except Exception:
            # A dashboard problem must never stop the chat; the details go to the server log.
            logger.exception("Could not read the AI switch; counting it as on.")
            return True

    def handle_chat(conversation_id, message, language="en", error_cause=None):
        """The checks of POST /chat in their fixed order, then the turn (P82).

        error_cause: a dict; on an internal error its "cause" is set to "timeout" or
        "crash", for the log row (P127).
        """
        # 2. Question too long (exactly 1,000 characters is allowed).
        if len(message) > MAX_MESSAGE_CHARS:
            return _reply(conversation_id, refusal=refusal_dict("question_too_long"))
        # 3. An ID we don't know.
        if conversation_id is not None and not store.exists(conversation_id):
            return _reply(conversation_id, refusal=refusal_dict("chat_not_found"))
        # 4. No AI to ask (no key or model in the settings), or the owner switched it off (P130).
        if provider is None or not ai_switch_on():
            return _reply(conversation_id, refusal=refusal_dict("ai_unavailable"))
        # 5. A new chat: we make its ID here, so the lock and the time limit know it (P83).
        if conversation_id is None:
            conversation_id = store.new_chat()
        # 6 and 7. The turn, unless the chat is still answering an earlier message.
        # TURN_TIMEOUT_SECONDS is read here, at request time, so tests can lower it (P85).
        status, result = runner.run(conversation_id, message, TURN_TIMEOUT_SECONDS, language)
        if status == "busy":
            return _reply(conversation_id, refusal=refusal_dict("busy"))
        if status != "done":  # "crash" or "timeout"
            if error_cause is not None:
                error_cause["cause"] = status
            return _internal_error(conversation_id)
        # Tables and steps come straight from the tool results, also for a refusal (P81).
        return _reply(
            result.chat_id,
            answer=result.answer,
            tables=build_tables(result.tool_events),
            steps=build_steps(result.tool_events),
            refusal=result.refusal._asdict() if result.refusal else None,
        )

    # ---------------------------------------------------------------- the three addresses

    def log_reply(response, language, error_cause, started, visitor_id=None):
        """Save one log row for this POST /chat reply (P127-P129). Never raises.

        Example (made up): a refusal for an unknown airport → ("c7f3…", "refused",
        "airport_not_found", 6100, "en"). The question text is never logged.
        """
        if admin_store is None:
            return
        try:
            body = json.loads(response.body)
            if response.status_code == 400:  # a body the page never sends
                outcome, cause = "error", "bad_request"
            elif response.status_code >= 500:  # the time limit, or a crash
                outcome, cause = "error", error_cause.get("cause", "crash")
            elif body["refusal"]:
                outcome, cause = "refused", body["refusal"]["cause"]
            else:
                outcome, cause = "answered", None
            # Whole milliseconds from the request arriving, on a steady clock (P128).
            duration_ms = round((time.monotonic() - started) * 1000)
            admin_store.log_event(body["conversation_id"], outcome, cause, duration_ms, language, visitor_id)
        except Exception:
            # A dashboard problem must never cost a user their answer (P129).
            logger.exception("Could not save the log row of POST /chat.")

    @app.post("/chat")
    async def chat(request: Request):
        """Send a question, get the answer (api.md section 1), then save one log row."""
        started = time.monotonic()  # when the request arrived (P128)
        error_cause = {}  # handle_chat writes "timeout" or "crash" here
        response, language = await answer_chat(request, error_cause)
        try:
            visitor_id = _visitor_id(await request.body())  # the body is cached, so this reads it again for free
        except Exception:
            visitor_id = None
        # The log row is a file write, so it runs off the main loop.
        await run_in_threadpool(log_reply, response, language, error_cause, started, visitor_id)
        return response

    async def answer_chat(request, error_cause):
        """(the reply of POST /chat, the language asked for); the language is None when the body can't be read."""
        conversation_id = None
        language = None
        try:
            # 1. The body must be one the page sends.
            parsed = _read_body(await request.body())
            if parsed is None:
                return _internal_error(None, status=400), None
            conversation_id, _message, language = parsed
            if store is None:
                return _internal_error(conversation_id), language
            # The rest waits on files and threads, so it runs off the main loop.
            return await run_in_threadpool(handle_chat, *parsed, error_cause), language
        except Exception:
            logger.exception("POST /chat failed.")
            return _internal_error(conversation_id), language

    @app.get("/chat/{conversation_id}")
    def reload_chat(conversation_id: str):
        """Reload a whole chat after the page is refreshed (api.md section 2)."""
        try:
            if store is None:
                raise RuntimeError("no chat database")
            if not store.exists(conversation_id):
                body = {"conversation_id": conversation_id, "turns": [], "refusal": refusal_dict("chat_not_found")}
                return JSONResponse(body)
            turns = rebuild_turns(store.load_steps(conversation_id))
            return JSONResponse({"conversation_id": conversation_id, "turns": turns, "refusal": None})
        except Exception:
            logger.exception("GET /chat failed.")
            body = {"conversation_id": conversation_id, "turns": [], "refusal": refusal_dict("internal_error")}
            return JSONResponse(body, status_code=500)

    @app.get("/health")
    def health():
        """Is the server up and does the airport database open? Railway calls this (api.md section 3)."""
        # Open the airport database, ask it the simplest question, close it (P80).
        try:
            con = open_airport_db(settings.airports_db)
            try:
                con.execute("SELECT 1").fetchone()
            finally:
                con.close()
        except Exception:
            logger.exception("Health check failed.")
            return JSONResponse({"status": "error"}, status_code=503)
        return JSONResponse({"status": "ok"})

    # ---------------------------------------------------------------- the admin addresses
    # The four /admin addresses, each behind the admin token (app/admin.py, Step 19).
    app.include_router(admin_router(settings, admin_store))

    return app


def main_app():
    """The app with settings from environment variables: `uvicorn --factory app.api:main_app`."""
    return create_app(Settings())
