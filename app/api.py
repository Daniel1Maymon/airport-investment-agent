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
              tests: test_step16_api.py.
Uses:         app/config.py (Settings), app/db.py (open_airport_db, for /health),
              app/store.py (ChatStore), app/agent/provider.py (OpenRouterProvider),
              app/turn_runner.py (TurnRunner: the lock and the time limit),
              app/presenters.py (build_tables, build_steps, rebuild_turns, refusal_dict).
              FastAPI and Starlette.
Main parts:   create_app(settings, provider=None) -> FastAPI - the app; never raises.
              main_app() - create_app(Settings()), for `uvicorn --factory`.
              TURN_TIMEOUT_SECONDS - the most seconds a request waits for its turn (60).
              MAX_MESSAGE_CHARS - the longest question allowed (1,000 characters).
Design:       docs/api.md; docs/agent.md "Safety"; docs/decisions.md 7.19, 7.22, 7.23;
              docs/implementation-plan.md P80-P91.

How one question works, in short (example: "What % of flights out of Anchorage are long-haul?"):
  1. The page sends {"message": "...", "conversation_id": null} to POST /chat.
  2. Quick checks, in a fixed order, that cost nothing: is the body readable, is the question
     at most 1,000 characters, do we know this chat, is there an AI to ask. A failed check
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

Words used here:
  - CORS: a browser rule. A web page from one site may call our server only if our server
    says that site is allowed. We allow only our own chat page.
"""

import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware

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
    """(conversation_id, message) from the request body, or None if it is not one we accept.

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
    return conversation_id, message


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

    app = FastAPI(title="Airport Investment Intelligence Agent")
    # Only our own chat page may call us from a browser (P87).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.allowed_origin] if settings.allowed_origin else [],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    # Runs each turn: one at a time per chat, with the time limit (P84, P85).
    runner = TurnRunner(store, provider, settings.airports_db)

    def handle_chat(conversation_id, message):
        """The checks of POST /chat in their fixed order, then the turn (P82)."""
        # 2. Question too long (exactly 1,000 characters is allowed).
        if len(message) > MAX_MESSAGE_CHARS:
            return _reply(conversation_id, refusal=refusal_dict("question_too_long"))
        # 3. An ID we don't know.
        if conversation_id is not None and not store.exists(conversation_id):
            return _reply(conversation_id, refusal=refusal_dict("chat_not_found"))
        # 4. No AI to ask (no key or model in the settings).
        if provider is None:
            return _reply(conversation_id, refusal=refusal_dict("ai_unavailable"))
        # 5. A new chat: we make its ID here, so the lock and the time limit know it (P83).
        if conversation_id is None:
            conversation_id = store.new_chat()
        # 6 and 7. The turn, unless the chat is still answering an earlier message.
        # TURN_TIMEOUT_SECONDS is read here, at request time, so tests can lower it (P85).
        status, result = runner.run(conversation_id, message, TURN_TIMEOUT_SECONDS)
        if status == "busy":
            return _reply(conversation_id, refusal=refusal_dict("busy"))
        if status != "done":  # "crash" or "timeout"
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

    @app.post("/chat")
    async def chat(request: Request):
        """Send a question, get the answer (api.md section 1)."""
        conversation_id = None
        try:
            # 1. The body must be one the page sends.
            parsed = _read_body(await request.body())
            if parsed is None:
                return _internal_error(None, status=400)
            conversation_id = parsed[0]
            if store is None:
                return _internal_error(conversation_id)
            # The rest waits on files and threads, so it runs off the main loop.
            return await run_in_threadpool(handle_chat, *parsed)
        except Exception:
            logger.exception("POST /chat failed.")
            return _internal_error(conversation_id)

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

    return app


def main_app():
    """The app with settings from environment variables: `uvicorn --factory app.api:main_app`."""
    return create_app(Settings())
