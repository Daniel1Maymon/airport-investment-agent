"""Tests for Step 18: put it online (smoke test script, Dockerfile, railway.json, deploy script, settings)."""

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import httpx
import pytest

from scripts.smoke_test import DEFAULT_QUESTION, main, run_smoke_test

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://backend.test"
CHAT_ID = "chat-123"
# The files the backend needs online, and nothing else (Step 18, approved 2026-10-31).
UPLOAD_FILES = {"Dockerfile", "railway.json", "requirements.txt", "app", "airports.duckdb"}
# What the container itself needs (the Dockerfile and railway.json are only build instructions).
CONTAINER_FILES = {"requirements.txt", "app", "airports.duckdb"}
# Things that must never leave the laptop: secrets, notes, raw downloads, chats, the exam.
NEVER_UPLOAD = [".env", "CLAUDE.md", "data/", ".venv", ".sqlite", "FDE EXAM"]


# ---------------------------------------------------------------- fake backend for the smoke test

def make_server(health=None, chat=None, reload=None, seen=None):
    """A fake backend (httpx.MockTransport) that answers like a good server.

    health / chat / reload: replace one answer with (status, JSON body).
    seen: a list that gets every request, so a test can look at what was sent.
    The good POST /chat reply echoes the question it got, and the good reload
    gives back that same question, as the real server does.
    """
    state = {"question": None}

    def handler(request):
        if seen is not None:
            seen.append(request)
        if request.method == "GET" and request.url.path == "/health":
            status, body = health or (200, {"status": "ok"})
            return httpx.Response(status, json=body)
        if request.method == "POST" and request.url.path == "/chat":
            state["question"] = json.loads(request.content)["message"]
            status, body = chat or (200, {
                "conversation_id": CHAT_ID,
                "answer": "About 12.3% of passenger departures from ANC are long-haul.",  # made up
                "tables": [],
                "steps": ["Split departures into groups (airport: ANC)"],
                "refusal": None,
            })
            return httpx.Response(status, json=body)
        if request.method == "GET" and request.url.path == f"/chat/{CHAT_ID}":
            status, body = reload or (200, {
                "conversation_id": CHAT_ID,
                "turns": [{"question": state["question"], "answer": "About 12.3% ...",
                           "tables": [], "steps": ["Split departures into groups (airport: ANC)"],
                           "refusal": None}],
                "refusal": None,
            })
            return httpx.Response(status, json=body)
        return httpx.Response(404, json={"detail": "Not Found"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_smoke_passes_on_good_server():
    assert run_smoke_test(BASE, client=make_server()) == []


def test_smoke_sends_one_new_chat_question():
    """POST /chat gets {"message": the question, "conversation_id": null}; the reload uses the new ID."""
    seen = []
    assert run_smoke_test(BASE + "/", client=make_server(seen=seen)) == []  # trailing / is removed
    posts = [r for r in seen if r.method == "POST"]
    assert len(posts) == 1
    assert str(posts[0].url) == f"{BASE}/chat"
    assert json.loads(posts[0].content) == {"message": DEFAULT_QUESTION, "conversation_id": None}
    assert [str(r.url) for r in seen if r.method == "GET"] == [f"{BASE}/health", f"{BASE}/chat/{CHAT_ID}"]


def test_smoke_default_question_is_exam_question_3():
    assert DEFAULT_QUESTION == "What % of flights out of Anchorage are long-haul?"


def test_smoke_fails_when_health_down():
    problems = run_smoke_test(BASE, client=make_server(health=(503, {"status": "error"})))
    assert problems
    assert any("/health" in p for p in problems)


def test_smoke_fails_on_refusal():
    """A healthy server with no OpenRouter key refuses every question: that must fail, naming the cause."""
    refused = {"conversation_id": None, "answer": "", "tables": [], "steps": [],
               "refusal": {"cause": "ai_unavailable", "message": "The AI is not available right now."}}
    problems = run_smoke_test(BASE, client=make_server(chat=(200, refused)))
    assert problems
    assert any("ai_unavailable" in p for p in problems)


def test_smoke_fails_on_missing_key():
    reply = {"conversation_id": CHAT_ID, "answer": "Some answer.", "tables": [], "refusal": None}
    problems = run_smoke_test(BASE, client=make_server(chat=(200, reply)))
    assert any("steps" in p for p in problems)


def test_smoke_fails_on_extra_key():
    reply = {"conversation_id": CHAT_ID, "answer": "Some answer.", "tables": [],
             "steps": ["Split departures into groups (airport: ANC)"], "refusal": None, "debug": "x"}
    problems = run_smoke_test(BASE, client=make_server(chat=(200, reply)))
    assert any("debug" in p for p in problems)


def test_smoke_fails_when_no_tool_ran():
    reply = {"conversation_id": CHAT_ID, "answer": "Some answer.", "tables": [], "steps": [], "refusal": None}
    problems = run_smoke_test(BASE, client=make_server(chat=(200, reply)))
    assert any("steps" in p for p in problems)


def test_smoke_fails_on_empty_answer():
    reply = {"conversation_id": CHAT_ID, "answer": "  ", "tables": [],
             "steps": ["Split departures into groups (airport: ANC)"], "refusal": None}
    assert run_smoke_test(BASE, client=make_server(chat=(200, reply)))


def test_smoke_fails_on_chat_500():
    reply = {"conversation_id": None, "answer": "", "tables": [], "steps": [],
             "refusal": {"cause": "internal_error", "message": "Something went wrong."}}
    problems = run_smoke_test(BASE, client=make_server(chat=(500, reply)))
    assert any("internal_error" in p for p in problems)


def test_smoke_fails_when_reload_has_no_turn():
    reload = {"conversation_id": CHAT_ID, "turns": [], "refusal": None}
    problems = run_smoke_test(BASE, client=make_server(reload=(200, reload)))
    assert problems
    assert any(f"/chat/{CHAT_ID}" in p for p in problems)


def test_smoke_fails_when_reload_has_other_question():
    reload = {"conversation_id": CHAT_ID, "refusal": None,
              "turns": [{"question": "Another question", "answer": "x", "tables": [], "steps": [], "refusal": None}]}
    assert run_smoke_test(BASE, client=make_server(reload=(200, reload)))


def test_smoke_network_error_is_a_problem_not_a_crash():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    problems = run_smoke_test(BASE, client=client)  # must not raise
    assert problems
    assert all(isinstance(p, str) for p in problems)


def test_smoke_command_exit_codes(capsys):
    assert main([BASE], client=make_server()) == 0
    out = capsys.readouterr().out
    assert "OK" in out and CHAT_ID in out
    assert main([BASE], client=make_server(health=(503, {"status": "error"}))) == 1
    assert "FAIL" in capsys.readouterr().out


# ---------------------------------------------------------------- deploy files (read at run time)

def read_text(relative):
    """The text of a project file; the test fails with a clear message when it is missing."""
    path = ROOT / relative
    assert path.exists(), f"{relative} is missing"
    return path.read_text()


def dockerfile_instructions():
    """The Dockerfile as a list of (INSTRUCTION, rest of line): comments dropped, '\\' lines joined."""
    joined = re.sub(r"\\\n", " ", read_text("Dockerfile"))
    result = []
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        word, _, rest = line.partition(" ")
        result.append((word.upper(), rest.strip()))
    return result


def copy_sources(rest):
    """The source paths of one COPY line ('--flag' options and the last item, the target, left out).

    Example: 'app/ ./app/' -> ['app/'];  '["requirements.txt", "."]' -> ['requirements.txt'].
    """
    rest = rest.strip()
    items = json.loads(rest) if rest.startswith("[") else shlex.split(rest)
    items = [item for item in items if not item.startswith("--")]
    return items[:-1]


def test_dockerfile_copies_only_needed_files():
    instructions = dockerfile_instructions()
    froms = [rest for word, rest in instructions if word == "FROM"]
    assert froms == ["python:3.12-slim"]

    sources = [src for word, rest in instructions if word in ("COPY", "ADD") for src in copy_sources(rest)]
    # "app/" and "./app" both mean the app folder.
    names = {src.strip("/").removeprefix("./").strip("/") for src in sources}
    assert names == CONTAINER_FILES, f"COPY sources: {sources}"
    for bad in (".", "", "*", ".env", "data", "CLAUDE.md"):
        assert bad not in names
    assert not [word for word, _ in instructions if word == "ADD"], "use COPY, not ADD"

    runs = " ".join(rest for word, rest in instructions if word == "RUN")
    assert "pip install" in runs and "-r requirements.txt" in runs


def test_dockerfile_settings_and_start():
    instructions = dockerfile_instructions()
    env = {}
    for word, rest in instructions:
        if word != "ENV":
            continue
        parts = shlex.split(rest)
        if "=" in parts[0]:
            env.update(part.split("=", 1) for part in parts)
        else:  # the old form: ENV KEY value
            env[parts[0]] = " ".join(parts[1:])

    airports_db = env.get("AIRPORTS_DB", "")
    # The disk is mounted at /data and hides what the image has there, so the DB must live elsewhere.
    assert airports_db.startswith("/") and airports_db.endswith(".duckdb")
    assert not (airports_db == "/data" or airports_db.startswith("/data/"))
    assert env.get("CHAT_DB") == "/data/chat.sqlite"

    starts = [rest for word, rest in instructions if word in ("CMD", "ENTRYPOINT")]
    assert len(starts) == 1, f"start commands: {starts}"
    start = starts[0]
    assert "uvicorn" in start
    assert "--factory app.api:main_app" in start
    assert "--host 0.0.0.0" in start
    assert "$PORT" in start or "${PORT" in start
    # Exec form (["..."]) does not expand $PORT unless it runs a shell.
    assert not start.startswith("[") or "sh" in start


def test_railway_json_health_check():
    config = json.loads(read_text("railway.json"))
    assert config["build"]["builder"].upper() == "DOCKERFILE"
    assert config["deploy"]["healthcheckPath"] == "/health"


def script_code_lines():
    """The deploy script's lines without comments (comments may explain what is never uploaded)."""
    lines = []
    for line in read_text("scripts/deploy_backend.sh").splitlines():
        code = line.strip()
        if code and not code.startswith("#"):
            lines.append(code)
    return lines


def test_deploy_script_uploads_only_listed_files():
    code = "\n".join(script_code_lines())
    assert "railway up" in code
    assert "--path-as-root" in code
    assert "mktemp" in code, "the files are copied into a fresh temporary folder"
    for name in UPLOAD_FILES:
        assert re.search(rf"(?<![\w.]){re.escape(name)}(?![\w.])", code), f"{name} is not copied"
    for bad in NEVER_UPLOAD:
        assert bad not in code, f"the script mentions {bad}"
    # Never upload the whole project folder.
    assert not re.search(r"railway up\s+(\.|\./)?(\s|$)", code)
    assert not re.search(r"\bcp\s+(-\w+\s+)*\.(/)?\s", code)


def test_deploy_script_run_uploads_exactly_listed_files(tmp_path):
    """Run the real script in a fake project with a fake `railway` command; check the uploaded folder.

    The fake project also has every file that must stay on the laptop; none may arrive.
    """
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    (project / "scripts" / "deploy_backend.sh").write_text(read_text("scripts/deploy_backend.sh"))
    for name in ("Dockerfile", "railway.json", "requirements.txt", "airports.duckdb",
                 ".env", "CLAUDE.md", "chat.sqlite", "FDE EXAM.pdf", "README.md"):
        (project / name).write_text("x")
    (project / "app").mkdir()
    (project / "app" / "api.py").write_text("x")
    for folder in ("data/raw", ".venv/bin", "tests", "web"):
        (project / folder).mkdir(parents=True)
        (project / folder / "f.txt").write_text("x")

    # A fake `railway`: on "railway up <folder> ...", writes the folder's file list to RECORD.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "uploaded.txt"
    fake = bin_dir / "railway"
    fake.write_text(
        '#!/bin/bash\n'
        'if [ "$1" = "up" ]; then\n'
        '  for a in "$@"; do\n'
        '    if [ -d "$a" ]; then (cd "$a" && find . -mindepth 1 | sort) > "$RECORD"; fi\n'
        '  done\n'
        '  echo "$@" > "$RECORD.args"\n'
        'fi\n'
        'exit 0\n'
    )
    fake.chmod(0o755)

    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", RECORD=str(record))
    run = subprocess.run(["bash", "scripts/deploy_backend.sh"], cwd=project, env=env,
                         capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    assert record.exists(), "railway up was not called with a folder"
    assert "--path-as-root" in Path(f"{record}.args").read_text()

    uploaded = [line.removeprefix("./") for line in record.read_text().splitlines()]
    top = {path.split("/")[0] for path in uploaded}
    assert top == UPLOAD_FILES
    assert "app/api.py" in uploaded


def test_env_example_model_is_deepseek():
    plan = read_text("docs/implementation-plan.md")
    p8 = [line for line in plan.splitlines() if line.startswith("| P8 |")]
    assert len(p8) == 1
    model = re.search(r"`(deepseek/[^`]+)`", p8[0]).group(1)

    settings = dict(
        line.split("=", 1) for line in read_text(".env.example").splitlines()
        if line.strip() and not line.startswith("#")
    )
    assert settings["OPENROUTER_MODEL"].strip() == model


def test_backend_url_is_public_https():
    found = re.findall(r'^const BACKEND_URL = "([^"]*)";', read_text("web/app.js"), re.MULTILINE)
    assert len(found) == 1
    url = found[0]
    assert url.startswith("https://")
    assert "localhost" not in url and "127.0.0.1" not in url
