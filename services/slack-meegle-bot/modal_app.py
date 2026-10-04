"""The team's Slack → Meegle bot on Modal: one shared deployment (Socket Mode) for every tester.

The image is the team's code from ``demo-project/slark-meegle-bot`` plus ``demo.patch``, which is
opt-in through environment variables: with ``USER_MAP_URL`` the bot reads Slack-user → Meegle-user
mappings from the demo backend (set by "Activate for me"; containers have no persistent disk), and
with ``CARD_EVENTS_URL`` it reports created cards so testers see them under Results.

    modal secret create workflow-demo-slack-bot \\
        SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... \\
        MEEGLE_PLUGIN_ID=... MEEGLE_PLUGIN_SECRET=... MEEGLE_PROJECT_KEY=... MEEGLE_SIMPLE_NAME=... \\
        MEEGLE_WORK_ITEM_TYPE_KEY=... MEEGLE_USER_KEY=... \\
        USER_MAP_URL=<demo>/api/bot/user-map CARD_EVENTS_URL=<demo>/api/bot/cards BOT_API_TOKEN=...
    modal deploy services/slack-meegle-bot/modal_app.py

Each run lasts about an hour and queues its successor before it ends (one container at a time),
so a redeploy or a rotated secret takes effect within the hour. A 10-minute schedule starts the
bot if nothing is running or queued (first deploy, or after a failure).
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import modal

APP_NAME = "workflow-demo-slack-bot"
RUN_SECONDS = 60 * 60
BOT_DIR = "/bot"

# Local paths are only read when building (`modal deploy`), not inside the running container.
HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent.parent / "demo-project/slark-meegle-bot"
image = (
    modal.Image.from_registry("node:20-bookworm-slim", add_python="3.12")
    .apt_install("patch")
    .add_local_dir(SOURCE, BOT_DIR, copy=True, ignore=["node_modules", ".env", "data", "*.log"])
    .add_local_file(HERE / "demo.patch", "/tmp/demo.patch", copy=True)
    .run_commands(f"cd {BOT_DIR} && patch -p1 < /tmp/demo.patch && npm ci --omit=dev")
)

app = modal.App(APP_NAME)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("workflow-demo-slack-bot")],
    timeout=RUN_SECONDS + 5 * 60,
    max_containers=1,  # one Socket Mode connection
)
def run_bot() -> None:
    """Run the bot for about an hour (restarting it after a crash), then hand over to a new run."""
    deadline = time.monotonic() + RUN_SECONDS
    try:
        while (remaining := deadline - time.monotonic()) > 30:
            try:
                code = subprocess.run(["node", "src/index.js"], cwd=BOT_DIR, timeout=remaining).returncode
            except subprocess.TimeoutExpired:
                break
            print(f"bot exited with code {code}; restarting in 10 s", flush=True)
            time.sleep(10)
    finally:
        # Queued behind this run (max_containers=1): no overlap, and it runs the latest deploy.
        run_bot.spawn()


@app.function(schedule=modal.Cron("*/10 * * * *"))
def keep_running() -> None:
    """Start the bot when no run is active or queued (first deploy, or after a failure)."""
    stats = run_bot.get_current_stats()
    if stats.num_total_runners == 0 and stats.backlog == 0:
        run_bot.spawn()
