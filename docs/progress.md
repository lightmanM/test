# Progress Tracker

Living document. Update at the end of every work session and every PR.

## Current status
- **Phase**: P3 n8n — in review.
- **Next step**: merge the P3 PR, then start P4 (Modal services: reader + Slack bot).
- **Blocked on owner**: nothing until P7 (credentials). See plan §15.

## Phases and PRs

| Phase | PR | Status | Notes |
|---|---|---|---|
| P0 Foundations | [#1](https://github.com/lightmanM/test/pull/1) | merged | repo layout, tooling, CI, catalog + fixed templates, SDK compile, setup guide |
| P1a Backend core | [#2](https://github.com/lightmanM/test/pull/2) | merged | auth, DB, catalog API, state machine, fake adapters |
| P1b Frontend | [#3](https://github.com/lightmanM/test/pull/3) | merged | sign-in, catalog, workflow page, admin shell |
| P2 Connections | [#4](https://github.com/lightmanM/test/pull/4) | merged | Nango connect + manual secrets |
| P3 n8n | #5 | in review | adapter, 3 transforms, per-deployment credentials, Run now, results |
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
Notes: `create_app()` in `workflow_demo/app.py`; services container (`services/container.py`), lifecycle in
`services/deployments.py` (request → `Job` row → runner → adapter), states in `services/states.py`. Fake adapters
(`adapters/fake.py`) include a fake Make popup (`/fake/make-popup` → `/make/callback`). Fake-mode connect:
`POST /api/connections/{id}/fake` (real flows in P2). Local run: `python -m workflow_demo` with `.env.example`.
Review fixes: status changes claimed with conditional UPDATEs (no double jobs); jobs only run in the expected
state; `recover_stale_jobs` (startup now, sweeper in P6); `request_expire` for P6; popup state carries a one-time
nonce per deploy attempt (`DeployContext.user_step_state` / `callback_url`); new settings travel in `Job.payload`
so undeploy uses the old ones; Alembic reads `.env`; Postgres URLs normalized to psycopg 3; login race/cap
handled; session cookie also checks the username.
- [x] FastAPI app, settings, Postgres models + Alembic migration
- [x] Sign-in (username + passcode, 10-user cap, cookie session); admin passcode
- [x] Catalog API; deployment state machine + events; fake adapters
- [x] Unit tests

### P1b Frontend
Notes: `app/frontend` (React 18 + Vite 5 + TS + Tailwind 4 + TanStack Query + React Router). The backend serves the
build (`app/frontend/dist`, SPA fallback; override with `WORKFLOW_DEMO_FRONTEND_DIST`). Make popup: opened blank on
click, navigated when the job returns `popup_url`, closes itself and `postMessage`s back. Connect buttons use the
fake-mode endpoint until P2. Playwright E2E (`npm run e2e`) starts the backend in fake mode on port 8765; locally
set `PW_CHROMIUM_PATH=/opt/pw-browsers/chromium` and `PYTHON=.venv/bin/python`.
Review fixes: popup closed if the deploy ends without reaching Make; select inputs keep option types and show
"Choose…" for invalid values; non-401 errors show a retry; connect errors clear; safe sign-out; delete guarded;
catch-all route answers unknown non-GET/API paths with 404; `safe_static_file` tested; shared `isTransitional`.
- [x] Sign-in, catalog, workflow page (connect / settings / deploy / try), admin shell
- [x] Playwright click-through in fake mode

### P2 Connections
Notes: `nango.py` (REST client: connect sessions, get connection with refresh, delete), `crypto.py` (AES-256-GCM,
associated data `user:{id}:connector:{id}`), `services/connections.py` (flows + per-connector checks) and
`api/connections.py`. Connect: `POST /api/connections/{id}/session` → Nango Connect UI (`@nangohq/frontend`,
lazy-loaded, `src/nango.ts`) → `POST …/complete {connection_id}`; the backend re-reads the connection from Nango and
requires `tags.end_user_id == username` and the expected integration; a reconnect deletes the old Nango connection.
Stored details (never tokens): Slack team, `slack_user_id`, `bot_user_id`; Google email (OpenID userinfo). Deploys
call `fresh_credentials()` (Nango refreshes) and `read_secret()`. Manual values: `PUT …/secret`; secret ones are
shown only as "saved · ends with 1234". `GET /api/slack/channels` feeds the settings picker (falls back to an ID box).
Without `NANGO_SECRET_KEY`, fake mode keeps the demo-data button; `/api/health` reports `nango_enabled`.
Review fixes: rows are saved before the replaced Nango connection is deleted (`_store`), and a concurrent first save
retries as an update; the secret-storage check runs before any change; connection IDs are validated and URL-escaped;
unexpected Nango responses become clean errors; damaged ciphertexts raise `CryptoError`; the refresh token is never
requested; the Connect UI uses the server's `NANGO_HOST` / `NANGO_CONNECT_URL`; one shared, closed HTTP client;
`.env.example` has no real key.
- [x] Nango connect session + verify tags + store connection; Slack channel picker
- [x] Manual secrets (Meegle token, user key) with AES-GCM
- [x] Tests with mocked Nango (respx), Connect UI unit tests, E2E for the token and user-key forms

### P3 n8n
Notes: `n8n/client.py` (public API: credentials, workflows, `/publish` with `/activate` fallback, executions,
webhook calls), `n8n/transform.py` (fills `__VALUE:x__` placeholders — whole values only, never a leading `=`
so user input can't become an n8n expression; wires credential slots; adds the "Run now (demo)" Webhook node with
header auth; keeps only API-accepted node/settings fields), `adapters/n8n.py` (deploy/undeploy/run/results) and
`google.py` (uptime spreadsheet in the user's Drive). Deploy jobs read secrets on demand through
`DeployContext.credentials` (`services.connections.UserCredentials`; Google tokens include the refresh token so n8n
refreshes them with our OAuth client). Every credential is per deployment — including the owner's OpenAI key and
reader token (no shared bootstrap) — and named `demo · <user> · <workflow> · <slot>`; a failed deploy deletes what it
created (credentials, workflow, spreadsheet). The Run-now header token is an HMAC of the webhook path with the
session secret (nothing stored). Results: executions with `includeData`, summarized from the catalog's
`result_nodes` (uptime lines per site, digest/report text). The spreadsheet link is shown to the user (`links`).
Platforms without owner credentials show "Not set up on this server yet (…)"; per-workflow config gaps are listed.
- [x] n8n client (credentials, workflows, publish/activate fallback, executions, webhook)
- [x] Transforms + golden tests for uptime, meegle digest, medium digest
- [x] Google Sheet creation for uptime; owner-provided OpenAI + reader keys as per-deployment credentials
- [x] Run-now webhook; result summaries; API-level flow test with mocked Nango + n8n

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
- 2026-10-04: PR #4 (P2) merged. P3 implemented: 112 backend tests (transform golden, adapter contract, API flow).
- 2026-10-04: PR #3 (P1b) merged. P2 implemented and reviewed (10 findings fixed): 88 backend tests, 8 unit + 5 E2E (frontend).
- 2026-10-04: PR #2 (P1a) merged. P1b implemented: 4 E2E + 3 unit (frontend), 70 backend tests.
- 2026-10-04: PR #1 (P0) reviewed, fixed, CI green, merged. P1a implemented, reviewed (10 findings fixed): 69 tests passing.
- 2026-10-04: P0 implemented (catalog, template fixes, compile script, setup guide, CI); 20 tests passing.
- 2026-10-03/04: feasibility research (n8n, Make, Zapier, Dify, Nango, Modal), evaluated all 5 workflows, cleaned leaked token from history, wrote `docs/implementation-plan.md`, added this tracker, `CLAUDE.md` and `docs/research-notes.md`.
