'use strict';

// The patched app_mention handler in demo mode, with Slack (bolt) and Meegle stubbed.
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');

test('a mention looks users up in parallel, creates the card, replies, and reports it', async (t) => {
  const requests = [];
  let inFlight = 0;
  let maxInFlight = 0;
  const server = http.createServer((req, res) => {
    inFlight += 1;
    maxInFlight = Math.max(maxInFlight, inFlight);
    let body = '';
    req.on('data', (chunk) => (body += chunk));
    req.on('end', () =>
      setTimeout(() => {
        inFlight -= 1;
        requests.push({ url: req.url, body });
        const keys = { '/map/U1': 'key-requester', '/map/U2': 'key-alice' };
        if (keys[req.url]) res.writeHead(200).end(JSON.stringify({ user_key: keys[req.url] }));
        else if (req.url === '/cards') res.writeHead(202).end('{}');
        else res.writeHead(404).end();
      }, 50),
    );
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${server.address().port}`;
  Object.assign(process.env, { USER_MAP_URL: `${base}/map`, CARD_EVENTS_URL: `${base}/cards`, BOT_API_TOKEN: 't' });

  const created = [];
  const meegle = path.join(process.env.BOT_DIR, 'src', 'meegle.js');
  require.cache[meegle] = {
    id: meegle,
    filename: meegle,
    loaded: true,
    exports: {
      createWorkItem: async (args) => (created.push(args), { id: 42, assignApplied: true }),
      cardUrl: (id) => `https://meegle.com/demo/story/${id}`,
    },
  };
  require(path.join(process.env.BOT_DIR, 'src', 'index.js'));
  const { handlers } = require(path.join(process.env.BOT_DIR, 'node_modules', '@slack', 'bolt'));
  await new Promise((resolve) => setImmediate(resolve)); // bot user id from auth.test

  const replies = [];
  await handlers.event.app_mention({
    event: { text: '<@UBOT> Fix login <@U2> <@U3>', user: 'U1', channel: 'C1', ts: '1.0' },
    client: { chat: { postMessage: async (message) => replies.push(message.text) } },
    context: { channelId: 'C1' },
  });
  await new Promise((resolve) => setTimeout(resolve, 200)); // the card report isn't awaited

  assert.equal(maxInFlight, 3); // requester + two assignees at once
  assert.deepEqual(created[0].assigneeUserKeys, ['key-alice']);
  assert.equal(created[0].requesterUserKey, 'key-requester');
  assert.match(replies[0], /已创建卡片/);
  assert.match(replies[0], /Activate for me/); // U3 isn't activated
  assert.doesNotMatch(replies[0], /meegle-bind/);
  const card = requests.find((r) => r.url === '/cards');
  assert.deepEqual(JSON.parse(card.body), {
    slack_user_id: 'U1',
    title: 'Fix login',
    url: 'https://meegle.com/demo/story/42',
  });
});
