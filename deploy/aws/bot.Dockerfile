# The team's Slack → Meegle bot with services/slack-meegle-bot/demo.patch applied (the patch only
# changes behaviour when USER_MAP_URL / CARD_EVENTS_URL are set). Build context: the repo root.

FROM node:20-bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends patch \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /bot
COPY demo-project/slark-meegle-bot/package.json demo-project/slark-meegle-bot/package-lock.json ./
RUN npm ci --omit=dev
COPY demo-project/slark-meegle-bot/src ./src
COPY services/slack-meegle-bot/demo.patch /tmp/demo.patch
RUN patch -p1 < /tmp/demo.patch && rm /tmp/demo.patch && chown -R node:node /bot
USER node
CMD ["node", "src/index.js"]
