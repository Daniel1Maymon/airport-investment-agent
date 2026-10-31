"""The smoke test: checks that a running backend really answers a question.

What it is:   A short check of a running backend (on the laptop or online). It calls the
              three addresses of docs/api.md once each: GET /health, POST /chat with one
              real question, and GET /chat/{id} to reload that chat. It returns a list of
              problems; an empty list means the backend works.
              ("Smoke test" = a quick first check that the whole thing runs at all, like
              switching on a new machine and seeing that no smoke comes out.)
Why we need:  After a deploy, a server can look "up" but still be broken. The most likely
              case: the OpenRouter key is missing, so the server is healthy but refuses
              every question with the ai_unavailable refusal. Checking only the shape of
              the reply would pass on that broken site, so this script also checks that
              the answer is not a refusal and that a tool really ran.
Used by:      a person at the terminal:
                .venv/bin/python -m scripts.smoke_test <backend-url>
              (Step 18: first against http://localhost:8000, then the public Railway address).
              tests: test_step18_deploy.py.
Uses:         httpx (already in requirements.txt). The backend's addresses, docs/api.md.
              Nothing from app/: it talks to the server only over HTTP, as the page does.
Main parts:   DEFAULT_QUESTION - the question it sends (exam question 3, cheap to answer).
              run_checks(base_url, client=None, question=DEFAULT_QUESTION) - run the three
                checks, return each check's name and problems, plus the chat ID.
              run_smoke_test(base_url, client=None, question=DEFAULT_QUESTION) - the same
                checks, as one flat list of problems (empty = pass).
              main(argv=None, client=None) - the command: prints OK/FAIL per check and
                the chat ID; exit code 0 on pass, 1 on any problem.
Design:       docs/implementation-plan.md Step 18; docs/api.md (the three addresses,
              the five reply keys); docs/decisions.md 7.4 (hosting).

How one run works, in short (example: python -m scripts.smoke_test http://localhost:8000):
  1. GET /health. A good server answers 200 {"status": "ok"}.
  2. POST /chat with {"message": "What % of flights out of Anchorage are long-haul?",
     "conversation_id": null}. A good server answers 200 with exactly the five keys
     conversation_id, answer, tables, steps, refusal; refusal is null, the answer is
     some text, and steps has at least one line (so a tool really ran).
  3. GET /chat/<the new chat ID>. A good server answers 200 with refusal null and one
     turn whose question is the one we sent (so the chat was saved).
  4. Every problem found becomes one line of text. A network error (server down, wrong
     address) is also a problem line, never a crash.
"""

import argparse
import sys

import httpx

# The question the smoke test sends: exam question 3. It needs one tool call
# (route_mix for ANC), so it costs about $0.001 of AI per run.
DEFAULT_QUESTION = "What % of flights out of Anchorage are long-haul?"
# How long one request may take, in seconds. A real turn takes about 5-20 seconds and the
# server's own limit is 60 seconds (docs/api.md), so 90 leaves room for a slow network.
TIMEOUT_SECONDS = 90
# The five keys every POST /chat reply has, no more and no less (docs/api.md, P81).
REPLY_KEYS = {"conversation_id", "answer", "tables", "steps", "refusal"}


def _get_json(client, method, url, **kwargs):
    """Send one request and return (status code, parsed JSON body), or (None, problem text).

    Example: _get_json(client, "GET", "http://localhost:8000/health") -> (200, {"status": "ok"}).
    A network error -> (None, "could not reach the server: ...").
    A body that is not JSON -> (status, None), so the caller reports the status it got.
    """
    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError as error:
        # Server down, wrong address, timeout: report it in words instead of crashing.
        return None, f"could not reach the server: {type(error).__name__}: {error}"
    try:
        body = response.json()
    except ValueError:
        body = None
    return response.status_code, body


def _refusal_text(refusal):
    """Describe a refusal in one line, naming its cause.

    Example: {"cause": "ai_unavailable", "message": "The AI is not available ..."}
    -> "ai_unavailable (The AI is not available ...)".
    """
    if isinstance(refusal, dict):
        return f"{refusal.get('cause')} ({refusal.get('message')})"
    return repr(refusal)


def _check_health(client, base_url):
    """Check 1: GET /health answers 200 {"status": "ok"}. Returns a list of problems."""
    status, body = _get_json(client, "GET", f"{base_url}/health")
    if status is None:
        return [f"GET /health: {body}"]
    if status != 200 or body != {"status": "ok"}:
        return [f"GET /health: expected 200 {{'status': 'ok'}}, got {status} {body!r}"]
    return []


