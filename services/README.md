# Shared services on Modal

Two of the team's services run once for every tester, under the owner's Modal account. The
team's code in `demo-project/` stays untouched; these folders only hold the Modal wrappers (and, for
the bot, a small opt-in patch).

| Folder | Runs | Used by |
|---|---|---|
| `medium-reader/` | the Freedium + CloakBrowser reader, from the team's Dockerfile, as a Modal web server | every Medium digest deployment on n8n (`POST /extract`) |
| `slack-meegle-bot/` | the Slack → Meegle bot (Socket Mode), Node 20, with `demo.patch` | testers who click **Activate for me** |

## Deploy (P7, with the owner's Modal token)

```bash
pip install modal && modal token set --token-id ... --token-secret ...

# Reader: generate a token, give it to both the reader and the demo (READER_API_TOKEN).
modal secret create workflow-demo-reader API_TOKEN=<token>
modal deploy services/medium-reader/modal_app.py           # prints the URL → demo READER_BASE_URL

# Bot: the demo bot Slack app (Socket Mode) + the team's Meegle plugin; BOT_API_TOKEN must match the demo's.
modal secret create workflow-demo-slack-bot \
  SLACK_BOT_TOKEN=xoxb-... SLACK_APP_TOKEN=xapp-... \
  MEEGLE_PLUGIN_ID=... MEEGLE_PLUGIN_SECRET=... MEEGLE_PROJECT_KEY=... MEEGLE_SIMPLE_NAME=... \
  MEEGLE_WORK_ITEM_TYPE_KEY=... MEEGLE_USER_KEY=... \
  USER_MAP_URL=https://<demo>/api/bot/user-map CARD_EVENTS_URL=https://<demo>/api/bot/cards \
  BOT_API_TOKEN=<token>
modal deploy services/slack-meegle-bot/modal_app.py         # starts within 10 minutes; picks up
                                                            # a new deploy/secret within an hour
```

`READER_MIN_CONTAINERS=1 modal deploy …` keeps one reader warm during a demo session (a cold
browser start can exceed n8n's 60 s per-article timeout).

## The bot patch

`slack-meegle-bot/demo.patch` changes nothing unless its environment variables are set:

- `USER_MAP_URL` + `BOT_API_TOKEN`: Slack-user → Meegle-user-key lookups go to the demo backend
  (`GET /api/bot/user-map/<slack user id>`), which answers for testers with an active activation.
  Modal containers have no persistent disk for `data/user-map.json`. `/meegle-bind` then points
  people to the demo site.
- `CARD_EVENTS_URL`: after creating a card the bot reports `{slack_user_id, title, url}` to the
  demo (`POST /api/bot/cards`, not awaited, so the Slack reply isn't delayed), which lists it under
  the tester's results.
- Mention handling looks the requester and all assignees up in parallel, and the "not bound"
  hint points to **Activate for me** instead of `/meegle-bind`.

`slack-meegle-bot/check.sh` applies the patch to a copy of the team's code and tests the patched
modules (CI runs it). If the team changes `src/index.js` or `src/userMap.js`, regenerate the
patch: copy their `src/`, re-apply the edits, and `git diff --no-index` the two copies.
