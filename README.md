# Workflow Deploy Demo

A demo app where testers sign in, connect their accounts (Slack, Google, Meegle) and deploy the
team's workflows to n8n, Make and Modal — then try them and see the results.

- Plan: [`docs/implementation-plan.md`](docs/implementation-plan.md)
- Progress and decisions: [`docs/progress.md`](docs/progress.md)
- Owner setup (accounts and keys): [`docs/setup-guide.md`](docs/setup-guide.md)
- Going live on Modal + Neon: [`docs/go-live.md`](docs/go-live.md)
- Platform research notes: [`docs/research-notes.md`](docs/research-notes.md)

## Layout

| Path | What |
|---|---|
| `demo-project/` | The team's original workflows (read-only) |
| `catalog/` | Demo templates generated from the originals + one `catalog.yaml` per workflow |
| `app/backend/` | Python backend (FastAPI): `workflow_demo/` package, Alembic `migrations/`, `tests/` |
| `app/frontend/` | React + Vite + TypeScript + Tailwind UI; Playwright tests in `e2e/` |
| `services/` | Modal wrappers for the shared Medium reader and Slack bot (+ the bot's opt-in patch) |
| `deploy/` | The demo on Modal (`modal_app.py`) and the production settings template |
| `scripts/` | `build_catalog.py` (regenerate templates), `compile_n8n_sdk.mjs` |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e "app/backend[dev]"
(cd app/backend && ruff check . && pytest -q)
python scripts/build_catalog.py --check      # templates match demo-project/ + fixes

# Run the demo locally with fake platforms (no credentials needed)
cp app/backend/.env.example app/backend/.env
# to save a Meegle token locally, set DATA_ENCRYPTION_KEY in .env to:
#   python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
(cd app/frontend && npm ci && npm run build)   # the backend serves app/frontend/dist
(cd app/backend && python -m workflow_demo)    # http://localhost:8000 (API docs: /api/docs)
# or, for frontend development with hot reload: (cd app/frontend && npm run dev) → http://localhost:5173

# Frontend checks
(cd app/frontend && npm run typecheck && npm test && npm run e2e)  # e2e starts the backend itself

# The Slack bot's demo patch still applies to the team's code (Node 20+)
services/slack-meegle-bot/check.sh

# Only when the Meegle digest SDK source changes (needs Node 20+):
npm install --prefix scripts
node scripts/compile_n8n_sdk.mjs demo-project/meegle-daily-digest/meegle-daily-digest.n8n-cloud-sdk.js \
  catalog/meegle-daily-digest/source.compiled.json
python scripts/build_catalog.py
```
