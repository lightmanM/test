# Setup Guide (owner)

Everything the owner creates before go-live (phase P7). Each section ends with the settings it
produces; they all go into `deploy/production.env` (see §10). Nothing here is committed to git.

## 1. Slack — "Connect Slack" app (used through Nango)

Used for every tester's **Connect Slack** popup. Create at <https://api.slack.com/apps> →
**Create New App → From an app manifest** → pick your workspace → paste:

```yaml
display_information:
  name: Workflow Demo
features:
  bot_user:
    display_name: Workflow Demo
    always_online: false
oauth_config:
  redirect_urls:
    - https://api.nango.dev/oauth/callback
  scopes:
    bot:
      - chat:write
      - chat:write.public
      - channels:read
settings:
  org_deploy_enabled: false
  socket_mode_enabled: false
  token_rotation_enabled: false
```

- Keep **token rotation off** (bot tokens then never expire; rotation can't be turned off later).
- Testers outside this workspace would need *Manage Distribution → public distribution* (out of scope).
- If you reuse an existing app instead, add the redirect URL and scopes above and reinstall it.

Produces: Slack **Client ID**, **Client Secret** (entered in Nango, §3).

## 2. Slack — shared bot app ("Slack → Meegle card bot")

One bot for all testers, running on the demo server in Socket Mode. **It must not also run anywhere else**
(Slack would split messages between the copies). Manifest:

```yaml
display_information:
  name: Meegle Card Bot (demo)
features:
  bot_user:
    display_name: meegle-bot
    always_online: true
  app_home:
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
  slash_commands:
    - command: /meegle-bind
      description: Link your Meegle account
      usage_hint: <your Meegle user_key>
      should_escape: false
oauth_config:
  scopes:
    bot:
      - app_mentions:read
      - chat:write
      - commands
settings:
  event_subscriptions:
    bot_events:
      - app_mention
  interactivity:
    is_enabled: false
  socket_mode_enabled: true
  token_rotation_enabled: false
```

Then: **Basic Information → App-Level Tokens → Generate** with scope `connections:write`;
**Install App** to the workspace.

Produces: `SLACK_BOT_TOKEN` (`xoxb-…`), `SLACK_APP_TOKEN` (`xapp-…`).

## 3. Google Cloud — External OAuth client in "Testing"

Used by Nango for **Connect Google**, and by n8n to refresh Google tokens. The testers' accounts
are on two Workspace domains, so the app is **External** (an Internal app covers one organization
only) and stays in **Testing** (Gmail read is a restricted scope; verification isn't worth it for a
demo).

1. <https://console.cloud.google.com> → create (or pick) a project. Any Google account can own it.
2. **APIs & Services → Library**: enable *Google Sheets API*, *Google Drive API*, *Gmail API*.
3. **Google Auth Platform → Branding**: app name "Workflow Demo"; support email.
4. **Audience**: user type **External**; publishing status **Testing** (do *not* publish).
   **Test users → Add users**: every tester's Google account, one by one (no domains or wildcards;
   up to 100). The list lives only in the Cloud console — it isn't kept in this public repo.
5. **Data access**: scopes `openid`, `.../auth/userinfo.email`, `.../auth/spreadsheets`,
   `.../auth/drive.file`, `.../auth/gmail.readonly`.
6. **Clients → Create client**: type **Web application**; authorized redirect URI
   `https://api.nango.dev/oauth/callback`.

Produces: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

What testers see and what to expect:
- Only listed accounts can connect; anyone else gets "access denied". Add a new tester before
  they try.
- Google shows a "hasn't verified this app" notice before its consent screen; testers continue.
- Every sign-in ends **7 days** after consent. The demo then says the Google connection has expired
  and asks to reconnect (deployments last 24 h, so this only affects later deploys).
- A Workspace admin can block unverified apps from reading Gmail. Connect one tester first; if
  Google refuses, ask the admin to trust the client ID (Admin console → Security → API controls).

## 4. Nango

1. Create an account at <https://app.nango.dev> (Pay-as-you-go plan for more than 10 connections).
2. **Integrations → Configure new integration**:
   - **Slack** — integration ID `slack`; client ID/secret from §1; scopes
     `chat:write,chat:write.public,channels:read`.
   - **Google** — integration ID `google`; client ID/secret from §3; scopes from §3.
