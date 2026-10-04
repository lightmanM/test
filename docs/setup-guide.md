# Setup Guide (owner)

Everything the owner creates before go-live (phase P7). Each section ends with the settings it
produces; they all go into the demo's Modal secret (see §10). Nothing here is committed to git.

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

One bot for all testers, running on Modal in Socket Mode. **It must not also run anywhere else**
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

## 3. Google Cloud — Internal OAuth client

Used by Nango for **Connect Google**, and by n8n to refresh Google tokens.

1. <https://console.cloud.google.com> → create (or pick) a project in the company organization.
2. **APIs & Services → Library**: enable *Google Sheets API*, *Google Drive API*, *Gmail API*.
3. **OAuth consent screen**: User type **Internal**; app name "Workflow Demo"; support email.
   Scopes: `openid`, `.../auth/userinfo.email`, `.../auth/spreadsheets`, `.../auth/drive.file`,
   `.../auth/gmail.readonly`.
4. **Credentials → Create credentials → OAuth client ID**: type **Web application**;
   authorized redirect URI `https://api.nango.dev/oauth/callback`.

Produces: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`. Only accounts in the company Google
Workspace can connect.

## 4. Nango

1. Create an account at <https://app.nango.dev> (Pay-as-you-go plan for more than 10 connections).
2. **Integrations → Configure new integration**:
   - **Slack** — integration ID `slack`; client ID/secret from §1; scopes
     `chat:write,chat:write.public,channels:read`.
   - **Google** — integration ID `google`; client ID/secret from §3; scopes from §3.
3. **Environment settings** → copy the secret key.

Produces: `NANGO_SECRET_KEY` (integration IDs default to `slack` and `google`).

## 5. n8n Cloud

1. Paid plan (the free trial has no API). Pro recommended: Starter stops any run after 5 minutes,
   which is tight for the Medium digest.
2. **Settings → n8n API → Create an API key**.

Produces: `N8N_BASE_URL` (e.g. `https://yourname.app.n8n.cloud`), `N8N_API_KEY`.

## 6. Make

1. **Profile → API access → Add token** with scopes `scenarios:read`, `scenarios:write`,
   `scenarios:run`, `connections:read`, `teams:read`, `organizations:read`.
2. Team ID: the number in the team URL (`…/team/<id>/…`).
3. Bridge template and application key: follow `catalog/github-merge-slack/make-setup.md`.
   No Bridge on the account → the workflow shows "Deploy unavailable"; nothing else to do.

Produces: `MAKE_API_TOKEN`, `MAKE_TEAM_ID`, `MAKE_BRIDGE_TEMPLATE_ID`, `MAKE_BRIDGE_KEY_ID`,
`MAKE_BRIDGE_SECRET` (`MAKE_ZONE` = `us2.make.com`).

## 7. Modal

1. Workspace → **Settings → API Tokens → New token** (or `modal token new`).

Produces: `MODAL_TOKEN_ID`, `MODAL_TOKEN_SECRET`. The demo, the Medium reader and the Slack bot
are deployed into this workspace.

## 8. Neon

1. Create a project at <https://neon.tech> (free tier is enough).
2. Copy the **pooled** connection string (`postgresql://…?sslmode=require`).

Produces: `DATABASE_URL`.

## 9. AI key and Meegle

- **OpenAI-compatible key** for the Medium digest: `OPENAI_API_KEY` (optional `OPENAI_BASE_URL`;
  testers pick the model, default `gpt-4o-mini`).
- **Meegle, shared bot** (see `demo-project/slark-meegle-bot/README.md` for where each comes from):
  `MEEGLE_PLUGIN_ID`, `MEEGLE_PLUGIN_SECRET`, `MEEGLE_PROJECT_KEY`, `MEEGLE_SIMPLE_NAME`,
  `MEEGLE_WORK_ITEM_TYPE_KEY`, `MEEGLE_USER_KEY` (service account), optional `MEEGLE_ROLE_KEY`.
- **Meegle, testers**: each tester enters their own MCP token (from a Meegle admin) in the demo.

## 10. Demo configuration

All values above, plus these generated ones, go into a Modal secret named `workflow-demo-app`
(template: `deploy/production.env.example`; step-by-step: `docs/go-live.md`):

| Setting | Value |
|---|---|
| `DEMO_PASSCODE` | shared tester passcode (owner picks) |
| `ADMIN_PASSCODE` | admin page passcode (owner picks) |
| `SESSION_SECRET`, `DATA_ENCRYPTION_KEY`, `READER_API_TOKEN`, `BOT_API_TOKEN` | random; generated during P7 |
| `PUBLIC_BASE_URL` | the demo's Modal URL |
| `MAX_USERS` / `DEPLOYMENT_TTL_HOURS` | `10` / `24` |
