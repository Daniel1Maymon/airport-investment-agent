"""The four admin addresses of the dashboard, behind the admin token.

What it is:   `admin_router(settings, admin_store)`: a FastAPI router with GET /admin/metrics,
              GET /admin/events, GET /admin/ai and POST /admin/ai, and one token check that
              runs before each of them.
Why we need:  The admin page in the browser can't read chat.sqlite itself. These addresses
              give it the numbers, the recent questions and the AI switch, but only to the
              owner, who holds the token (a long random password set on Railway).
Used by:      app/api.py (create_app includes the router).
              tests: test_step19_admin.py.
Uses:         app/config.py (Settings.admin_token), app/admin_store.py (AdminStore).
              FastAPI, Starlette; standard library secrets, json, re.
Main parts:   admin_router(settings, admin_store) -> APIRouter - the four addresses.
              MAX_NOTE_CHARS - the longest note allowed on the switch (200 characters).
              MIN_LIMIT, MAX_LIMIT, DEFAULT_LIMIT - the allowed sizes of the recent list.
Design:       docs/api.md section 4; docs/admin-dashboard.md "Who can open it";
              docs/implementation-plan.md P124, P131, P132, P135.

How one admin request works, in short (example: the owner presses Refresh on the dashboard):
  1. The page sends GET /admin/metrics with the header "Authorization: Bearer <token>".
  2. The token check runs first, for every address (it is set once on the router, so a new
     address can't be added without it). No ADMIN_TOKEN setting, no header or a wrong one →
     401 {"detail": "unauthorized"} and nothing else.
  3. The address reads its settings itself (the limit, or the switch body) and gives
     400 {"detail": "bad request"} for anything it does not accept.
  4. AdminStore works out the numbers from chat.sqlite, and the reply is plain JSON.

Words used here:
  - Token: a long random password. The page sends it in the Authorization header.
  - Constant-time compare (secrets.compare_digest): takes the same time whether the first
    or the last character is wrong, so nobody can guess the token one character at a time
    by timing the replies.
"""

import json
import logging
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.admin_store import SORT_KEYS, SORT_ORDERS

# Errors are written here (the server log), never into a reply.
logger = logging.getLogger("app.admin")

# The longest note the owner may save with the switch (P131).
MAX_NOTE_CHARS = 200
# The smallest, largest and default number of recent questions GET /admin/events gives
# (api.md section 4). 500 keeps one reply small enough for a phone.
MIN_LIMIT = 1
MAX_LIMIT = 500
DEFAULT_LIMIT = 100
MAX_OFFSET = 1_000_000  # far more questions than the site will ever have; a larger offset is a bad request
# A limit must be plain digits: "-1", "1.5" and "abc" are refused.
_DIGITS = re.compile(r"[0-9]+")


def _bad_request():
    """The one reply for a request the page never sends (P131)."""
    return JSONResponse({"detail": "bad request"}, status_code=400)


def _server_error():
    """The reply when the admin data can't be read; details go to the server log only."""
    return JSONResponse({"detail": "internal error"}, status_code=500)


def _read_switch_body(raw):
    """(enabled, note) from the POST /admin/ai body, or None if it is not one we accept.

    Accepted: {"enabled": true or false} with an optional "note" (text, at most 200
    characters, or null). Example: {"enabled": false, "note": "cost check"} → (False, "cost check").
    """
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or set(body) - {"enabled", "note"}:
        return None
    enabled = body.get("enabled")
    note = body.get("note")
    # Must be JSON true/false exactly: 0, "no" or null are refused.
    if not isinstance(enabled, bool):
        return None
    if note is not None and (not isinstance(note, str) or len(note) > MAX_NOTE_CHARS):
        return None
    return enabled, note


def admin_router(settings, admin_store):
    """The four admin addresses, with the token check set once for all of them (P124).

    settings: holds admin_token (None or "" means every admin request is refused).
    admin_store: the AdminStore that reads chat.sqlite.
    """

    def check_token(request: Request):
        """Let the request through only with "Authorization: Bearer <ADMIN_TOKEN>"; else 401."""
        token = settings.admin_token
        sent = request.headers.get("authorization", "")
        # Fails closed: a forgotten or empty setting locks the dashboard. Compared as bytes,
        # in constant time, so an odd character in the header can't crash the check.
        if not token or not secrets.compare_digest(sent.encode("utf-8"), f"Bearer {token}".encode("utf-8")):
            raise HTTPException(status_code=401, detail="unauthorized")

    router = APIRouter(prefix="/admin", dependencies=[Depends(check_token)])

    @router.get("/metrics")
    def metrics():
        """The dashboard numbers (api.md section 4)."""
        try:
            return JSONResponse(admin_store.metrics())
        except Exception:
            logger.exception("GET /admin/metrics failed.")
            return _server_error()

    @router.get("/events")
    def events(request: Request):
        """The most recent questions, newest first, one page at a time.

        ?limit=1..500 (100 when not given) and ?offset=0.. (0 when not given): skip `offset`
        questions, then return up to `limit`. "total" is how many questions there are, so the
        page can show "page 2 of 5".
        """
        # Read by hand (not with FastAPI's checks) so a bad value gets our short 400 reply.
        text = request.query_params.get("limit", str(DEFAULT_LIMIT))
        offset_text = request.query_params.get("offset", "0")
        if not _DIGITS.fullmatch(text) or not MIN_LIMIT <= int(text) <= MAX_LIMIT:
            return _bad_request()
        if not _DIGITS.fullmatch(offset_text) or int(offset_text) > MAX_OFFSET:
            return _bad_request()
        # ?sort=<column>&order=asc|desc; newest first when not given.
        sort = request.query_params.get("sort", "time")
        order = request.query_params.get("order", "desc")
        if sort not in SORT_KEYS or order not in SORT_ORDERS:
            return _bad_request()
        try:
            return JSONResponse(
                {
                    "events": admin_store.recent_questions(int(text), int(offset_text), sort, order),
                    "total": admin_store.question_count(),
                }
            )
        except Exception:
            logger.exception("GET /admin/events failed.")
            return _server_error()

    @router.get("/ai")
    def get_ai():
        """The AI switch: {"enabled", "updated_at", "note"}."""
        try:
            return JSONResponse(admin_store.ai_state())
        except Exception:
            logger.exception("GET /admin/ai failed.")
            return _server_error()

    @router.post("/ai")
    async def set_ai(request: Request):
        """Save the wanted state of the AI switch (not a flip) and return it (P131)."""
        parsed = _read_switch_body(await request.body())
        if parsed is None:
            return _bad_request()
        enabled, note = parsed
        try:
            # A file write, so it runs off the main loop.
            return JSONResponse(await run_in_threadpool(admin_store.set_ai_enabled, enabled, note))
        except Exception:
            logger.exception("POST /admin/ai failed.")
            return _server_error()

    return router
