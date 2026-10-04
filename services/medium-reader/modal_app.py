"""The team's Medium reader (Freedium + CloakBrowser) on Modal, built from their own Dockerfile.

Shared by every Medium digest deployment; n8n calls ``POST <url>/extract`` with
``Authorization: Bearer <API_TOKEN>``.

    modal secret create workflow-demo-reader API_TOKEN=<READER_API_TOKEN> [FREEDIUM_BASE_URL=...]
    modal deploy services/medium-reader/modal_app.py

Then set the demo's ``READER_BASE_URL`` to the printed URL and ``READER_API_TOKEN`` to the same
token. ``READER_MIN_CONTAINERS=1`` at deploy time keeps one browser warm (cold starts can exceed
n8n's 60 s per-article timeout).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import modal

APP_NAME = "workflow-demo-medium-reader"
PORT = 8000

# Local paths are only read when building (`modal deploy`), not inside the running container.
REPO = Path(__file__).resolve().parent.parent.parent
SOURCE = REPO / "demo-project/medium-digest-project/services/medium-reader"
image = modal.Image.from_dockerfile(SOURCE / "Dockerfile", context_dir=SOURCE, add_python="3.12")

app = modal.App(APP_NAME)


@app.function(
    image=image,
    secrets=[modal.Secret.from_name("workflow-demo-reader")],
    max_containers=1,  # one browser; the server queues extractions itself
    min_containers=int(os.environ.get("READER_MIN_CONTAINERS", "0")),
    scaledown_window=15 * 60,
    timeout=10 * 60,
)
@modal.concurrent(max_inputs=4)
@modal.web_server(PORT, startup_timeout=180)
def reader() -> None:
    if not os.environ.get("API_TOKEN"):
        # Without a token the server accepts anyone's requests.
        raise RuntimeError("Set API_TOKEN in the workflow-demo-reader secret")
    env = {**os.environ, "HOST": "0.0.0.0", "PORT": str(PORT), "NODE_ENV": "production"}
    subprocess.Popen(["node", "src/server.mjs"], cwd="/service", env=env)  # the Dockerfile's WORKDIR/CMD
