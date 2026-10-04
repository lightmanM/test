'use strict';

// Without the demo variables the patched bot behaves exactly like the original (file-based map).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

test('file-based user map is unchanged', async () => {
  delete process.env.USER_MAP_URL;
  delete process.env.CARD_EVENTS_URL;
  process.env.USER_MAP_FILE = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'bot-')), 'map.json');
  const userMap = require(path.join(process.env.BOT_DIR, 'src', 'userMap.js'));
  const { reportCard } = require(path.join(process.env.BOT_DIR, 'src', 'demoEvents.js'));

  assert.equal(userMap.isRemote, false);
  assert.equal(userMap.getMeegleUserKey('U1'), ''); // synchronous, as before
  userMap.bindUser('U1', ' key-1 ', 'alice');
  assert.equal(userMap.getMeegleUserKey('U1'), 'key-1');
  await reportCard({ slackUserId: 'U1', title: 't', url: 'u' }); // no-op
});
