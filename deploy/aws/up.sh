#!/usr/bin/env bash
# Runs on the server (deploy.sh calls it): build and start the stack. WITH_BOT=true also runs the
# Slack bot; otherwise it is stopped. Compose doesn't always recreate a container whose image was
# rebuilt, so built services still running an older image are recreated explicitly.
set -euo pipefail
cd "$(dirname "$0")"

WITH_BOT=${WITH_BOT:-false}
CADDYFILE_HASH=$(sha256sum Caddyfile | cut -c1-16)  # a changed Caddyfile recreates caddy (compose.yml)
export CADDYFILE_HASH
PROFILE=()
[ "$WITH_BOT" = true ] && PROFILE=(--profile bot)

docker compose "${PROFILE[@]}" up -d --build --remove-orphans
[ "$WITH_BOT" = true ] || docker compose --profile bot stop bot

for service in demo reader bot; do
  [ "$service" = bot ] && [ "$WITH_BOT" != true ] && continue
  running=$(docker inspect -f '{{.Image}}' "workflow-demo-$service-1" 2>/dev/null) || continue
  built=$(docker image inspect -f '{{.Id}}' "workflow-demo-$service" 2>/dev/null) || continue
  if [ "$running" != "$built" ]; then
    docker compose "${PROFILE[@]}" up -d --no-deps --force-recreate "$service"
  fi
done
docker compose --profile bot ps
