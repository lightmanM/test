# Research Notes (verified platform facts)

Condensed findings from the feasibility research (Oct 2026). "Verified" = checked in
official source code or docs; others are from docs/search snippets and should be
re-checked when implementing. Check here before re-researching.

## n8n (deploy target for 3 workflows)
- **Public API can create OAuth2 credentials pre-filled with tokens** — `oauthTokenData` is added to the allowed schema for every OAuth2 credential type (`packages/cli/src/credentials-helper.ts`, `getCredentialsProperties`). Verified.
- Credential routes (verified, `public-api/v1/controllers/credentials.public.controller.ts`): `GET/POST /credentials`, `PATCH /credentials/{id}`, `DELETE`, `PUT /{id}/transfer`, `POST /{id}/test`, `GET /credentials/schema/{type}`. PATCH can write `oauthTokenData` from v2.7; send full `data` without `isPartialData`.
- Workflows: `POST /workflows` (strip read-only `id/active/tags/versionId/meta`; `settings` strict), `POST /workflows/{id}/publish` (v2.33+; `/activate` is a deprecated alias), `DELETE`. Requests with a body need `Content-Type: application/json` (v2.37+).
- Node credential reference: `"credentials": {"<type>": {"id": "...", "name": "..."}}`. Missing IDs → save fails (if sharing licensed) or run-time error.
- n8n refreshes OAuth2 tokens itself on 401 using `refresh_token` + the credential's `clientId/clientSecret` (Google refresh tokens don't rotate → safe).
- Slack node: `authentication: accessToken` → `slackApi {accessToken}`; Gmail: `gmailOAuth2`; Sheets: `googleSheetsOAuth2Api`; LLM HTTP node: `openAiApi`; generic headers: `httpHeaderAuth {name, value}`.
- No "run workflow" API → add a Webhook trigger (header auth) for "Run now"; results via `GET /executions?workflowId=…&includeData=true`.
- Cloud: API not on the free trial; max execution time Starter 5 min, Pro 40 min; no active-workflow limits since Aug 2025 (billed by executions; Starter 2,500/month); Python Code node on Cloud cannot import any library; `$env` blocked in nodes.
- License FAQ (`n8n-docs/docs/n8n-community-license/license-faq.md`, verified): end users may connect their own accounts to pre-built workflows as long as they can't build/modify workflow logic; "automation-as-a-service" / competing automation products are not allowed. Applies to self-hosted; n8n Cloud has its own terms.
- Workflow SDK: `@n8n/workflow-sdk` (npm, 0.34.2) — `workflow(...).toJSON()` compiles SDK code to importable JSON. Verified on the Meegle digest.

- Self-hosted (chosen at P7): the public API is in every self-hosted edition (only the n8n Cloud free trial lacks it); Community Edition is free under the Sustainable Use License (internal business use); no run time limit. Docker: `docker.n8n.io/n8nio/n8n:<v>` + `n8nio/runners:<same v>` sidecar for Code nodes (`N8N_RUNNERS_MODE=external`, shared `N8N_RUNNERS_AUTH_TOKEN`, broker `http://n8n:5679`; internal mode is deprecated in 3.0) — n8n-io/n8n-hosting `docker-compose/withPostgres`. Stable 2.41.6 on 2026-10-04.
- Headless first-run (verified in n8n@2.41.6 source): `POST /rest/owner/setup {email, firstName, lastName, password}` (password 8–64 chars with a digit and an uppercase letter) → session cookie; `GET /rest/api-keys/scopes`; `POST /rest/api-keys {label, scopes, expiresAt: null}` → `rawApiKey`. Used by `deploy/aws/setup_n8n.py`.

## AWS (hosting since P7)
- `pond-new` (account 4326…): us-east-2's On-Demand standard vCPU quota (8) is used by four t2.medium backends; the user can't read or raise quotas (`servicequotas:*` denied by a permissions boundary). us-west-2 had nothing running, so the server is there.
- Let's Encrypt issues certificates for sslip.io names (`demo-1-2-3-4.sslip.io`) — Caddy obtained both on the first start.

