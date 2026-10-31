#!/usr/bin/env bash
# Upload the backend to Railway (Step 18, docs/implementation-plan.md P119).
#
# What it is:   Copies exactly five things into a fresh temporary folder and uploads only that
#               folder to Railway, which builds the container from it:
#                 Dockerfile        - the build recipe (Python 3.12, start command)
#                 railway.json      - Railway settings: build with the Dockerfile; the server
#                                     counts as up only when GET /health answers (wait up to
#                                     120 seconds); restart it if it crashes (up to 5 times)
#                 requirements.txt  - the libraries
#                 app/              - the backend code (without Python's __pycache__ folders)
#                 airports.duckdb   - the airport database (about 30 MB)
# Why we need:  The airport database is not in git (too big, and the secret scan blocks
#               *.duckdb files), so Railway can't build from GitHub; we upload from the laptop.
#               Uploading the whole project folder would also send secrets and notes (the
#               settings file with the OpenRouter key, raw downloads, chat history). Copying
#               only a fixed list into an empty folder means nothing else can ever leave the
#               laptop, even if new files appear in the project later.
# Used by:      a person at the terminal, from anywhere:
#                 bash scripts/deploy_backend.sh
#               Extra arguments go to `railway up` as they are.
#               tests: test_step18_deploy.py (runs this script with a fake `railway`).
# Uses:         the Railway command-line tool, logged in and linked to the project
#               airport-investment-agent; the service is "backend".
# Design:       docs/decisions.md 7.4; docs/implementation-plan.md Step 18, P117-P121.
#
# How it works, in short:
#   1. Go to the project folder (the folder above scripts/).
#   2. Stop with a clear message if the airport database is missing.
#   3. Make an empty temporary folder; it is removed at the end, even after an error.
#   4. Copy the five items into it; remove __pycache__ folders from the copied app/.
#   5. railway up <that folder> --path-as-root: upload that folder as if it were the project.

# Stop at the first failed command, on an unset variable, and on a failure inside a pipe.
set -euo pipefail

# 1. The project folder is the parent of the folder this script is in.
cd "$(dirname "$0")/.."

# 2. Without the database the server would start but could not answer anything.
if [ ! -f airports.duckdb ]; then
  echo "airports.duckdb is missing in $(pwd). Build it first with the loader (see README)." >&2
  exit 1
fi

# 3. A fresh empty folder, removed when the script ends (also on an error or Ctrl+C).
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# 4. Copy exactly the five items, nothing else.
cp Dockerfile railway.json requirements.txt airports.duckdb "$STAGE/"
cp -R app "$STAGE/app"
# Python's cached bytecode is laptop-specific and not needed in the container.
find "$STAGE/app" -name __pycache__ -type d -prune -exec rm -rf {} +

echo "Uploading to Railway:"
(cd "$STAGE" && ls -1)

# 5. --path-as-root: treat the temporary folder as the project root, so only it is uploaded.
railway up "$STAGE" --path-as-root --service backend --detach "$@"
