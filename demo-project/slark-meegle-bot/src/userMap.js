'use strict';

/**
 * Slack 用户 ↔ Meegle user_key 映射
 * 存放于 data/user-map.json，通过 Slack 斜杠命令 `/meegle-bind <user_key>` 自助绑定。
 */

const fs = require('fs');
const path = require('path');

const FILE = process.env.USER_MAP_FILE || path.join(__dirname, '..', 'data', 'user-map.json');

function load() {
  try {
    return JSON.parse(fs.readFileSync(FILE, 'utf8')) || {};
  } catch (e) {
    return {};
  }
}

function save(map) {
  fs.mkdirSync(path.dirname(FILE), { recursive: true });
  fs.writeFileSync(FILE, JSON.stringify(map, null, 2), 'utf8');
}

/** 取某个 Slack 用户绑定的 Meegle user_key，没有则返回空字符串 */
function getMeegleUserKey(slackUserId) {
  const entry = load()[slackUserId];
  return entry && entry.user_key ? String(entry.user_key).trim() : '';
}

/** 绑定（重复绑定会覆盖） */
function bindUser(slackUserId, userKey, displayName) {
  const map = load();
  map[slackUserId] = {
    user_key: String(userKey).trim(),
    ...(displayName ? { name: displayName } : {}),
    updated_at: new Date().toISOString(),
  };
  save(map);
  return map[slackUserId];
}

module.exports = { getMeegleUserKey, bindUser, load };
