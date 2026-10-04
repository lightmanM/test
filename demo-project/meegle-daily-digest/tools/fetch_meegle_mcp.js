#!/usr/bin/env node
// Fetch work items from Meegle MCP server and normalize to work_item shape.
// Usage:
//   node tools/fetch_meegle_mcp.js [project_key] [window_hours]
//   MEEGLE_MCP_TOKEN=m-AB-xxx node tools/fetch_meegle_mcp.js
//
// Env:
//   MEEGLE_MCP_TOKEN  (required)  e.g. m-AB-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx...
//   MEEGLE_PROJECT_KEY (optional) default: 693a4c95897fcda33ebe0175 (Pond Engineering)
//   MEEGLE_PROJECT_SIMPLE_NAME (optional) default: c4u20i
//   WINDOW_HOURS (optional) default 24

const https = require('https');

const MCP_URL = 'https://meegle.com/mcp_server/v1';
const TOKEN = process.env.MEEGLE_MCP_TOKEN || '';
const PROJECT_KEY = process.env.MEEGLE_PROJECT_KEY || '693a4c95897fcda33ebe0175';
const SIMPLE_NAME = process.env.MEEGLE_PROJECT_SIMPLE_NAME || 'c4u20i';
const WINDOW_HOURS = parseInt(process.env.WINDOW_HOURS || '24', 10);

if (!TOKEN) { console.error('MEEGLE_MCP_TOKEN not set'); process.exit(1); }

function mcpCall(tool, args) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ jsonrpc: '2.0', id: Date.now(), method: 'tools/call', params: { name: tool, arguments: args } });
    const url = new URL(MCP_URL);
    const req = https.request({
      hostname: url.hostname, path: url.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Mcp-Token': TOKEN, 'Content-Length': Buffer.byteLength(body) }
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch (e) { reject(new Error(`bad json: ${data.slice(0,200)}`)); }
      });
    });
    req.on('error', reject);
    req.write(body); req.end();
  });
}

// Parse the moql_field_list array into a flat object
function parseWorkItem(raw) {
  const out = {};
  for (const f of raw.moql_field_list || []) {
    const k = f.key;
    const v = f.value || {};
    if (v.string_value !== undefined) out[k] = v.string_value;
    else if (v.long_value !== undefined) out[k] = String(v.long_value);
    else if (v.key_label_value) out[k] = v.key_label_value.label;
    else if (v.key_label_value_list) out[k] = v.key_label_value_list.map(x => x.label).join(',');
    else if (v.user_value_list) out[k] = v.user_value_list.map(u => u.name_cn || u.name_en).join(',');
    else out[k] = JSON.stringify(v);
  }
  return out;
}

async function searchByMql(mql) {
  const resp = await mcpCall('search_by_mql', { project_key: PROJECT_KEY, mql });
  const texts = (resp.result?.content || []).map(c => c.text).filter(t => !t.startsWith('logid'));
  const parsed = texts.map(t => { try { return JSON.parse(t); } catch { return null; } }).filter(Boolean);
  const result = parsed[0] || {};
  const data = result.data || {};
  const groupId = Object.keys(data)[0];
  const items = (data[groupId] || []).map(parseWorkItem);
  return { items, count: result.list?.[0]?.count || 0, sessionId: result.session_id };
}

async function main() {
  const windowDays = Math.max(1, Math.ceil(WINDOW_HOURS / 24));

  // Fetch bugs (issue) and stories in parallel
  const [bugs, stories] = await Promise.all([
    searchByMql(`SELECT \`work_item_id\`, \`name\`, \`priority\`, \`work_item_status\`, \`current_status_operator\`, \`updated_at\`, \`description\` FROM \`${SIMPLE_NAME}\`.\`issue\` WHERE RELATIVE_DATETIME_BETWEEN(\`updated_at\`, 'past', '${windowDays}d')`),
    searchByMql(`SELECT \`work_item_id\`, \`name\`, \`priority\`, \`work_item_status\`, \`current_status_operator\`, \`updated_at\`, \`description\` FROM \`${SIMPLE_NAME}\`.\`story\` WHERE RELATIVE_DATETIME_BETWEEN(\`updated_at\`, 'past', '${windowDays}d')`),
  ]);

  // Normalize to work_item shape
  const normalize = (raw, type) => ({
    key: `POND-${raw.work_item_id}`,
    type,
    title: raw.name || '(无标题)',
    priority: raw.priority || 'P2',
    status: raw.work_item_status || '进行中',
    assignee: raw.current_status_operator || '未分配',
    created_at: raw.start_time || raw.updated_at,
    updated_at: raw.updated_at,
    blocked: (raw.work_item_status || '').includes('阻塞') || (raw.work_item_status || '').includes('blocked'),
  });

  const all = [
    ...bugs.items.map(i => normalize(i, 'bug')),
    ...stories.items.map(i => normalize(i, 'story')),
  ];

  // Summary stats
  const stats = {
    bugs: bugs.items.length,
    stories: stories.items.length,
    total: all.length,
    bugs_count: bugs.count,
    stories_count: stories.count,
  };

  console.error(`[fetch_meegle_mcp] bugs=${stats.bugs} stories=${stats.stories} (total reported: bug=${stats.bugs_count} story=${stats.stories_count})`);
  console.log(JSON.stringify(all, null, 2));
}

main().catch(e => { console.error(e); process.exit(1); });
