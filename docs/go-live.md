# Go live (P7)

Everything runs under the owner's accounts. Steps 1–2 are the owner's (they need the accounts);
steps 3–7 can be done together in a session. Account setup details are in `docs/setup-guide.md`.

## 1. Accounts and keys (owner)

- [ ] Slack: the **Connect** app and the **bot** app (Socket Mode) from the manifests — setup guide §1–2.
- [ ] Google Cloud **Internal** OAuth client — §3.
- [ ] Nango: `slack` and `google` integrations with those clients; secret key — §4.
- [ ] n8n Cloud (paid plan, Pro recommended): base URL + API key — §5.
- [ ] Make: Bridge enabled; template from `catalog/github-merge-slack/make-setup.md`; Bridge key ID +
      secret; template ID — §6.
- [ ] Modal token — §7. Neon connection string — §8.
- [ ] OpenAI-compatible key; Meegle plugin credentials for the shared bot — §9.
- [ ] Passcodes for testers and the admin.

## 2. Generate the demo's own secrets

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"               # SESSION_SECRET, READER_API_TOKEN, BOT_API_TOKEN
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"   # DATA_ENCRYPTION_KEY
```

Keep `DATA_ENCRYPTION_KEY` stable: changing it makes saved Meegle tokens unreadable (testers re-enter them).

## 3. Shared services (`services/README.md`)

```bash
pip install modal && modal token set --token-id ... --token-secret ...
modal secret create workflow-demo-reader API_TOKEN=<READER_API_TOKEN>
modal deploy services/medium-reader/modal_app.py      # → READER_BASE_URL
```

## 4. The demo

```bash
cp deploy/production.env.example deploy/production.env   # fill in (git-ignored)
(cd app/frontend && npm ci && npm run build)
modal secret create workflow-demo-app --from-dotenv deploy/production.env
modal run deploy/modal_app.py::migrate                    # creates the tables on Neon
modal deploy deploy/modal_app.py                          # → the web URL
```

Set `PUBLIC_BASE_URL` to the printed web URL (`modal secret create workflow-demo-app --force
--from-dotenv …`) and deploy again. Then:

- [ ] Make Bridge application: allowed redirect URL `<PUBLIC_BASE_URL>/make/callback` (any query string).
- [ ] Bot secret and deploy (`services/README.md`), with `USER_MAP_URL=<PUBLIC_BASE_URL>/api/bot/user-map`,
      `CARD_EVENTS_URL=<PUBLIC_BASE_URL>/api/bot/cards` and the same `BOT_API_TOKEN`.

## 5. Setup check

Admin page (`/admin`) → **Run setup check**: every line ✓ and every workflow available.

## 6. Live checklist (one test user, then a second one)

- [ ] **Uptime monitor**: connect Google + Slack, pick a channel, deploy → "Your uptime spreadsheet" opens;
      Run now → Slack alert for the failing site, rows in the Log tab, result lines in the demo.
- [ ] **Meegle digest**: save the MCP token and project settings, deploy, Run now → report in Slack and in the demo.
- [ ] **Medium digest**: deploy, Run now → report (or the empty report) in Slack and in the demo within ~3 min.
- [ ] **GitHub merge → Slack**: Deploy → Make popup (GitHub, Slack, repo, channel) → Active; merge a PR,
      Run now → diff in Slack, run listed. Check the run's details look right (log field names are inferred).
- [ ] **Slack bot**: Activate for me; `@bot Fix login page error @you` → card + thread reply; card listed.
- [ ] Redeploy and delete one of each; n8n and Make keep nothing behind (Run sweeper now reports nothing).
- [ ] Two users deploy the same workflow independently.
- [ ] Expiry: set `DEPLOYMENT_TTL_HOURS=0.05`, deploy, wait for the sweeper (≤10 min) → Stopped
      "after the demo time limit"; set it back to `24`.

## 7. Hand over

- [ ] Share the URL and the tester passcode; testers need a company Google account and the Slack workspace.
- [ ] Mark P7 done in `docs/progress.md`.