3. **Environment settings** → copy the secret key.

Produces: `NANGO_SECRET_KEY` (integration IDs default to `slack` and `google`).

## 5. n8n (self-hosted on the demo server)

Nothing to buy or sign up for: n8n Community Edition runs on the AWS server next to the demo
(`deploy/aws/compose.yml`; the public API is in every self-hosted edition, and there is no run
time limit). `deploy/aws/setup_n8n.py` creates the owner account and the demo's API key
(`docs/go-live.md` §4). Code nodes run in a separate `n8nio/runners` container of the same version.

Produces: `N8N_BASE_URL=http://n8n:5678` (internal address), `N8N_API_KEY`. The editor is at
`https://<N8N_HOST>` for the owner.

## 6. Make

> **Make discontinued Bridge** (<https://f.make.com/bridge>), so this section can't be completed today. The hosted
> demo switches the workflow off with `DISABLED_WORKFLOWS=github-merge-slack`; remove that line once Make offers
> a replacement and the settings below exist.

1. Team ID: the number in the team URL (`…/team/<id>/…`) — only needed if the Bridge template
   lives in a specific team.
2. Bridge template and application key: follow `catalog/github-merge-slack/make-setup.md`.
   No Bridge on the account → the workflow shows "Deploy unavailable"; nothing else to do.

The demo only talks to the Bridge API (no Make API token needed). Produces: `MAKE_TEAM_ID`
(optional), `MAKE_BRIDGE_TEMPLATE_ID`, `MAKE_BRIDGE_KEY_ID`, `MAKE_BRIDGE_SECRET`
(`MAKE_ZONE` = `us2.make.com`).

## 7. AWS (the server)

1. An AWS CLI profile for the account that pays (here `pond-new`) with EC2 rights (instances,
   security groups, key pairs, Elastic IPs) and `ssm:GetParameter` (to find the Ubuntu image).
2. Free On-Demand vCPU quota for one 2-vCPU instance in the region (`pond-new`'s us-east-2 is full,
   so the script uses us-west-2).

`deploy/aws/provision.sh` creates the server; Docker Compose on it runs the demo, n8n, the Medium
reader, the Slack bot and Postgres (`docs/go-live.md`). Roughly $65/month at list price (t3.large,
40 GB disk, Elastic IP); stop the instance to pause it.

## 8. Database

Nothing to set up: Postgres runs on the server (`postgres` service), with one database for the
demo and one for n8n, created on first start by `deploy/aws/postgres-init.sh`.

Produces: `DATABASE_URL=postgresql://demo:<DEMO_DB_PASSWORD>@postgres:5432/workflow_demo`.

## 9. AI key and Meegle

- **OpenAI-compatible key** for the Medium digest: `OPENAI_API_KEY` (optional `OPENAI_BASE_URL`;
  testers pick the model, default `gpt-4o-mini`).
- **Meegle, shared bot** (see `demo-project/slark-meegle-bot/README.md` for where each comes from):
  `MEEGLE_PLUGIN_ID`, `MEEGLE_PLUGIN_SECRET`, `MEEGLE_PROJECT_KEY`, `MEEGLE_SIMPLE_NAME`,
  `MEEGLE_WORK_ITEM_TYPE_KEY`, `MEEGLE_USER_KEY` (service account), optional `MEEGLE_ROLE_KEY`.
- **Meegle, testers**: each tester enters their own MCP token (from a Meegle admin) in the demo.

## 10. Demo configuration

All values above, plus these generated ones, go into `deploy/production.env` (template:
`deploy/production.env.example`; server-side values in `deploy/aws/.env`; step-by-step:
`docs/go-live.md`):

| Setting | Value |
|---|---|
| `DEMO_PASSCODE` | shared tester passcode (owner picks; a random one was generated) |
| `ADMIN_PASSCODE` | admin page passcode (owner picks; a random one was generated) |
| `SESSION_SECRET`, `DATA_ENCRYPTION_KEY`, `READER_API_TOKEN`, `BOT_API_TOKEN` | random; generated during P7 |
| `PUBLIC_BASE_URL` | `https://<DEMO_HOST>` (the sslip.io name from `provision.sh`) |
| `MAX_USERS` / `DEPLOYMENT_TTL_HOURS` | `10` / `24` |
