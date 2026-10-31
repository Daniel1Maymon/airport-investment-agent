# The backend container for Railway (Step 18, docs/implementation-plan.md P117-P118).
#
# What it is:   The recipe Railway follows to build the backend: a small Linux with Python,
#               our libraries, the app code and the airport database, then it starts the server.
# Why we need:  Railway runs a container, not our laptop's folder. Everything the server needs
#               must be inside it; nothing else should be (no secrets, no notes, no raw data).
# Used by:      Railway, when scripts/deploy_backend.sh uploads the files (railway.json says
#               "build with this Dockerfile"). Also usable on the laptop:
#                 docker build -t airport-backend . && docker run -p 8000:8000 --env-file .env airport-backend
# Design:       docs/decisions.md 7.4; docs/implementation-plan.md Step 18, P117-P121.

# Python 3.12 on a small Debian ("slim" leaves out compilers and docs we don't need).
FROM python:3.12-slim

# Print log lines at once (no buffering), so Railway's log view shows them as they happen.
ENV PYTHONUNBUFFERED=1

# All our files live in /app inside the container.
WORKDIR /app

# Libraries first, in their own layer: when only the code changes, the build reuses this layer
# and skips the slow install. --no-cache-dir keeps pip's download cache out of the image.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Only the files the server needs, named one by one (no "COPY . ."), so a secret or a note
# can never end up in the image by accident.
COPY app/ ./app/
COPY airports.duckdb ./

# Where the server finds its two files (read by app/config.py).
# The airport database stays in /app: the Railway disk is mounted at /data and hides whatever
# the image has there, so a database under /data would disappear.
ENV AIRPORTS_DB=/app/airports.duckdb
# The chat history goes on the Railway disk, so chats survive a redeploy.
ENV CHAT_DB=/data/chat.sqlite

# Make the /data folder in the image too, so the container also works without a disk
# (on the laptop). On Railway the disk is mounted over it.
RUN mkdir -p /data

# Start the server. Railway gives the port in $PORT; 8000 when it is not set (laptop).
# Shell form (no [ ]) so that $PORT is filled in; "exec" makes uvicorn the main process,
# so it gets Railway's stop signal and shuts down cleanly.
CMD exec uvicorn --factory app.api:main_app --host 0.0.0.0 --port ${PORT:-8000}
