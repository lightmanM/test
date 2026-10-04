#!/usr/bin/env bash
# Apply demo.patch to a copy of the team's bot and test the patched modules (no npm install needed).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp -r "$repo/demo-project/slark-meegle-bot/src" "$work/"
(cd "$work" && patch -p1 --quiet --no-backup-if-mismatch < "$here/demo.patch")
for file in "$work"/src/*.js; do node --check "$file"; done
# Stand-in for @slack/bolt so index.js can be loaded without installing dependencies.
mkdir -p "$work/node_modules/@slack/bolt"
cp "$here/test/stubs/bolt.js" "$work/node_modules/@slack/bolt/index.js"
BOT_DIR="$work" node --test "$here"/test/*.test.js
