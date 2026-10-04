# Workflow Deploy Demo

A demo web app: testers sign in (username + shared passcode), browse the team's
workflows, connect the accounts each one needs, deploy it to its own platform
(n8n, Make, Modal) under the owner's single account, then try it and see results.

## Read first (in this order)
1. `docs/progress.md` — current status, next step, phase checklists, decision log. **Update it at the end of every work session and every PR.**
2. `docs/implementation-plan.md` — demo rules, architecture, per-workflow specs, API, phases.
3. `docs/research-notes.md` — verified platform facts (n8n, Make, Zapier, Nango, Modal, Slack, Google, Meegle, Dify). Check here before re-researching.

## Repo map
- `demo-project/` — the team's original workflows. **Read-only**; never edit.
- `catalog/` — demo-ready copies of those workflows (fixes applied) + `catalog.yaml` per workflow.
- `app/backend/` — FastAPI (Python 3.12). `app/frontend/` — React + Vite + TypeScript.
- `deploy/aws/` — the hosting: one AWS EC2 server running everything with Docker Compose (provision, deploy, n8n setup scripts; `docs/go-live.md`).
- `services/` — the Slack bot's `demo.patch` (+ tests). `deploy/modal_app.py` and `services/*/modal_app.py` are the earlier Modal packaging, no longer used.
- `scripts/` — compile/bootstrap/setup-check helpers.
- `connector-demo/` — unrelated backup fixtures from an earlier n8n backup tool; leave alone.

## Rules
- Develop on branch `claude/amazing-maxwell-6md3og`. One PR per phase, only when the owner asks; PRs are sequential (the branch restarts from `main` after each merge).
- **Never commit secrets** (tokens, keys, webhook URLs). A Meegle token was once committed and history had to be rewritten. Use `.env.example` with placeholders.
- No real credentials exist yet: build and test against fake platform adapters (`DEMO_FAKE_PLATFORMS=1`) and mocked HTTP; real keys arrive at phase P7.
- Secrets go into platform credentials, never into workflow node parameters.

## Environment notes (cloud sessions)
- The network proxy blocks most documentation sites for curl/WebFetch; `git clone` from GitHub, raw.githubusercontent.com, the npm registry and PyPI work. WebSearch works.
- Compile the Meegle digest's n8n Workflow-SDK code with `@n8n/workflow-sdk` (0.34.2 verified) via `scripts/compile_n8n_sdk.mjs`.
