# Go live (P7)

Everything the demo hosts runs on **one AWS server** (EC2 in the `pond-new` account, region
us-west-2) with Docker Compose: Caddy (HTTPS), the demo, n8n (+ its Code-node runner), the Medium
reader, the Slack bot and Postgres. Make, Slack, Google, Nango, OpenAI and Meegle stay where they
are. Account setup details: `docs/setup-guide.md`. Files: `deploy/aws/`.

The live instance's address is in `deploy/aws/.env` (`SERVER_IP`, `DEMO_HOST`, `N8N_HOST`; git-ignored —
this repo is public, so the address isn't written here).

## 1. Accounts and keys (owner)

- [ ] AWS: CLI profile `pond-new` with EC2 rights in us-west-2 — setup guide §7.
- [ ] Slack: the **Connect** app and the **bot** app (Socket Mode) — §1–2.
- [ ] Google Cloud **External** OAuth client in **Testing**, with every tester as a test user — §3
      (only Nango gets it: every Google call goes through Nango's proxy).
- [ ] Nango: `slack` and `google` integrations with those clients; secret key (with proxy access) — §4.
- [ ] Make: Bridge enabled; template from `catalog/github-merge-slack/make-setup.md`; Bridge key ID +
      secret; template ID — §6.
- [ ] OpenAI-compatible key; Meegle plugin credentials for the shared bot — §9.

n8n needs no account or plan: it runs on the server (§5).

## 2. The server

```bash
AWS_PROFILE=pond-new deploy/aws/provision.sh     # prints SERVER_IP, DEMO_HOST, N8N_HOST
```

Creates (or shows) everything named `workflow-demo`: a t3.large Ubuntu 24.04 instance (40 GB,
encrypted), an Elastic IP, a security group (80/443 open; SSH only from the machine that ran the
script — run it again after your IP changes) and the SSH key `~/.ssh/workflow-demo.pem`. The first
boot installs Docker (a few minutes). The hostnames are sslip.io names of the IP, so no DNS setup is
needed; Caddy gets their certificates.

## 3. Settings (all git-ignored)

- `deploy/aws/.env` from `deploy/aws/.env.example`: the three values from step 2, random passwords
  and tokens, `N8N_VERSION`. Keep `N8N_ENCRYPTION_KEY` stable (it encrypts n8n's credentials).
- `deploy/production.env` from `deploy/production.env.example`: `PUBLIC_BASE_URL=https://<DEMO_HOST>`,
  `DATABASE_URL` with `DEMO_DB_PASSWORD`, passcodes, the generated secrets and the account values
  from step 1. `READER_API_TOKEN` must equal the one in `deploy/aws/.env` (deploy.sh checks).
  Keep `RELAY_BASE_URL=http://demo:8000`: n8n calls Google through the demo's relay at that internal
  address (Caddy doesn't offer the relay publicly).
- `deploy/aws/bot.env` from `deploy/aws/bot.env.example` (or the team's
  `demo-project/slark-meegle-bot/.env`) plus the same `BOT_API_TOKEN` as `deploy/production.env`.

```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"                     # passwords, tokens
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"   # DATA_ENCRYPTION_KEY
```

Keep `DATA_ENCRYPTION_KEY` stable: changing it makes saved Meegle tokens unreadable (testers re-enter them).

## 4. Deploy

```bash
deploy/aws/deploy.sh                                          # copy, build, start
N8N_OWNER_EMAIL=<you> python3 deploy/aws/setup_n8n.py         # n8n owner + API key → production.env
deploy/aws/deploy.sh                                          # the demo picks up N8N_API_KEY
```

Run `setup_n8n.py` from the machine that ran `deploy.sh`: Caddy lets only that IP reach n8n's public
address at all, so nobody else can claim the fresh instance (testers never need it; the demo talks to
n8n inside the server). The bot is deployed whenever
`deploy/aws/bot.env` exists — create it only once no other copy of the bot runs anywhere
(`deploy.sh --without-bot` stops it again).

The demo applies its database migrations on start. The n8n owner login is saved in
`deploy/aws/n8n-owner.env` (stays on your machine). On macOS with the python.org Python, run
`setup_n8n.py` with `SSL_CERT_FILE` pointing at a CA bundle (e.g. certifi's).

- [ ] Make Bridge application: allowed redirect URL `<PUBLIC_BASE_URL>/make/callback` (any query string).

## 5. Setup check

Admin page (`/admin`) → **Run setup check**: every line ✓ and every workflow available
("Google relay" ✓ means the demo answers at `RELAY_BASE_URL`).

## 6. Live checklist (one test user, then a second one)

- [ ] **Uptime monitor**: connect Google + Slack, pick a channel, deploy → "Your uptime spreadsheet" opens;
      Run now → Slack alert for the failing site, rows in the Log tab, result lines in the demo.
- [ ] **Meegle digest**: save the MCP token and project settings, deploy, Run now → report in Slack and in the demo.
- [ ] **Medium digest**: deploy, Run now → report (or the empty report) in Slack and in the demo within ~3 min.
- [ ] **GitHub merge → Slack**: Deploy → Make popup (GitHub, Slack, repo, channel) → Active; merge a PR,
      Run now → diff in Slack, run listed. Check the run's details look right (log field names are inferred).
- [ ] **Slack bot**: Activate for me; `@bot Fix login page error @you` → card + thread reply; card listed.
- [ ] Redeploy and delete one of each; n8n and Make keep nothing behind (Run sweeper now removes nothing).
- [ ] n8n holds no Google token: its Credentials page lists each Google slot (`demo · <user> · <workflow> ·
      google`) as Header Auth (the relay key), and Nango's Logs show the Sheets/Gmail calls.
- [ ] Two users deploy the same workflow independently.
- [ ] Expiry: set `DEPLOYMENT_TTL_HOURS=0.05` in `deploy/production.env` and run `deploy/aws/deploy.sh`;
      deploy a workflow, wait 3 minutes, then admin page → **Run sweeper now** (it also runs every
      10 minutes) → Stopped "after the demo time limit". Set it back to `24` and deploy again.

## 7. Hand over

- [ ] Share the URL and the tester passcode; testers need a Google account on the test-user list
      (setup guide §3) and the Slack workspace.
- [ ] Mark P7 done in `docs/progress.md`.

## Operations

```bash
ssh -i ~/.ssh/workflow-demo.pem ubuntu@<SERVER_IP>
cd /opt/workflow-demo/deploy/aws
docker compose --profile bot ps                       # status of every service
docker compose --profile bot logs -f demo             # also: n8n, n8n-runner, reader, bot, caddy, postgres
docker compose exec -T postgres pg_dumpall -U postgres > backup.sql   # database backup
```

- **Change a setting**: edit the file on your machine, run `deploy/aws/deploy.sh` (containers whose
  settings or image changed are recreated; `up.sh` on the server handles rebuilt images).
- **Keep the settings files safe**: `deploy/production.env`, `deploy/aws/.env`, `deploy/aws/bot.env` and
  `deploy/aws/n8n-owner.env` exist only on your machine (and, except the last, on the server). Store
  copies in a password manager: `DATA_ENCRYPTION_KEY` and `N8N_ENCRYPTION_KEY` can't be recovered, and
  without them saved Meegle tokens and n8n credentials are unreadable. Never run `docker compose down -v`
  (it deletes the database volumes).
- **Upgrade n8n**: `N8N_VERSION` in `deploy/aws/.env` (the runner follows), then deploy.
- **Google through Nango (from 2026-10-06)**: on a server set up before then, add
  `RELAY_BASE_URL=http://demo:8000` to `deploy/production.env` (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
  are no longer used and can go), run `deploy/aws/deploy.sh`, then the setup check. Uptime and Medium
  deployments made before keep their old n8n Google credential until they're redeployed or expire.
- **n8n editor**: `https://<N8N_HOST>`, owner login in `deploy/aws/n8n-owner.env`. Reachable only from the IP
  that last ran `deploy.sh` (everyone else gets 403); after your IP changes, run `deploy.sh` again.
- **Certificates**: sslip.io names share Let's Encrypt's per-domain limits; if a fresh server can't get
  a certificate, point a DNS name (e.g. in Cloudflare) at the Elastic IP and use it as `DEMO_HOST`/`N8N_HOST`.
- **Pause costs**: `aws ec2 stop-instances --profile pond-new --region us-west-2 --instance-ids <id>`;
  the Elastic IP keeps the address and the volume keeps the data. Start it again the same way.
