# Workflow Deploy Demo

A demo app where testers sign in, connect their accounts (Slack, Google, Meegle) and deploy the
team's workflows to n8n, Make and Modal — then try them and see the results.

- Plan: [`docs/implementation-plan.md`](docs/implementation-plan.md)
- Progress and decisions: [`docs/progress.md`](docs/progress.md)
- Owner setup (accounts and keys): [`docs/setup-guide.md`](docs/setup-guide.md)
- Platform research notes: [`docs/research-notes.md`](docs/research-notes.md)

## Layout

| Path | What |
|---|---|
| `demo-project/` | The team's original workflows (read-only) |
| `catalog/` | Demo templates generated from the originals + one `catalog.yaml` per workflow |
| `app/backend/` | Python backend (FastAPI): `workflow_demo/` package, Alembic `migrations/`, `tests/` |
| `app/frontend/` | React + Vite + TypeScript + Tailwind UI; Playwright tests in `e2e/` |
| `scripts/` | `build_catalog.py` (regenerate templates), `compile_n8n_sdk.mjs` |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e "app/backend[dev]"
(cd app/backend && ruff check . && pytest -q)
python scripts/build_catalog.py --check      # templates match demo-project/ + fixes

# Run the demo locally with fake platforms (no credentials needed)
cp app/backend/.env.example app/backend/.env
(cd app/frontend && npm ci && npm run build)   # the backend serves app/frontend/dist
(cd app/backend && python -m workflow_demo)    # http://localhost:8000 (API docs: /api/docs)
# or, for frontend development with hot reload: (cd app/frontend && npm run dev) → http://localhost:5173

# Frontend checks
(cd app/frontend && npm run typecheck && npm test && npm run e2e)  # e2e starts the backend itself

# Only when the Meegle digest SDK source changes (needs Node 20+):
npm install --prefix scripts
node scripts/compile_n8n_sdk.mjs demo-project/meegle-daily-digest/meegle-daily-digest.n8n-cloud-sdk.js \
  catalog/meegle-daily-digest/source.compiled.json
python scripts/build_catalog.py
```
