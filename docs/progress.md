# Progress Tracker

Living document. Update at the end of every work session and every PR.

## Current status
- **Phase**: P0–P6 done; P7 live on AWS (2026-10-04; address in the git-ignored `deploy/aws/.env`).
  Setup check green except Make Bridge; 4 of 5 workflows available and live-tested.
- **Next step**: finish the live checklist (`docs/go-live.md` §6): Slack bot (owner's Meegle user key), redeploy/delete
  of each, second tester, short-TTL expiry; then open the PR for the AWS move and mark P7 done.
- **Blocked**: GitHub merge → Slack — Make discontinued Bridge (<https://f.make.com/bridge>); left "Deploy unavailable".

## Phases and PRs

| Phase | PR | Status | Notes |
|---|---|---|---|
| P0 Foundations | [#1](https://github.com/lightmanM/test/pull/1) | merged | repo layout, tooling, CI, catalog + fixed templates, SDK compile, setup guide |
| P1a Backend core | [#2](https://github.com/lightmanM/test/pull/2) | merged | auth, DB, catalog API, state machine, fake adapters |
| P1b Frontend | [#3](https://github.com/lightmanM/test/pull/3) | merged | sign-in, catalog, workflow page, admin shell |
| P2 Connections | [#4](https://github.com/lightmanM/test/pull/4) | merged | Nango connect + manual secrets |
| P3 n8n | [#5](https://github.com/lightmanM/test/pull/5) | merged | adapter, 3 transforms, per-deployment credentials, Run now, results |
| P4 Modal services | [#6](https://github.com/lightmanM/test/pull/6) | merged | reader + bot on Modal, bot patches, "Activate for me" |
| P5 Make Bridge | [#7](https://github.com/lightmanM/test/pull/7) | merged | Bridge adapter, popup + callback, unavailable state |
| P6 Lifecycle & admin | [#8](https://github.com/lightmanM/test/pull/8) | merged | 24 h sweeper, redeploy/delete, admin page, setup check, E2E |
| P7 Go live | [#9](https://github.com/lightmanM/test/pull/9) | packaging merged; live part waits on owner | Modal + Neon deploy, owner credentials, live checklist |

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
`google.py` (uptime spreadsheet in the user's Drive; a redeploy reuses it via `DeployContext.previous_refs`, so
edits to its Sites tab survive, and a new one is made only if the user deleted it). Deploy jobs read secrets on demand through
`DeployContext.credentials` (`services.connections.UserCredentials`; Google tokens include the refresh token so n8n
refreshes them with our OAuth client). Every credential is per deployment — including the owner's OpenAI key and
reader token (no shared bootstrap) — and named `demo · <user> · <workflow> · <slot>`; a failed deploy deletes what it
created (credentials, workflow, spreadsheet). The Run-now header token is an HMAC of the webhook path with the
session secret (nothing stored). Results: executions with `includeData`, summarized from the catalog's
`result_nodes` (uptime lines per site, digest/report text). The spreadsheet link is shown to the user (`links`).
Platforms without owner credentials show "Not set up on this server yet (…)"; per-workflow config gaps are listed
(owner-provided values/credentials come from one table, `SHARED_VALUES` / `SHARED_CREDENTIALS`). The "no leading
`=`" rule is checked at request time for n8n workflows (422 with field errors) and again in the transform.
Review fixes: cleanup deletes each item independently and never logs tokens; fake connections are refused for
secrets too; one Nango read per connector per deploy; run summaries fetch execution data once per finished
execution (cached) instead of on every poll; `fresh_credentials` is the single Nango read path.
- [x] n8n client (credentials, workflows, publish/activate fallback, executions, webhook)
- [x] Transforms + golden tests for uptime, meegle digest, medium digest
- [x] Google Sheet creation for uptime; owner-provided OpenAI + reader keys as per-deployment credentials
- [x] Run-now webhook; result summaries; API-level flow test with mocked Nango + n8n

### P4 Modal services
Notes: `services/README.md` has the deploy commands (P7). Reader: `Image.from_dockerfile` on the team's Dockerfile
(+ Python), `@modal.web_server(8000)`, refuses to start without `API_TOKEN`, one container (optionally kept warm).
Bot: Node 20 image with the team's code + `services/slack-meegle-bot/demo.patch` (opt-in env vars: `USER_MAP_URL`
→ parallel async lookups against the demo, `CARD_EVENTS_URL` → non-blocking card reports, demo hint instead of
`/meegle-bind`; file mode unchanged). `run_bot` runs ~1 h (restarting node after crashes) and queues its successor
in `finally` (`max_containers=1`, so no overlap and a redeploy/secret applies within the hour); a 10-minute cron
starts it when nothing runs or is queued. `check.sh` (CI job `services`) applies the patch to a copy and runs Node
tests, including the mention handler with stubbed bolt/Meegle. Demo side: `api/bot.py`
(`GET /api/bot/user-map/{slack_user_id}`, `POST /api/bot/cards`, Bearer `BOT_API_TOKEN`), `services/bot.py`
(lookups only over live bot deployments — active and before `expires_at` — and answered from the tester's
current Slack + Meegle connections, so deactivate/expiry/disconnect ends the mapping; long card titles shortened), `adapters/modal.py`
(`SharedBotAdapter`: Activate records `slack_user_id` + Meegle user key in refs; real Slack connection required,
optional `SLACK_BOT_TEAM_ID` workspace check; card history kept on redeploy). The fake adapter records the same refs.
- [x] `services/medium-reader/modal_app.py` (team Dockerfile + web_server)
- [x] `services/slack-meegle-bot/modal_app.py` + opt-in patch (user map via API, card events) + Node tests
- [x] Bot API endpoints; "Activate for me" flow; E2E posts a bot card and sees it under Results

### P5 Make Bridge
Notes: `make_bridge.py` (portal API client; HS256 JWT per request built with the stdlib — `kid` = key ID, `sub` =
`workflow-demo:<username>`, 2-minute expiry, random `jti`; optional `teamId`), `adapters/make.py`
(`MakeBridgeAdapter`). Deploy: `init` with `redirectUri` = the signed `/make/callback?state=…` → `awaiting_user` with
Make's `publicUrl` (the existing popup handling opens it) → callback claims `awaiting_user → deploying` (a repeated
redirect is a no-op) and queues a `finish` job, so the popup page answers at once → the job polls `check-init` for
up to ~2 min (transient errors retried) → activates the scenario (extra scenarios and same-named leftovers from
abandoned popups deleted; on failure everything created is deleted). Undeploy: deactivate + delete; if the callback
never arrived, the flow is checked; same-named leftovers are removed too. Run now: `/integrations/{id}/run`; results
from `/scenarios/{id}/logs` (only entries with status 1 ok / 2 warnings / 3 error). Availability (single-flight,
any 2xx = available): missing settings → "Not set up…"; 401 → "Make rejected the demo's Bridge key…" (rechecked
after 1 min); 403/404 → "Make Bridge isn't enabled…" (10 min); unreachable → rechecked after 1 min. Settings now
treat empty env values as unset (`env_ignore_empty`), so `.env.example` copies cleanly.
- [x] Bridge client (JWT per request), availability check → "unavailable"
- [x] init → popup → `/make/callback` → check-init → activate; run; logs; delete
- [x] `catalog/github-merge-slack/make-setup.md` (JWT details, redirect URL, settings)

### P6 Lifecycle & admin
Notes: `services/sweeper.py` — `sweep()` stops deployments past `expires_at` (active/failed) or stuck in
`awaiting_user` for an hour, fails jobs queued/running for 30 min, and asks each adapter with `sweep_orphans()` to
remove demo items nothing references — **only with `ORPHAN_SWEEP=true`**, set on the one hosted instance that owns
the platform accounts (a local run with the same keys would otherwise delete the hosted demo's items). n8n: `[demo] …`
workflows / `demo · …` credentials older than 1 h, each delete independent; refs of rows whose workflow left the
catalog still count. Make: users with Make activity in the last 2 days, one listing each, re-checking the database
right before each delete (a popup may have just started); failed deletes are reported as errors. Auto-stops carry
their own messages (time limit vs. unfinished popup) and clear `expires_at`, so a failing clean-up isn't retried
every sweep. The thread is joined on shutdown before the HTTP client closes. A daemon thread runs it every `SWEEP_INTERVAL_SECONDS` (600; 0 = off); P7 adds a Modal cron for
when the web app scales to zero. `DEPLOYMENT_TTL_HOURS` accepts fractions for a live expiry test.
`services/setup_check.py` — database, mode, Nango (key + slack/google integrations), encryption key, n8n (API key),
Google client, LLM key (`/models`), reader (`/healthz`), Make Bridge and Slack bot (adapter availability), plus every
workflow's availability; states ok / missing / error / info. Admin API: `GET /api/admin/setup`,
`POST /api/admin/sweep`, `POST /api/admin/users/{user}/deployments/{workflow}/stop` ("Stopped by the admin").
Admin page: setup check, "Run sweeper now", Stop per deployment.
- [x] Sweeper: 24 h expiry, abandoned popups, lost jobs
- [x] Orphan sweep: n8n workflows/credentials and Make scenarios that no deployment references
- [x] Admin page: setup check, sweep now, stop a deployment
- [x] E2E: admin setup check, sweeper, stop

### P7 Go live
Notes: `deploy/modal_app.py` — the demo on Modal: `web` (ASGI, FastAPI + built SPA, `@modal.concurrent`), `Jobs.run`
(one function call per deploy job via `ModalJobRunner` → survives web scale-down; services built once per container
with `@modal.enter`, DB pool disposed on exit), `sweeper` (cron every 30 min, so Neon can suspend; the Modal entrypoints
force `recover_jobs_on_startup=False` and `sweep_interval_seconds=0` in code since several containers share the DB),
`migrate` (`alembic upgrade head`, via `MIGRATION_DATABASE_URL` = Neon's direct URL if set). Containers refuse a
non-Postgres `DATABASE_URL`. A job that can't be started fails its deployment at once (503) instead of leaving it
busy. Settings come from the Modal secret `workflow-demo-app`
(`deploy/production.env.example`, `ORPHAN_SWEEP=true`). Step-by-step: `docs/go-live.md`.
**Moved to AWS (2026-10-04)**: one EC2 t3.large in `pond-new` us-west-2 (us-east-2 had no vCPU quota) running Docker
Compose (`deploy/aws/`): Caddy (sslip.io hostnames, Let's Encrypt), the demo (one process: thread job runner, sweeper
thread, migrations on start), self-hosted n8n 2.41.6 + `n8nio/runners` (external mode), the team's reader (its own
Dockerfile — the Modal build failed on `add_python`), the team's bot (+ `demo.patch`) and Postgres 17 (demo + n8n
databases). `provision.sh` (EC2/SG/key/EIP), `deploy.sh` (rsync + compose; checks shared tokens match),
`setup_n8n.py` (owner + API key via n8n's REST API). The Modal files remain but are unused.
Accounts set up: Google Cloud project "Workflow Demo" (External, Testing, 9 test users, 5 scopes, web client →
Nango), Slack app "Workflow Demo", Nango prod (`slack`, `google` created through its API), OpenAI key.
Live fixes (test-first): n8n 2.x refuses to delete a published workflow (409) and unpublishes in the background →
`delete_workflow` unpublishes (`/unpublish`, `/deactivate` fallback) and retries for ~15 s; Medium digest's Gmail node
gets `alwaysOutputData` so an empty inbox reaches "Build empty report" (bug in the team's original too); a refused
Nango refresh (`invalid_credentials`) asks to reconnect. 165 backend tests.
- [x] Modal app for the demo (web, jobs, sweeper, migrate) + production settings template + go-live guide
- [x] AWS server + Compose stack; owner credentials configured; setup check green (Make Bridge: discontinued)
- [ ] Live test of every workflow — uptime ✓ (deploy, run, delete), Medium ✓ (deploy, redeploy, run), Meegle digest ✓
      (deploy, run); Slack bot, second tester and short-TTL expiry still to do (`docs/go-live.md` §6)

## Decision log

| Date | Decision |
|---|---|
| 2026-10-04 | Scope: 5 workflows in `demo-project/` (3 n8n, 1 Make, 1 Node Slack bot). No Zapier, no Dify. |
| 2026-10-04 | n8n + Modal: demo handles authorization and creates platform credentials at deploy. |
| 2026-10-04 | Make: users authorize in Make's popup via Make Bridge; if Bridge unavailable, show "Deploy unavailable" (no HTTP-module fallback). |
| 2026-10-04 | Slack bot: one shared deployment with a demo bot app (owner provides later); testers "Activate for me" with their Meegle user key. |
| 2026-10-04 | Use Nango Cloud for Slack + Google token storage/refresh (not our own OAuth code). |
| 2026-10-04 | Google OAuth client is **Internal** (company Workspace accounts only). |
| 2026-10-04 | Hosting moved from Modal + Neon + n8n Cloud to **one AWS EC2 server** (owner's AWS credits): Docker Compose with self-hosted n8n, the reader, the bot and Postgres. |
| 2026-10-04 | **Make Bridge discontinued** by Make: GitHub merge → Slack stays "Deploy unavailable" for now (option C): `DISABLED_WORKFLOWS=github-merge-slack` on the server shows the catalog's `unavailable_note` to testers. Alternatives on file: rebuild on n8n (recommended) or Make Core with HTTP modules. |
| 2026-10-04 | Google OAuth client changed to **External + Testing** (testers span joinpond.ai and cryptopond.xyz; an Internal app covers one organization). Testers are added as test users in the Cloud console only — not in this public repo. A refused Nango refresh (`invalid_credentials`) now tells the tester to reconnect. |
| 2026-10-04 | Meegle MCP token: per-user text box, encrypted in our DB. |
| 2026-10-04 | Freedium kept for the Medium reader (owner's decision; risk noted in plan §14). |
| 2026-10-04 | Limits: ≤10 users · uptime every 30 min · Medium ≤5 articles/run · deployments expire after 24 h. |
| 2026-10-04 | Workflow fixes approved: Make merged-PR filter · uptime status-update + remove Gmail node · Meegle digest Slack post only with webhook. |
| 2026-10-04 | Hosting: Modal (app + jobs) + Neon Postgres. Shared passcode supplied by owner at go-live. |
| 2026-10-04 | Leaked Meegle token removed from git history (2 commits rewritten; `main` now at e7c40dc). Owner to revoke the token in Meegle. |

## Session log
- 2026-10-04: Tester bug (uptime): changing "Websites to monitor" and redeploying kept the old sites — the redeploy reused the spreadsheet and ignored the list. Now the list is written into the Sites tab when it changed since it was last written (`sites_written` ref; older deployments rewrite once); unchanged lists keep edits made in the sheet. Verified live; 169 backend tests.
- 2026-10-04: P7 live on AWS: provisioned the server, deployed the stack, set up Google/Slack/Nango/OpenAI, live-tested uptime, Medium and Meegle digest; fixed n8n delete (unpublish + retry) and the Medium empty-inbox path (165 backend tests).
- 2026-10-04: Go-live prep: Google OAuth switched to External + Testing (docs: setup guide §3, go-live, plan R14/§15, research notes); expired Nango connections now ask to reconnect (158 backend tests).
- 2026-10-04: PR #9 (P7 packaging) merged — all 9 PRs in. Remaining: the live go-live run with the owner's credentials.
- 2026-10-04: PR #8 (P6) merged. P7 packaging: Modal app for the demo, production settings template, go-live guide; reviewed (10 findings fixed), 157 backend tests.
- 2026-10-04: PR #7 (P5) merged. P6 implemented and reviewed (10 findings fixed): 156 backend tests, 5 E2E (admin lifecycle).
- 2026-10-04: PR #6 (P4) merged. P5 implemented and reviewed (10 findings fixed): 143 backend tests (Bridge client + adapter contract, API popup flow).
- 2026-10-04: PR #5 (P3) merged. P4 implemented and reviewed (8 findings fixed): 127 backend tests, 3 bot Node tests, 5 E2E.
- 2026-10-04: PR #4 (P2) merged. P3 implemented and reviewed (10 findings fixed): 117 backend tests (transform golden, adapter contract, API flow).
- 2026-10-04: PR #3 (P1b) merged. P2 implemented and reviewed (10 findings fixed): 88 backend tests, 8 unit + 5 E2E (frontend).
- 2026-10-04: PR #2 (P1a) merged. P1b implemented: 4 E2E + 3 unit (frontend), 70 backend tests.
- 2026-10-04: PR #1 (P0) reviewed, fixed, CI green, merged. P1a implemented, reviewed (10 findings fixed): 69 tests passing.
- 2026-10-04: P0 implemented (catalog, template fixes, compile script, setup guide, CI); 20 tests passing.
- 2026-10-03/04: feasibility research (n8n, Make, Zapier, Dify, Nango, Modal), evaluated all 5 workflows, cleaned leaked token from history, wrote `docs/implementation-plan.md`, added this tracker, `CLAUDE.md` and `docs/research-notes.md`.
