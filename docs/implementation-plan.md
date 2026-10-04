# Workflow Deploy Demo — Implementation Plan

Status: draft for review · Branch: `claude/amazing-maxwell-6md3og`

A demo web app where a tester signs in, browses the team's workflows, connects the
accounts each workflow needs, deploys it to the workflow's own platform (n8n, Make,
Modal), and then tries it and sees the results. All deployments run under the
owner's single account on each platform.

---

## 1. Demo rules (agreed)

| # | Rule |
|---|---|
| R1 | **Sign-in**: any username (3–20 chars, `a-z 0-9 -`) + one shared passcode. No per-user passwords; anyone who knows a username can use it. |
| R2 | **Max 10 users.** The 11th new username is rejected ("demo is full"). |
| R3 | **Catalog**: the 5 workflows in `demo-project/` (section 3). |
| R4 | **One deployment per user per workflow.** Actions: Deploy → Redeploy (replaces it) → Delete. |
| R5 | **Deployments stop automatically 24 hours** after (re)deploy. |
| R6 | **Connections are per user** and reused across that user's workflows. Reconnect, then Redeploy to apply. |
| R7 | **n8n / Modal workflows**: the demo handles authorization (Nango popups for Slack and Google; a text box for Meegle) and creates platform credentials at deploy time. |
| R8 | **Make workflow**: the user authorizes GitHub and Slack in Make's own popup (Make Bridge). If Bridge isn't enabled on the account, the card shows **"Deploy unavailable"**. |
| R9 | **Slack bot** is one **shared** deployment (Slack can't route one app's events to several copies). For a tester, "Deploy" means **"Activate for me"**: link their Slack user to their Meegle user key. |
| R10 | **Results**: each deployment page shows status, recent runs, a **Run now** button where possible, and links to where real output lands (Slack, Google Sheet, Meegle). |
| R11 | **Limits**: uptime checks every 30 min · Medium digest ≤ 5 articles per run. |
| R12 | **Workflow fixes** applied: Make reacts only to merged PRs · Uptime status-update fixed and unconnected Gmail step removed · Meegle digest posts to Slack only when a webhook is set. |
| R13 | **Freedium is kept** for Medium article fetching (owner's decision). |
| R14 | **Google OAuth app is External, kept in "Testing"**: only the Google accounts on its test-user list (≤100, added one by one) can connect; sign-ins end after 7 days and the demo asks to reconnect. (Was "Internal"; the testers span two Workspace domains.) |

---

## 2. Architecture

```
 Browser (React SPA)
   │  cookie session
   ▼
 Caddy (HTTPS) ─► Demo backend (FastAPI) ──── Postgres (users, connections, deployments, events)
   │                  all on one AWS EC2 server (Docker Compose, deploy/aws/)
   ├── Nango Cloud ............ Slack + Google OAuth popups, token storage & refresh
   ├── n8n (same server) ...... credentials + workflows for 3 n8n workflows; Code nodes in a runner sidecar
   ├── Make Bridge (portal) ... popup-based instancing of the Make workflow (runs on Make's cloud)
   ├── Same server ............ shared services: medium-reader, slack-meegle-bot
   └── Background jobs: a thread pool in the demo process for deploy/undeploy jobs; 10-min sweeper thread
```

**Tech stack**
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, Pydantic v2, httpx, PyJWT (Bridge), `cryptography` (AES-GCM for manual secrets).
- Frontend: React + Vite + TypeScript + Tailwind; `@nangohq/frontend` for the Connect UI.
- Hosting (changed at P7, 2026-10-04): one AWS EC2 server in the owner's `pond-new` account running Docker Compose — Caddy, the demo (one process: API + built SPA, job thread pool, sweeper thread), self-hosted n8n + `n8nio/runners`, the Medium reader, the Slack bot and Postgres. Originally Modal + Neon + n8n Cloud; `deploy/modal_app.py` and `services/*/modal_app.py` are that earlier packaging and are no longer used.

**Why jobs run in the demo process**: one long-running server never scales to zero, so a thread pool is enough; on start, jobs left unfinished by a restart are failed (`recover_jobs_on_startup`) and the UI polls status.

---

## 3. Workflow catalog

Templates in `catalog/<id>/` are **demo-ready copies** of the team's originals in
`demo-project/` with the approved fixes applied (originals stay untouched). At
deploy time a per-workflow **transform** injects the user's values, credentials and
a "Run now" trigger.

### 3.1 `uptime-monitor` (n8n) — from `Host your own uptime monitoring with scheduled triggers.json`

- **What it does**: every 30 min, reads sites from a Google Sheet, checks each, logs results, alerts Slack when a site goes down / stays down / recovers.
- **Connectors**: Google (Nango; Sheets) · Slack (Nango; bot token).
- **User settings**: Slack channel (picker); sites to monitor (default: `https://example.com` and one always-failing URL so the alert path is visible).
- **Template fixes**: remove unconnected Gmail node; rewrite "Update Site Status" to update the `Sites` tab row matched by `Property` with `Status = UP/DOWN`; loop processes one site at a time (the cross-join Merge paired every response with every site); blank Status treated as UP; alert text says DOWN / still DOWN / back UP; schedule 1 min → 30 min; Slack node auth → access token (`slackApi`); resource locators switched to ID mode (no Drive listing needed).
- **Deploy job**:
  1. Get the user's Google token from Nango; create spreadsheet "Uptime monitor (demo)" in the user's Drive with tabs `Sites` (Property, Status), `Log` (date, Property, UP_FROM_UP, DOWN_FROM_DOWN, UP_FROM_DOWN, DOWN_FROM_UP) and seed the sites.
  2. n8n credentials: `googleSheetsOAuth2Api` (our Google client ID/secret + Nango tokens — n8n refreshes Google tokens itself), `slackApi` (bot token), `httpHeaderAuth` for the Run-now webhook.
  3. Transform (sheet ID/tab IDs, channel, credentials, webhook trigger) → `POST /workflows` → publish.
- **Try it / results**: Run now → Slack alert for the failing site; rows appear in the sheet. Demo shows recent executions with per-site status (from "Calculate Status").
- **Undeploy**: unpublish + delete workflow and its credentials. The sheet stays in the user's Drive.

### 3.2 `meegle-daily-digest` (n8n) — from `meegle-daily-digest/`

- **What it does**: weekdays 09:00 (plus on demand), pulls bugs and stories from Meegle via its MCP server, aggregates them, posts a Chinese daily report.
- **Connectors**: Meegle MCP token (text box, encrypted in our DB) · Slack (Nango; bot token).
- **User settings**: Slack channel, Meegle project key, Meegle simple name, look-back window (default 24 h; 720 h option for richer demo data).
- **Template**: compiled from the team's n8n Workflow-SDK code to n8n JSON by `scripts/compile_n8n_sdk.mjs` (verified with `@n8n/workflow-sdk` 0.34.2), committed as `catalog/meegle-daily-digest/workflow.json`.
- **Template fixes**: token removed from the Config node; both MCP HTTP nodes authenticate with an `httpHeaderAuth` credential (`X-Mcp-Token`); the incoming-webhook post is replaced by a Slack node using the bot token (a webhook URL is a secret and would sit in node parameters); an IF node posts only when a channel is set.
- **Deploy job**: credentials (`httpHeaderAuth` for Meegle, `slackApi`, webhook auth) → inject Config values → create → publish.
- **Try it / results**: Run now → report in Slack; demo shows the report text (output of "Compose digest").

### 3.3 `medium-digest` (n8n) — from `medium-digest-project/`

- **What it does**: on demand, finds "Medium" emails from the last 7 days in the user's Gmail, extracts article links, fetches full text via the reader service (Freedium), summarizes with an LLM, posts a report to Slack.
- **Connectors**: Google (Nango; Gmail read-only) · Slack (Nango; bot token + channel).
- **Shared (owner-provided)**: OpenAI-compatible API key → one shared n8n `openAiApi` credential; reader service URL + token → one shared n8n `httpHeaderAuth` credential.
- **User settings**: Slack channel; (optional) model, default `gpt-4o-mini`.
- **Template fixes**: cap to 5 newest articles (`.slice(0, 100)` → `.slice(0, 5)` in "Extract article links"); reader HTTP node sends `Authorization: Bearer <token>` via credential; shorter HTTP timeouts (reader 60 s, LLM 60 s). Typical runs take 1–3 min, but a worst case can exceed Starter's 5-min limit → Pro recommended. Run-now webhook added.
- **Deploy job**: credentials (`gmailOAuth2`, `slackApi`; shared ones reused) → inject config (reader URL, channel, model) → create → publish.
- **Try it / results**: Run now → weekly report in Slack (or an "empty report" if the inbox has no Medium mail); demo shows report text (output of "Build Medium weekly report").

### 3.4 `github-merge-slack` (Make, via Make Bridge) — from `GitHub 合并提交 Diff 通知前端.blueprint.json`

- **What it does**: watches a GitHub repo for merged pull requests, fetches the merge commit diff, posts it to Slack.
- **Connectors**: GitHub + Slack, connected **inside Make's popup** (Make holds those tokens).
- **User settings** (entered in the Bridge wizard): repo owner, repo name, Slack channel.
- **One-time setup in Make** (done during implementation with the owner's account): add a filter between the trigger and the API call (merged = true **and** merged within the last 20 min, so later updates to an old merged PR don't re-post); turn hard-coded repo/channel into template inputs; trigger starts "from now on"; schedule every 15 min; save as a **Bridge template**; create Bridge app key (key ID + secret).
- **Availability check**: at startup / in admin setup check, call the Bridge API; if Bridge isn't enabled → card shows "Deploy unavailable".
- **Deploy flow** (Bridge portal API at `https://us2.make.com/portal/api/bridge/...`, each call authorized with a 2-minute JWT `{sub: <username>, jti}` signed with the Bridge secret — per-user sandbox):
  1. `POST /integrations/init/{templateId}` with `redirectUri`, `prefill`, `allowReusingComponents: true`, scenario name → `publicUrl`, `flow.id`.
  2. Frontend opens `publicUrl` in a popup; user connects GitHub + Slack and fills the settings.
  3. Make redirects to `/make/callback`; the backend queues a job that polls `GET /integrations/check-init/{flowId}` → scenario ID.
  4. `POST /integrations/{scenarioId}/activate`.
- **Try it / results**: merge a PR in the chosen repo, then Run now (`POST /integrations/{scenarioId}/run`); demo shows run history from `GET /scenarios/{scenarioId}/logs`.
- **Redeploy**: delete old scenario, run the init flow again (existing Make connections are offered for reuse). **Undeploy**: deactivate + `DELETE /integrations/{scenarioId}`.

### 3.5 `slack-meegle-bot` (Modal, shared) — from `slark-meegle-bot/`

- **What it does**: in Slack, `@bot <title> @owner` creates a Meegle card and replies in the thread with its link.
- **Shared deployment** (admin, once): Modal app runs the bot (Socket Mode) with the demo bot Slack app tokens and the team's Meegle plugin credentials; cards go to the team's demo Meegle space.
- **Small code patches** (opt-in via env vars, file behaviour unchanged otherwise):
  - `userMap.js`: when `USER_MAP_URL` is set, read/write Slack-user → Meegle-user-key mappings through the demo backend API instead of a local file (Modal containers have no persistent disk).
  - after a card is created, POST `{slackUserId, title, url}` to the demo backend so the tester sees it under Results.
- **Tester "Activate for me"**: requires Slack connection (Nango; the tester's Slack user ID comes from the OAuth response's `authed_user.id`) + Meegle user key (text box). Delete or 24 h expiry removes the mapping.
- **Try it / results**: invite the bot to a channel, `@bot Fix login error @me` → card + thread reply; demo lists the cards the bot created for that tester.
- **Runtime on Modal**: Node 20 image; long-running function (24 h max per run, restarts node after a crash) with one container at a time; a 10-minute schedule starts it whenever nothing is running or queued.

---

## 4. Shared services (on the demo server since P7; this table is the original Modal design)

| Service | Source | Modal setup |
|---|---|---|
| `workflow-demo` (the demo itself) | `app/` | ASGI web app + `run_job` function + `sweeper` (every 10 min) |
| `workflow-demo-medium-reader` | `demo-project/medium-digest-project/services/medium-reader` | `Image.from_dockerfile(..., add_python="3.12")` (team's Dockerfile, CloakBrowser base) + `@modal.web_server(8000)`; `API_TOKEN` from a Modal secret; 1 container, a few concurrent requests |
| `workflow-demo-slack-bot` | `demo-project/slark-meegle-bot` + patches | Node 20 image, `npm ci`; long-running function with bot + Meegle secrets |

The owner's OpenAI key and the reader token are given to each Medium digest deployment as its own n8n credentials (`openAiApi`, reader `httpHeaderAuth`), created at deploy and deleted at undeploy, so there is no shared state to bootstrap or rotate (changed in P3).

---

## 5. Data model (Postgres)

| Table | Key columns |
|---|---|
| `users` | `id`, `username` (unique), `created_at`, `last_login_at` |
| `connections` | `id`, `user_id`, `connector` (`slack` · `google` · `meegle_mcp_token` · `meegle_user_key`), `method` (`nango` · `manual`), `nango_integration`, `nango_connection_id`, `secret_ciphertext` (manual only, AES-GCM), `metadata` (Slack team/user, webhook channel, Google email), `status`, timestamps · unique (`user_id`, `connector`) |
| `deployments` | `id`, `user_id`, `workflow_id`, `status`, `inputs` (JSON), `platform_refs` (n8n workflow/credential IDs + webhook path · Make scenario/flow IDs · bot mapping), `error`, `deployed_at`, `expires_at`, timestamps · unique (`user_id`, `workflow_id`) |
| `deployment_events` | `deployment_id`, `at`, `type`, `message`, `details` — the timeline shown in the UI |
| `bot_events` | `slack_user_id`, `title`, `card_url`, `created_at` |
| `shared_resources` | `key`, `value` (JSON) — shared n8n credential IDs, reader URL, bot status |

**Deployment states**: `deploying` → `active` | `failed`; `active` → `redeploying` → `active` | `failed`; `active` → `stopping` → `stopped` (Delete or 24 h expiry); `awaiting_user` for the Make popup step. `unavailable` is computed (e.g. Make Bridge disabled).

---

## 6. Backend API

| Method & path | Purpose |
|---|---|
| `POST /api/auth/login` · `POST /api/auth/logout` · `GET /api/me` | Username + shared passcode; HTTP-only signed cookie (7 days) |
| `GET /api/workflows` · `GET /api/workflows/{id}` | Catalog with per-user readiness, deployment status, settings schema, "how to try" |
| `POST /api/connections/{connector}/session` | Create a Nango connect session (tags `end_user_id=<username>`) |
| `POST /api/connections/{connector}/complete` | Save `connectionId` after verifying its tags belong to this user |
| `PUT /api/connections/{connector}/secret` | Save a manual secret (Meegle token / user key), encrypted; never returned |
| `GET /api/connections` · `DELETE /api/connections/{connector}` | List (masked) / remove |
| `GET /api/slack/channels` | Channel picker (via the user's Slack token) |
| `POST /api/deployments/{workflowId}` | Deploy or redeploy with settings → job; Make returns the popup URL |
| `GET /api/deployments/{workflowId}` | Status + timeline |
| `POST /api/deployments/{workflowId}/run` | Run now |
| `GET /api/deployments/{workflowId}/runs` | Recent runs with result summaries (live from n8n / Make / bot events) |
| `DELETE /api/deployments/{workflowId}` | Stop and remove |
| `GET /make/callback` | Bridge redirect landing; finishes the Make deploy and closes the popup |
| `GET/POST /api/bot/user-map…` · `POST /api/bot/events` | For the shared bot (bearer token) |
| `POST /api/admin/login` · `GET /api/admin/overview` · `GET /api/admin/setup-check` · stop/reset actions | Admin page (separate admin passcode) |

---

## 7. Frontend

- **Sign in**: username + passcode.
- **Catalog**: one card per workflow — platform badge, connector chips (connected / missing), deployment status, "expires in".
- **Workflow page** (4 steps):
  1. **Connect** — rows per connector: Connect / Reconnect (Nango popup), text box (Meegle), or "connect in Make's popup" note.
  2. **Settings** — form generated from the catalog schema (channel picker, repo, sites…).
  3. **Deploy** — Deploy / Redeploy / Delete; live status and timeline; "expires in 23 h".
  4. **Try it** — instructions, **Run now**, recent runs with result text, links to Slack channel / Google Sheet.
- **Admin**: users, deployments (force stop), setup check (each platform reachable, n8n features, Make Bridge enabled, Nango integrations, OpenAI key, reader health, bot running).

---

## 8. Platform adapters

All adapters implement: `check_available()`, `deploy(ctx)`, `undeploy(ctx)`, `run_now(ctx)`, `recent_runs(ctx)`. A **fake adapter** set (`DEMO_FAKE_PLATFORMS=1`) makes the whole UI work without any credentials — used for development until real keys arrive and for E2E tests.

**Nango**: connect sessions; verify connection tags; fetch fresh credentials (`GET /connections/{id}?provider_config_key=…`); Slack raw response for `authed_user.id`. Integrations: `slack` (scopes `chat:write chat:write.public channels:read`), `google` (scopes Sheets, Drive file, Gmail read-only, email).

**n8n** (`X-N8N-API-KEY`):
- `GET /credentials/schema/{type}` at startup to validate payloads; `POST /credentials`; `DELETE /credentials/{id}`.
- `POST /workflows` (read-only fields stripped, strict `settings`), `POST /workflows/{id}/publish` with fallback to `/activate` on older versions; `DELETE /workflows/{id}`; everything the demo creates is named `[demo] …` / `demo · <user> · …` (no tags).
- Run now: each deployed workflow gets a Webhook trigger (unique path, header-auth credential); backend POSTs to it.
- Results: `GET /executions?workflowId=…&includeData=true` → status, timing, error, summary node output.

**Make Bridge**: JWT per request; init → popup → check-init → activate; run; logs; delete (section 3.4).

**Modal**: Python SDK with the owner's token to (re)deploy the two shared services from the admin page; bot activation is just the user-map record.

---

## 9. Security

- Slack/Google tokens live in Nango; the demo stores only connection IDs.
- Manual secrets (Meegle) encrypted with AES-GCM (`DATA_ENCRYPTION_KEY`), decrypted only inside deploy jobs, never logged or sent to the browser.
- Platform secrets in a Modal secret; nothing secret in git (`.env.example` only).
- Secrets go into platform **credentials**, never into node parameters, so they don't appear in exported workflows or execution data.
- Session cookie HTTP-only, `Secure`, `SameSite=Lax`; JSON-only API.
- Run-now webhooks and bot API protected by per-deployment / shared bearer tokens.
- Users never get access to n8n, Make or Modal; resources are named `demo · <username> · <workflow>`.

---

## 10. Repository layout

```
app/
  backend/            FastAPI app: auth, db (models + Alembic), catalog loader,
                      nango.py, crypto.py, adapters/ (n8n, make_bridge, modal_services, fake),
                      transforms/ (uptime, meegle_digest, medium_digest), jobs.py, routes/, tests/
  frontend/           React + Vite + TS
catalog/
  uptime-monitor/       catalog.yaml, workflow.json (fixed template)
  meegle-daily-digest/  catalog.yaml, workflow.json (compiled + fixed)
  medium-digest/        catalog.yaml, workflow.json (fixed)
  github-merge-slack/   catalog.yaml, make-setup.md (Bridge template steps)
  slack-meegle-bot/     catalog.yaml
services/
  medium-reader/modal_app.py      wraps the team's reader service
  slack-meegle-bot/modal_app.py   wraps the team's bot + patches
deploy/modal_app.py               demo web app, jobs, sweeper
scripts/                          compile_n8n_sdk.mjs, setup_check.py
docs/                             implementation-plan.md, setup-guide.md
demo-project/                     the team's originals (unchanged)
```

---

## 11. Configuration (supplied by the owner after implementation)

| Area | Settings |
|---|---|
| Demo | `DEMO_PASSCODE`, `ADMIN_PASSCODE`, `SESSION_SECRET`, `DATA_ENCRYPTION_KEY`, `PUBLIC_BASE_URL`, `MAX_USERS=10`, `DEPLOYMENT_TTL_HOURS=24` |
| Database | `DATABASE_URL` (the Postgres container on the server) |
| Nango | `NANGO_SECRET_KEY`, integration keys |
| Google (External OAuth client, Testing) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` (also needed for n8n Google credentials) |
| Slack connect app | client ID / secret (configured in Nango) |
| n8n | `N8N_BASE_URL` (`http://n8n:5678`, same server), `N8N_API_KEY` (created by `deploy/aws/setup_n8n.py`) |
| Make | `MAKE_ZONE=us2.make.com`, `MAKE_TEAM_ID` (optional), `MAKE_BRIDGE_KEY_ID`, `MAKE_BRIDGE_SECRET`, `MAKE_BRIDGE_TEMPLATE_ID` (Bridge API only) |
| Server | `deploy/aws/.env`: hostnames, Postgres passwords, `N8N_ENCRYPTION_KEY`, `N8N_RUNNERS_AUTH_TOKEN`, `N8N_VERSION` |
| LLM | `OPENAI_API_KEY`, optional `OPENAI_BASE_URL` (testers pick the model) |
| Reader | `READER_API_TOKEN` (generated), `FREEDIUM_BASE_URL` |
| Slack bot | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `MEEGLE_PLUGIN_ID`, `MEEGLE_PLUGIN_SECRET`, `MEEGLE_PROJECT_KEY`, `MEEGLE_SIMPLE_NAME`, `MEEGLE_WORK_ITEM_TYPE_KEY`, `MEEGLE_USER_KEY`, `BOT_API_TOKEN` |

---

## 12. Testing

- **Unit**: auth, crypto, state machine, catalog validation, each transform (golden JSON: credentials wired, Gmail node removed, webhook trigger present, no secrets in node parameters).
- **Contract**: adapters against mocked Nango / n8n / Make Bridge / Modal responses (`respx`).
- **E2E**: Playwright against fake-platform mode — sign in → connect → settings → deploy → run → results → redeploy → delete → expiry.
- **Live checklist** (once credentials arrive): setup check green; each workflow deployed and tried end to end by a test user; 24 h expiry verified with a short TTL override.

---

## 13. Phases

| Phase | Deliverable | Done when |
|---|---|---|
| P0 Foundations | Repo layout, tooling, catalog files, fixed templates, Meegle SDK compiled to JSON, setup guide (Slack app manifest, Google Internal OAuth steps, Nango, Make Bridge, Modal, Neon) | Templates pass transform tests |
| P1 App skeleton | Backend (auth, DB, catalog API, state machine) + frontend (sign-in, catalog, workflow page) on fake adapters | Full click-through in fake mode |
| P2 Connections | Nango connect flow + manual secrets (encrypted) | Connect/reconnect/delete work (mocked Nango in tests) |
| P3 n8n | n8n adapter + 3 transforms + per-deployment credentials + Run now + results | Contract tests pass; fake-mode E2E |
| P4 Modal services | Reader and bot on Modal; bot patches; "Activate for me" | Services deployable via script; activation flow tested |
| P5 Make Bridge | Bridge adapter, availability check, popup + callback, run/logs/delete, `make-setup.md` | Contract tests pass; "unavailable" path works |
| P6 Lifecycle & admin | 24 h sweeper, redeploy, delete, admin page, setup check | E2E covers lifecycle |
| P7 Go live | Deploy to one AWS server (was Modal + Neon), plug in credentials, run live checklist | All live checks pass |

P0–P6 need no credentials (fake mode + mocked APIs). P7 starts when the owner provides them.

---

## 14. Risks and how they're handled

| Risk | Handling |
|---|---|
| Make Bridge not enabled on the owner's account | Card shows "Deploy unavailable" (agreed) |
| ~~n8n Starter stops runs after 5 min~~ | Resolved: self-hosted n8n has no run time limit (Medium digest still capped at 5 articles) |
| n8n version differences (publish vs activate) | Detect and fall back |
| Freedium mirror changes/blocks requests; Medium terms | Kept by owner decision; per-article failures are already handled by the workflow |
| Chromium (reader) on the server | `shm_size: 1gb`, `init: true` as in the team's compose file; t3.large (8 GB) + 4 GB swap |
| Slack bot app also running elsewhere would split events | Use a dedicated demo bot app (owner provides) |
| Google app External in "Testing" | Only listed test users can connect; "unverified app" notice; sign-ins end after 7 days (demo asks to reconnect); a Workspace admin may need to trust the client for Gmail |
| Nango free plan = 10 connections | 10 users × (Slack + Google) needs Pay-as-you-go |
| OpenAI usage cost per Medium run | Capped articles; owner's key |

---

## 15. Needed from the owner at go-live (P7)

1. Demo Slack app for the Connect popup (scopes in §8) and the bot app (Socket Mode; not running elsewhere) — manifests in `docs/setup-guide.md`.
2. Google Cloud **External** OAuth client (Web) in **Testing**, with every tester added as a test user — setup guide provided.
3. Nango account (Pay-as-you-go) + secret key.
4. Make API token, team ID, Bridge key ID + secret (and Bridge enabled).
5. AWS account for the server (`pond-new`; EC2 in us-west-2). n8n, the database and the shared services run there — no n8n Cloud, Modal or Neon accounts needed.
6. OpenAI-compatible API key.
7. Meegle: team plugin credentials for the shared bot; testers bring their own MCP tokens.
8. Shared passcode and admin passcode.

---

## 16. Out of scope

- Zapier (no Zapier workflow in this set) and Dify.
- Real user accounts / SSO, billing, multi-tenant isolation beyond naming and per-user records.
- Slack testers outside the company workspace (would need Slack public distribution).
- Production hardening (rate limiting beyond the 10-user cap, HA, backups) and licensing review for production use of n8n / Make / Freedium.
