# Progress Tracker

Living document. Update at the end of every work session and every PR.

## Current status
- **Phase**: P0 Foundations — in review.
- **Next step**: merge the P0 PR, then start P1a (backend core).
- **Blocked on owner**: nothing until P7 (credentials). See plan §15.

## Phases and PRs

| Phase | PR | Status | Notes |
|---|---|---|---|
| P0 Foundations | [#1](https://github.com/lightmanM/test/pull/1) | in review | repo layout, tooling, CI, catalog + fixed templates, SDK compile, setup guide |
| P1a Backend core | — | not started | auth, DB, catalog API, state machine, fake adapters |
| P1b Frontend | — | not started | sign-in, catalog, workflow page, admin shell |
| P2 Connections | — | not started | Nango connect + manual secrets |
| P3 n8n | — | not started | adapter, 3 transforms, shared credentials, Run now, results |
| P4 Modal services | — | not started | reader + bot on Modal, bot patches, "Activate for me" |
| P5 Make Bridge | — | not started | Bridge adapter, popup + callback, unavailable state |
| P6 Lifecycle & admin | — | not started | 24 h sweeper, redeploy/delete, admin page, setup check, E2E |
| P7 Go live | — | not started | Modal + Neon deploy, owner credentials, live checklist |

## Phase checklists

### P0 Foundations
Notes: backend package `app/backend/workflow_demo` (catalog models/loader, template fixes, n8n JSON helpers);
`scripts/build_catalog.py [--check]` regenerates `catalog/*/workflow.json` + `blueprint.json` from
`demo-project/`; CI (`.github/workflows/ci.yml`) runs ruff, pytest and the template check. Frontend
tooling moves to P1b; `services/` and `deploy/` folders are created in P4/P7.
Review fixes (self-review, high): uptime loop one site per batch (cross-join Merge), blank Status = UP,
alert text DOWN/still DOWN/back UP; Meegle digest posts with the Slack bot token + channel instead of an
incoming-webhook URL (secret in node params) — `incoming-webhook` scope dropped; Make filter also requires
merged within 20 min (trigger watches *updated* PRs); `insert_between` keeps output/input indexes; build
targets in one place (`catalog/build.py`); CI recompiles the Meegle SDK source to catch drift.
- [x] Repo layout (`app/`, `catalog/`, `services/`, `deploy/`, `scripts/`) and tooling (ruff, pytest, Vite, TypeScript)
- [x] `catalog/*/catalog.yaml` for all 5 workflows (connectors, settings schema, how to try, result source)
- [x] `scripts/compile_n8n_sdk.mjs` → `catalog/meegle-daily-digest/workflow.json`
- [x] Fixed templates: uptime (status update, no Gmail node, 30 min, Slack token auth), meegle digest (token via credential, IF before Slack), medium digest (5 articles, reader auth, timeouts)
- [x] `docs/setup-guide.md`: Slack app manifests (connect + bot), Google Internal OAuth client steps, Nango integrations, Make Bridge template steps, Modal, Neon

### P1a Backend core
- [ ] FastAPI app, settings, Postgres models + Alembic migration
- [ ] Sign-in (username + passcode, 10-user cap, cookie session); admin passcode
- [ ] Catalog API; deployment state machine + events; fake adapters
- [ ] Unit tests

### P1b Frontend
- [ ] Sign-in, catalog, workflow page (connect / settings / deploy / try), admin shell
- [ ] Playwright click-through in fake mode

### P2 Connections
- [ ] Nango connect session + verify tags + store connection; Slack channel picker
- [ ] Manual secrets (Meegle token, user key) with AES-GCM
- [ ] Tests with mocked Nango

### P3 n8n
- [ ] n8n client (schema check, credentials, workflows, publish/activate fallback, executions)
- [ ] Transforms + golden tests for uptime, meegle digest, medium digest
- [ ] Google Sheet creation for uptime; shared OpenAI + reader credentials bootstrap
- [ ] Run-now webhook; result summaries

### P4 Modal services
- [ ] `services/medium-reader/modal_app.py` (team Dockerfile + web_server)
- [ ] `services/slack-meegle-bot/modal_app.py` + opt-in patches (user map via API, card events)
- [ ] Bot API endpoints; "Activate for me" flow

### P5 Make Bridge
- [ ] Bridge client (JWT per request), availability check → "unavailable"
- [ ] init → popup → `/make/callback` → check-init → activate; run; logs; delete
- [ ] `catalog/github-merge-slack/make-setup.md`

### P6 Lifecycle & admin
- [ ] Sweeper: 24 h expiry, status reconcile
- [ ] Redeploy / delete hardening; admin page; setup check
- [ ] E2E lifecycle tests

### P7 Go live
- [ ] Deploy demo + services to Modal; Neon migration
- [ ] Owner credentials configured; setup check green
- [ ] Live test of every workflow; short-TTL expiry test

## Decision log

| Date | Decision |
|---|---|
| 2026-10-04 | Scope: 5 workflows in `demo-project/` (3 n8n, 1 Make, 1 Node Slack bot). No Zapier, no Dify. |
| 2026-10-04 | n8n + Modal: demo handles authorization and creates platform credentials at deploy. |
| 2026-10-04 | Make: users authorize in Make's popup via Make Bridge; if Bridge unavailable, show "Deploy unavailable" (no HTTP-module fallback). |
| 2026-10-04 | Slack bot: one shared deployment with a demo bot app (owner provides later); testers "Activate for me" with their Meegle user key. |
| 2026-10-04 | Use Nango Cloud for Slack + Google token storage/refresh (not our own OAuth code). |
| 2026-10-04 | Google OAuth client is **Internal** (company Workspace accounts only). |
| 2026-10-04 | Meegle MCP token: per-user text box, encrypted in our DB. |
| 2026-10-04 | Freedium kept for the Medium reader (owner's decision; risk noted in plan §14). |
| 2026-10-04 | Limits: ≤10 users · uptime every 30 min · Medium ≤5 articles/run · deployments expire after 24 h. |
| 2026-10-04 | Workflow fixes approved: Make merged-PR filter · uptime status-update + remove Gmail node · Meegle digest Slack post only with webhook. |
| 2026-10-04 | Hosting: Modal (app + jobs) + Neon Postgres. Shared passcode supplied by owner at go-live. |
| 2026-10-04 | Leaked Meegle token removed from git history (2 commits rewritten; `main` now at e7c40dc). Owner to revoke the token in Meegle. |

## Session log
- 2026-10-04: P0 implemented (catalog, template fixes, compile script, setup guide, CI); 20 tests passing.
- 2026-10-03/04: feasibility research (n8n, Make, Zapier, Dify, Nango, Modal), evaluated all 5 workflows, cleaned leaked token from history, wrote `docs/implementation-plan.md`, added this tracker, `CLAUDE.md` and `docs/research-notes.md`.
