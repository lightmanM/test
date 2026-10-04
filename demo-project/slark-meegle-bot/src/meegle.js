'use strict';

/**
 * Meegle OpenAPI 封装
 * - 插件凭据换 plugin_access_token（有效期 2 小时，内存缓存复用）
 * - 创建工作项（卡片）
 * 文档：https://meegle.com/b/helpcenter/developer/create-an-api-configuration
 */

const DOMAIN = process.env.MEEGLE_DOMAIN || 'meegle.com';
const WEB_BASE = process.env.MEEGLE_WEB_BASE || `https://${DOMAIN}`;

const PLUGIN_ID = process.env.MEEGLE_PLUGIN_ID || '';
const PLUGIN_SECRET = process.env.MEEGLE_PLUGIN_SECRET || '';
const PROJECT_KEY = process.env.MEEGLE_PROJECT_KEY || '';
const TYPE_KEY = process.env.MEEGLE_WORK_ITEM_TYPE_KEY || 'story';
const ROLE_KEY = (process.env.MEEGLE_ROLE_KEY || 'owner').trim();
const SERVICE_USER_KEY = process.env.MEEGLE_USER_KEY || '';
const SIMPLE_NAME = (process.env.MEEGLE_SIMPLE_NAME || PROJECT_KEY).trim();

/** 错误码 → 人话（便于在 Slack 里直接回复用户） */
const ERROR_HINTS = {
  10001: '当前身份没有该空间的权限（检查插件权限管理 / user_key 是否在空间内）',
  10211: '插件 token 无效，检查 Plugin ID / Plugin Secret',
  20038: '必填字段未填或字段值不合法',
  20083: '请求中存在重复字段',
  30005: '工作项不存在',
  30009: '字段不存在（可能是 description 等字段在当前工作项类型里没有）',
  30014: '工作项类型不存在，请用 npm run inspect 查询正确的 work_item_type_key',
  50006: '角色/负责人或模板解析失败（多为 MEEGLE_ROLE_KEY 或负责人 user_key 不对）',
};

let tokenCache = { token: '', expireAt: 0 };

/**
 * 归一化业务返回码：
 * - 国内版/文档风格：{ err_code, err_msg, data }
 * - 国际版实测：    { error: { code, msg }, data }
 */
function getBizCode(json) {
  if (json == null) return -1;
  if (json.err_code !== undefined) return json.err_code;
  if (json.error && json.error.code !== undefined) return json.error.code;
  return 0;
}

function getBizMsg(json) {
  return json && (json.err_msg || (json.error && json.error.msg) || 'unknown error');
}

/** 把国际版格式归一化成 err_code 风格，方便下游统一处理 */
function normalize(json) {
  if (json && json.err_code === undefined && json.error) {
    json.err_code = json.error.code;
    json.err_msg = json.error.msg;
  }
  return json;
}

function assertConfig() {
  const missing = [];
  if (!PLUGIN_ID) missing.push('MEEGLE_PLUGIN_ID');
  if (!PLUGIN_SECRET) missing.push('MEEGLE_PLUGIN_SECRET');
  if (!PROJECT_KEY) missing.push('MEEGLE_PROJECT_KEY');
  if (missing.length) throw new Error(`.env 缺少配置：${missing.join(', ')}`);
}