## Make (GitHub → Slack workflow)
- **OAuth connections can't be created with injected tokens**: Make's own guide says tokens "are **not** injectable — there is no way to skip the consent" (`integromat/make-skills`, `http-fallback-shells.md`). Verified.
- **Make Bridge** (verified, `integromat/bridge-examples`): portal API at `https://<zone>.make.com/portal/api/bridge/...`; every call carries a JWT `{sub: <end user id>, jti}` signed with the Bridge secret (HS256, `kid` = key ID, ~2 min expiry). Endpoints: `POST /integrations/init/{templateId}` (body: `redirectUri`, `prefill{hard,soft}`, `allowReusingComponents`, `autoActivate`, `autoFinalize`, `scenario{name,enable}`) → `publicUrl` + `flow.id`; `GET /integrations/check-init/{flowId}` → scenario IDs; `POST /integrations/{scenarioId}/activate|deactivate|run`; `DELETE /integrations/{scenarioId}`; `GET /scenarios/{id}/logs`. End users connect accounts "without logging into Make". Templates: Make UI → Templates → "+ New Bridge template" (some accounts don't show it).
- Other Make API facts: blueprint connection refs `flow[i].parameters.__IMTCONN__`; Keys API (`POST /keys`, type `apikeyauth`, `PATCH /keys/{id}`) for HTTP modules; external credential requests are Enterprise/Partner only; Make terms limit use to internal purposes (partner agreement for production).
- The team's blueprint: zone `us2.make.com`; modules `github:newPullRequest` (choose `updated`), `github:makeRestApiCall`, `slack:CreateMessage`; no merged-PR filter (fails for unmerged PRs; Make disables a scenario after 3 errors).

## Zapier (not in scope now)
- No API accepts third-party OAuth tokens; apps connect only via Zapier's popup. Workflow API (`/v2/zaps`, `/v2/authentications`) requires a **public** Zapier integration; White Label (embedded, no Zapier accounts) is early access. Zapier SDK connect URLs are bound to the logged-in Zapier user. Storage by Zapier has a REST API (UUID secret). ToS forbid hosting Zaps as a service for others.

## Nango (Slack + Google tokens)
- No official Python SDK ("Coming soon. Use the REST API") — verified in `NangoHQ/nango` docs source.
- Flow: `POST /connect/sessions` (`tags: {end_user_id, …}`, `allowed_integrations`) → frontend `@nangohq/frontend` `openConnectUI` → `connect` event `{connectionId, providerConfigKey}` → verify with `GET /connections/{id}?provider_config_key=…` (returns fresh `credentials.access_token`, `expires_at`, `raw`). Proxy: `/proxy/...` with `Connection-Id` + `Provider-Config-Key`.
- Refreshes every token at least once every 24 h (verified, `docs/guides/auth/token-refreshing.mdx`). Never hand rotating refresh tokens to another system.
- Free plan: 10 connections, 2 environments (verified, `plans/definitions.ts`); Pay-as-you-go $50/month (credits), $0.29/connection.
- Providers: `slack`, `google`, `google-mail`, `google-sheet` exist; **Meegle/Feishu/Lark not supported**. Own OAuth app required to export tokens. Cloud OAuth callback: `https://api.nango.dev/oauth/callback`.
- A refresh the provider refuses (e.g. Google `invalid_grant` after 7 days) → `GET /connections/{id}` answers `{"error": {"code": "invalid_credentials", …}}`, status taken from the refresh error (400 for Google); the only fix is reconnecting. Verified in `NangoHQ/nango` `packages/server/lib/controllers/connection/connectionId/getConnection.ts`.

## Modal (original hosting plan; replaced by AWS at P7)
- Deploy: `modal deploy` / `app.deploy()` (Python SDK only); `modal.Secret.objects.create`, `.update`; environments; `modal app stop`; `app rollover` to restart after secret changes.
- `Image.from_dockerfile(path, add_python=...)` and `@modal.web_server(port)` exist (verified in modal 1.6.1) → can run the team's Node/Chromium reader service.
- Functions max 24 h per run; schedules via `modal.Period` / `modal.Cron`; containers have no persistent disk (use DB/Volume).

## Slack
- Bot tokens (`xoxb`) never expire unless token rotation is enabled (can't be turned off once on).
- Socket Mode: events are spread across all open connections of one app → several copies of a bot on one app don't work; hence one shared bot deployment.
- OAuth with `incoming-webhook` scope returns `incoming_webhook.url` (channel chosen by the user); `authed_user.id` identifies the installing user.

## Google
- Internal OAuth app: only the accounts of the one Cloud organization the project belongs to, no test-user cap, no 7-day token expiry. Gmail read scopes are "restricted" (matters only for External apps).
- External + "Testing" (chosen): up to 100 test users, added one by one (no domain wildcard); an "unverified app" notice before consent; consent and refresh tokens end 7 days after consent; other accounts get "access denied". External + "In production" unverified: any account, a stronger warning, 100 users over the project's lifetime. Workspace admins can still block unverified apps from Gmail. Source: Google Cloud help "Manage App Audience" / "Unverified apps".
- n8n Cloud's "Managed OAuth2" (Sign in with Google) uses n8n's own verified Google app; it only works inside the n8n editor for a logged-in n8n user and its client secret isn't exposed, so the demo (API-created credentials, testers aren't n8n users) can't use it.

## Meegle
- OpenAPI: `POST /open_api/authen/plugin_token {plugin_id, plugin_secret, type}` → token (~2 h); calls send `X-PLUGIN-TOKEN` + `X-USER-KEY`.
- MCP server `https://meegle.com/mcp_server/v1`, header `X-Mcp-Token` (used by the daily digest; tokens issued by a Meegle admin). An OAuth (dynamic client registration + PKCE) flow also exists but isn't used.

## Dify (not in scope now)
- Self-hosted with `ADMIN_API_KEY_ENABLE` + `ADMIN_API_KEY` (+ `X-WORKSPACE-ID`) allows server-to-server console API calls (import DSL, publish, API keys) — verified in `api/extensions/ext_login.py`. OAuth credentials added via API get `expires_at=-1` and are never refreshed (verified). No per-end-user tool auth. License: single workspace as a backend is allowed; multiple workspaces need a commercial license.

## Workflow evaluation notes (team's originals)
- Uptime (n8n template 2327): "Update Site Status" mis-mapped (status never updates → repeated alerts); Gmail node unconnected; runs every minute.
- Meegle digest: SDK code, compiles to 10 nodes; Slack post runs even with an empty webhook URL.
- Medium digest: clean (no secrets); manual trigger only; reader service = CloakBrowser + Freedium mirror (Docker, ~1 GB shm); already slices to 100 articles.
- Slack bot: Node 20, `@slack/bolt` Socket Mode; needs bot + app-level tokens and Meegle plugin credentials; user map in a local JSON file.
