'use strict';

// Patched bot modules with the demo backend configured (USER_MAP_URL / CARD_EVENTS_URL).
const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');

test('user map and card events go to the demo backend', async (t) => {
  const requests = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (chunk) => (body += chunk));
    req.on('end', () => {
      requests.push({ method: req.method, url: req.url, auth: req.headers.authorization, body });
      if (req.url === '/api/bot/user-map/U1') {
        res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ user_key: ' key-1 ' }));
      } else if (req.url === '/api/bot/user-map/UERR') {
        res.writeHead(500).end();
      } else if (req.url === '/api/bot/cards') {
        res.writeHead(202, { 'content-type': 'application/json' }).end('{}');
      } else {
        res.writeHead(404).end();
      }
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const base = `http://127.0.0.1:${server.address().port}`;

  process.env.USER_MAP_URL = `${base}/api/bot/user-map/`;
  process.env.CARD_EVENTS_URL = `${base}/api/bot/cards`;
  process.env.BOT_API_TOKEN = 'bot-token';
  const userMap = require(path.join(process.env.BOT_DIR, 'src', 'userMap.js'));
  const { reportCard } = require(path.join(process.env.BOT_DIR, 'src', 'demoEvents.js'));

  assert.equal(userMap.isRemote, true);
  assert.equal(await userMap.getMeegleUserKey('U1'), 'key-1');
  assert.equal(await userMap.getMeegleUserKey('UNKNOWN'), '');
  assert.equal(await userMap.getMeegleUserKey('UERR'), ''); // errors never break card creation

  await reportCard({ slackUserId: 'U1', title: 'Fix login', url: 'https://meegle.com/x/1' });
  const card = requests.find((r) => r.url === '/api/bot/cards');
  assert.equal(card.method, 'POST');
  assert.deepEqual(JSON.parse(card.body), { slack_user_id: 'U1', title: 'Fix login', url: 'https://meegle.com/x/1' });
  assert.ok(requests.every((r) => r.auth === 'Bearer bot-token'));
});
