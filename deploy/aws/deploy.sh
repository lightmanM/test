#!/usr/bin/env bash
# Copy the code and settings to the server and (re)build and start the containers.
#   deploy/aws/deploy.sh                 # everything; the Slack bot too when deploy/aws/bot.env exists
#   deploy/aws/deploy.sh --without-bot   # everything else, and stop the bot if it runs
# Needs deploy/production.env and deploy/aws/.env. Create deploy/aws/bot.env only once no other copy
# of the bot runs anywhere (Slack would split its events between the copies).
set -euo pipefail
cd "$(dirname "$0")/../.."

NAME=workflow-demo
KEY_FILE=${SSH_KEY:-$HOME/.ssh/$NAME.pem}
APP_DIR=/opt/$NAME
WITH_BOT=false
[ -f deploy/aws/bot.env ] && WITH_BOT=true
[ "${1:-}" = "--without-bot" ] && WITH_BOT=false

die() { echo "$*" >&2; exit 1; }
value() { grep -E "^$1=" "$2" | tail -1 | cut -d= -f2-; }

for file in deploy/production.env deploy/aws/.env; do
  [ -f "$file" ] || die "Missing $file (copy it from its .example)"
done
SERVER=$(value SERVER_IP deploy/aws/.env)
[ -n "$SERVER" ] || die "Set SERVER_IP in deploy/aws/.env (provision.sh prints it)"
[ "$(value READER_API_TOKEN deploy/aws/.env)" = "$(value READER_API_TOKEN deploy/production.env)" ] \
  || die "READER_API_TOKEN differs between deploy/aws/.env and deploy/production.env"
SETTINGS="$APP_DIR/deploy/production.env $APP_DIR/deploy/aws/.env"
if $WITH_BOT; then
  [ "$(value BOT_API_TOKEN deploy/aws/bot.env)" = "$(value BOT_API_TOKEN deploy/production.env)" ] \
    || die "BOT_API_TOKEN differs between deploy/aws/bot.env and deploy/production.env"
  SETTINGS="$SETTINGS $APP_DIR/deploy/aws/bot.env"
fi
# Caddy lets only this machine reach the n8n editor (see Caddyfile); setup_n8n.py runs from here.
ADMIN_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')

SSH=(ssh -i "$KEY_FILE" -o StrictHostKeyChecking=accept-new "ubuntu@$SERVER")
# The three settings files are the only env files copied; excluded paths on the server are kept.
rsync -az --delete -e "ssh -i $KEY_FILE -o StrictHostKeyChecking=accept-new" \
  --include=/deploy/production.env --include=/deploy/aws/.env --include=/deploy/aws/bot.env \
  --exclude=.git --exclude=.env --exclude='.env.*' --exclude='*.env' --exclude='/deploy/aws/*.json' --exclude=.DS_Store \
  --exclude=node_modules --exclude=.venv --exclude=__pycache__ --exclude='*.egg-info' --exclude='.*_cache' \
  --exclude=dist --exclude='*.db' --exclude=test-results --exclude=playwright-report \
  --exclude=/connector-demo --exclude=/demo-project/slark-meegle-bot/data \
  ./ "ubuntu@$SERVER:$APP_DIR/"
"${SSH[@]}" "chmod 600 $SETTINGS && WITH_BOT=$WITH_BOT ADMIN_IP=$ADMIN_IP $APP_DIR/deploy/aws/up.sh"