def _check_chat(client, base_url, question):
    """Check 2: POST /chat answers the question. Returns (problems, chat ID or None)."""
    status, body = _get_json(
        client, "POST", f"{base_url}/chat", json={"message": question, "conversation_id": None}
    )
    if status is None:
        return [f"POST /chat: {body}"], None
    if not isinstance(body, dict):
        return [f"POST /chat: expected a JSON object, got status {status} and {body!r}"], None

    problems = []
    if status != 200:
        problems.append(f"POST /chat: expected status 200, got {status}")
    # The refusal is checked early and named clearly: it is the most likely problem
    # on a new deploy (no OpenRouter key -> every question is refused with ai_unavailable).
    refusal = body.get("refusal")
    if refusal is not None:
        problems.append(f"POST /chat: the server refused the question: {_refusal_text(refusal)}")
    keys = set(body)
    if keys != REPLY_KEYS:
        missing = sorted(REPLY_KEYS - keys)
        extra = sorted(keys - REPLY_KEYS)
        problems.append(f"POST /chat: reply keys are wrong (missing {missing}, extra {extra})")

    answer = body.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        problems.append(f"POST /chat: the answer is empty or not text: {answer!r}")
    chat_id = body.get("conversation_id")
    if not isinstance(chat_id, str) or not chat_id.strip():
        problems.append(f"POST /chat: conversation_id is empty or not text: {chat_id!r}")
        chat_id = None
    if not isinstance(body.get("tables"), list):
        problems.append(f"POST /chat: tables is not a list: {body.get('tables')!r}")
    steps = body.get("steps")
    if not isinstance(steps, list):
        problems.append(f"POST /chat: steps is not a list: {steps!r}")
    elif not steps:
        # No step means no tool ran, so the answer is not based on our data.
        problems.append("POST /chat: steps is empty, so no tool ran")
    return problems, chat_id


def _check_reload(client, base_url, chat_id, question):
    """Check 3: GET /chat/{id} gives back the saved chat with our one question.

    Returns a list of problems. Without a chat ID (check 2 failed) it can't run,
    which is reported as a problem too.
    """
    if chat_id is None:
        return ["GET /chat/{id}: skipped, POST /chat gave no chat ID"]
    status, body = _get_json(client, "GET", f"{base_url}/chat/{chat_id}")
    if status is None:
        return [f"GET /chat/{chat_id}: {body}"]
    if status != 200 or not isinstance(body, dict):
        return [f"GET /chat/{chat_id}: expected 200 and a JSON object, got {status} {body!r}"]

    problems = []
    if body.get("refusal") is not None:
        problems.append(f"GET /chat/{chat_id}: refused: {_refusal_text(body.get('refusal'))}")
    turns = body.get("turns")
    if not isinstance(turns, list) or len(turns) != 1:
        count = len(turns) if isinstance(turns, list) else repr(turns)
        problems.append(f"GET /chat/{chat_id}: expected 1 saved turn, got {count}")
    elif not isinstance(turns[0], dict) or turns[0].get("question") != question:
        got = turns[0].get("question") if isinstance(turns[0], dict) else turns[0]
        problems.append(f"GET /chat/{chat_id}: the saved question is {got!r}, not {question!r}")
    return problems


def run_checks(base_url, client=None, question=DEFAULT_QUESTION):
    """Run the three checks in order. Returns ([(check name, problems), ...], chat ID or None).

    Example on a good server:
    ([("GET /health", []), ("POST /chat", []), ("GET /chat/{id}", [])], "c7f3a9e2-...").
    client=None -> a real httpx.Client with a 90-second timeout, closed at the end.
    """
    # "http://host:8000/" and "http://host:8000" must give the same addresses.
    base_url = base_url.rstrip("/")
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=TIMEOUT_SECONDS)
    try:
        # All three checks always run (check 3 reports itself as skipped when it can't),
        # so one run shows every problem at once.
        results = [("GET /health", _check_health(client, base_url))]
        chat_problems, chat_id = _check_chat(client, base_url, question)
        results.append(("POST /chat", chat_problems))
        results.append(("GET /chat/{id}", _check_reload(client, base_url, chat_id, question)))
    finally:
        if own_client:
            client.close()
    return results, chat_id


def run_smoke_test(base_url, client=None, question=DEFAULT_QUESTION):
    """Run the smoke test. Returns the list of problems found; empty means it passed.

    Example: run_smoke_test("http://localhost:8000") -> [] on a working server, or
    ["POST /chat: the server refused the question: ai_unavailable (...)", ...].
    """
    results, _chat_id = run_checks(base_url, client=client, question=question)
    return [problem for _name, problems in results for problem in problems]


def main(argv=None, client=None):
    """The command: run the smoke test on one backend address and print the result.

    Prints one OK/FAIL line per check (with its problems below it) and the chat ID.
    Returns the exit code: 0 when every check passed, 1 when any problem was found.
    """
    parser = argparse.ArgumentParser(description="Check that a running backend answers a question.")
    parser.add_argument("base_url", help="the backend address, e.g. http://localhost:8000")
    args = parser.parse_args(argv)

    results, chat_id = run_checks(args.base_url, client=client)
    for name, problems in results:
        print(f"{'OK  ' if not problems else 'FAIL'} {name}")
        for problem in problems:
            print(f"     - {problem}")
    print(f"Chat ID: {chat_id}")
    failed = any(problems for _name, problems in results)
    print("Smoke test FAILED" if failed else "Smoke test passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