/** 换取 plugin_access_token，带过期缓存 */
async function getPluginToken(force = false) {
  assertConfig();
  const now = Date.now();
  if (!force && tokenCache.token && now < tokenCache.expireAt) return tokenCache.token;

  const res = await fetch(`https://${DOMAIN}/open_api/authen/plugin_token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      plugin_id: PLUGIN_ID,
      plugin_secret: PLUGIN_SECRET,
      // 0 = 正式 plugin_access_token；1 = 虚拟 token（仅调试用，插件未发布时也能调通）
      type: Number(process.env.MEEGLE_TOKEN_TYPE || 0),
    }),
  });
  const json = await res.json().catch(() => null);
  if (!json || getBizCode(json) !== 0) {
    throw new Error(`获取 plugin_access_token 失败：${JSON.stringify(json)}`);
  }
  const token = json.data.token;
  // 国际版返回相对秒数（如 7200），文档写的是秒级时间戳，两种都兼容；提前 2 分钟失效
  const rawExpire = Number(json.data.expire_time) || 0;
  const expireAt = rawExpire > 1e9
    ? rawExpire * 1000 - 120000
    : now + rawExpire * 1000 - 120000;
  tokenCache = { token, expireAt };
  return token;
}

/** 统一调用 Meegle OpenAPI，返回原始业务 JSON */
async function callOpenApi(path, { method = 'POST', body, userKey } = {}) {
  const token = await getPluginToken();
  const headers = { 'Content-Type': 'application/json', 'X-PLUGIN-TOKEN': token };
  // 使用插件身份凭证时，必须带 X-USER-KEY 指明以谁的身份调用
  const effectiveUserKey = userKey || SERVICE_USER_KEY;
  if (effectiveUserKey) headers['X-USER-KEY'] = effectiveUserKey;

  const res = await fetch(`https://${DOMAIN}${path}`, {
    method,
    headers,
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch (e) {
    throw new Error(`Meegle 返回非 JSON（HTTP ${res.status}）：${text.slice(0, 300)}`);
  }
  if (getBizCode(json) === 10211) {
    // token 失效，清缓存重试一次
    tokenCache = { token: '', expireAt: 0 };
    const retry = await fetch(`https://${DOMAIN}${path}`, {
      method,
      headers: { ...headers, 'X-PLUGIN-TOKEN': await getPluginToken(true) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    return normalize(JSON.parse(await retry.text()));
  }
  return normalize(json);
}

/** 空间下所有工作项类型（用来查 work_item_type_key） */
async function listWorkItemTypes(userKey) {
  return callOpenApi(`/open_api/${encodeURIComponent(PROJECT_KEY)}/work_item/all-types`, {
    method: 'GET',
    userKey,
  });
}

function hintFor(code, msg) {
  return ERROR_HINTS[code] ? `${msg}（${ERROR_HINTS[code]}）` : msg;
}

/**
 * 创建工作项。
 * 依次降级尝试：带负责人+描述 → 带负责人 → 只有标题，避免因为某个可选字段不合法整卡创建失败。
 * @returns {Promise<{id:number, level:string, brief:string}>}
 */
async function createWorkItem({ name, assigneeUserKeys = [], description = '', requesterUserKey = '' }) {
  const userKey = requesterUserKey || SERVICE_USER_KEY;
  const canAssign = Boolean(ROLE_KEY && assigneeUserKeys.length);
  const canDescribe = Boolean(description);

  const attempts = [
    { level: '负责人 + 描述', assign: canAssign, describe: canDescribe },
    { level: '负责人', assign: canAssign, describe: false },
    { level: '仅标题', assign: false, describe: false },
  ].filter((a, i, arr) => i === 0 || a.assign !== arr[i - 1].assign || a.describe !== arr[i - 1].describe);

  const errors = [];
  for (const attempt of attempts) {
    const fieldValuePairs = [];
    if (attempt.assign) {
      fieldValuePairs.push({
        field_key: 'role_owners',
        field_value: [{ role: ROLE_KEY, owners: assigneeUserKeys }],
      });
    }
    if (attempt.describe) {
      fieldValuePairs.push({ field_key: 'description', field_value: description });
    }

    const body = {
      work_item_type_key: TYPE_KEY,
      name,
      required_mode: 0, // 0 = 不校验必填字段，降低建卡失败率
    };
    if (fieldValuePairs.length) body.field_value_pairs = fieldValuePairs;

    const json = await callOpenApi(
      `/open_api/${encodeURIComponent(PROJECT_KEY)}/work_item/create`,
      { method: 'POST', body, userKey },
    );

    if (json.err_code === 0) {
      return { id: json.data, level: attempt.level, assignApplied: attempt.assign, brief: '' };
    }
    errors.push(`${attempt.level} → [${json.err_code}] ${hintFor(json.err_code, json.err_msg)}`);
  }

  throw new Error(errors.join('\n'));
}

/** 卡片网页链接（用于在 Slack 里回复可点击的链接） */
const CARD_URL_PATTERN =
  process.env.MEEGLE_CARD_URL_PATTERN || '{base}/{simple}/detail/{type}/{id}';

function cardUrl(id) {
  const base = WEB_BASE.replace(/\/$/, '').replace(/^http:\/\//i, 'https://');
  return CARD_URL_PATTERN.replace('{base}', base)
    .replace('{simple}', encodeURIComponent(SIMPLE_NAME))
    .replace('{type}', encodeURIComponent(TYPE_KEY))
    .replace('{id}', id);
}

module.exports = {
  getPluginToken,
  callOpenApi,
  listWorkItemTypes,
  createWorkItem,
  cardUrl,
  config: { DOMAIN, PROJECT_KEY, TYPE_KEY, ROLE_KEY, SERVICE_USER_KEY, webBase: WEB_BASE },
};
