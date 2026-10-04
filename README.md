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
| `app/backend/` | Python backend (FastAPI from P1) |
| `scripts/` | `build_catalog.py` (regenerate templates), `compile_n8n_sdk.mjs` |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e "app/backend[dev]"
(cd app/backend && ruff check . && pytest -q)
python scripts/build_catalog.py --check      # templates match demo-project/ + fixes

# Only when the Meegle digest SDK source changes (needs Node 20+):
npm install --prefix scripts
node scripts/compile_n8n_sdk.mjs demo-project/meegle-daily-digest/meegle-daily-digest.n8n-cloud-sdk.js \
  catalog/meegle-daily-digest/source.compiled.json
python scripts/build_catalog.py
```
