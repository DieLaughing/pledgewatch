#!/usr/bin/env bash
# Build on the server and swap in the new version without a gap: a temporary copy starts on the same port
# (SO_REUSEPORT, host network) and serves the site while the main container is recreated, then it's removed.
# Only one copy at a time runs the store checks and bots (a lock in the data folder).
# Settings in deploy.env next to this script (not committed):
#   HOST        ssh host
#   COMPOSE_DIR folder with a compose.yaml that has a `pledgewatch` service (network_mode: host)
#   DATA_DIR    the data folder mounted at /data
#   ENV_FILE    the settings file the service uses
#   REMOTE_DIR  where the source goes (default pledgewatch)
set -euo pipefail
cd "$(dirname "$0")"
[ -f deploy.env ] && . ./deploy.env
: "${HOST:?set HOST}" "${COMPOSE_DIR:?set COMPOSE_DIR}" "${DATA_DIR:?set DATA_DIR}" "${ENV_FILE:?set ENV_FILE}"
REMOTE_DIR=${REMOTE_DIR:-pledgewatch}
rsync -a --delete --exclude .venv --exclude .git --exclude /data --exclude __pycache__ --exclude .pytest_cache \
  --exclude node_modules --exclude web/dist --exclude 'deploy*.env' ./ "$HOST:$REMOTE_DIR/"
ssh "$HOST" REMOTE_DIR="$REMOTE_DIR" COMPOSE_DIR="$COMPOSE_DIR" DATA_DIR="$DATA_DIR" ENV_FILE="$ENV_FILE" bash -s <<'REMOTE'
set -euo pipefail
cd "$REMOTE_DIR"
docker build -q -t pledgewatch:latest . >/dev/null

wait_for_site() {  # container name: wait until it logs that the website is up
  for _ in $(seq 1 60); do
    docker logs "$1" 2>&1 | grep -q "site on" && return 0
    sleep 1
  done
  echo "$1 didn't start its website in 60 s" >&2; docker logs --tail 20 "$1" >&2; return 1
}

docker rm -f pledgewatch-next >/dev/null 2>&1 || true
docker run -d --name pledgewatch-next --network host --user 1000:1000 --memory 128m \
  -e PW_HOST=127.0.0.1 -v "$DATA_DIR:/data" --env-file "$ENV_FILE" pledgewatch:latest >/dev/null
wait_for_site pledgewatch-next || { docker rm -f pledgewatch-next >/dev/null; exit 1; }

docker compose --project-directory "$COMPOSE_DIR" up -d --no-deps --force-recreate pledgewatch 2>&1 | tail -1
wait_for_site pledgewatch
docker stop -t 15 pledgewatch-next >/dev/null && docker rm pledgewatch-next >/dev/null
echo "pledgewatch swapped in with no gap"
REMOTE
