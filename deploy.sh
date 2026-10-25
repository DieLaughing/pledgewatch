#!/usr/bin/env bash
# Copy the source to the server, build the image there, and restart the container with Docker Compose.
# Settings: HOST (ssh host), REMOTE_DIR (default pledgewatch), COMPOSE_DIR (folder with a compose.yaml that has a
# `pledgewatch` service). Put them in deploy.env next to this script (not committed).
set -euo pipefail
cd "$(dirname "$0")"
[ -f deploy.env ] && . ./deploy.env
: "${HOST:?set HOST in deploy.env}" "${COMPOSE_DIR:?set COMPOSE_DIR in deploy.env}"
REMOTE_DIR=${REMOTE_DIR:-pledgewatch}
rsync -a --delete --exclude .venv --exclude .git --exclude /data --exclude __pycache__ --exclude .pytest_cache --exclude node_modules --exclude web/dist \
  --exclude 'deploy*.env' ./ "$HOST:$REMOTE_DIR/"
ssh "$HOST" "cd $REMOTE_DIR && docker build -q -t pledgewatch:latest . && \
  docker compose --project-directory $COMPOSE_DIR up -d --no-deps --force-recreate pledgewatch"
