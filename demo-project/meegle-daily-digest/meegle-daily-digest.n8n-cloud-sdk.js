import { workflow, node, trigger, switchCase, expr } from '@n8n/workflow-sdk';

const manualTrigger = trigger({
  type: 'n8n-nodes-base.manualTrigger',
  version: 1,
  config: { name: 'Manual Trigger (demo)' }
});

const scheduleTrigger = trigger({
  type: 'n8n-nodes-base.scheduleTrigger',
  version: 1.3,
  config: {
    name: 'Daily 09:00 Weekdays',
    parameters: {
      rule: {
        interval: [
          { field: 'cronExpression', expression: '0 9 * * 1-5' }
        ]
      }
    }
  }
});

const config = node({
  type: 'n8n-nodes-base.set',
  version: 3.4,
  config: {
    name: 'Config',
    parameters: {
      mode: 'manual',
      includeOtherFields: true,
      assignments: {
        assignments: [
          // NOTE: n8n Cloud blocks $env access in nodes (N8N_BLOCK_ENV_ACCESS_IN_NODE).
          // Values are hard-coded here for the demo; in production, use n8n Variables or Credentials.
          { id: 'a1', name: 'source_mode', value: 'mcp', type: 'string' },
          { id: 'a2', name: 'delivery_mode', value: 'stdout', type: 'string' },
          { id: 'a3', name: 'slack_webhook_url', value: '', type: 'string' },
          { id: 'a4', name: 'window_hours', value: 720, type: 'number' },
          { id: 'a5', name: 'stale_days', value: 3, type: 'number' },
          { id: 'a7', name: 'meegle_mcp_token', value: 'm-AB-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx', type: 'string' },
          { id: 'a8', name: 'meegle_project_key', value: '693a4c95897fcda33ebe0175', type: 'string' },
          { id: 'a9', name: 'meegle_simple_name', value: 'c4u20i', type: 'string' }
        ]
      }
    }
  }
});

const mcpFetchBugs = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.2,
  config: {
    name: 'MCP: fetch bugs (issue)',
    parameters: {
      method: 'POST',
      url: 'https://meegle.com/mcp_server/v1',
      sendHeaders: true,
      headerParameters: {
        parameters: [
          { name: 'Content-Type', value: 'application/json' },
          { name: 'X-Mcp-Token', value: expr('{{ $json.meegle_mcp_token }}') }
        ]
      },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "search_by_mql", arguments: { project_key: $json.meegle_project_key, mql: "SELECT `work_item_id`, `name`, `priority`, `work_item_status`, `current_status_operator`, `updated_at` FROM `" + $json.meegle_simple_name + "`.`issue` WHERE RELATIVE_DATETIME_BETWEEN(`updated_at`, \x27past\x27, \x27" + Math.max(1, Math.ceil($json.window_hours/24)) + "d\x27)" } } }) }}')
    }
  }
});

const mcpFetchStories = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.2,
  config: {
    name: 'MCP: fetch stories',
    parameters: {
      method: 'POST',
      url: 'https://meegle.com/mcp_server/v1',
      sendHeaders: true,
      headerParameters: {
        parameters: [
          { name: 'Content-Type', value: 'application/json' },
          { name: 'X-Mcp-Token', value: expr("{{ $('Config').first().json.meegle_mcp_token }}") }
        ]
      },
      sendBody: true,
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "search_by_mql", arguments: { project_key: $("Config").first().json.meegle_project_key, mql: "SELECT `work_item_id`, `name`, `priority`, `work_item_status`, `current_status_operator`, `updated_at` FROM `" + $("Config").first().json.meegle_simple_name + "`.`story` WHERE RELATIVE_DATETIME_BETWEEN(`updated_at`, \x27past\x27, \x27" + Math.max(1, Math.ceil($("Config").first().json.window_hours/24)) + "d\x27)" } } }) }}')
    }
  }
});

const normalizeMcp = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Normalize MCP results',
    parameters: {
      jsCode: `// Pull items from BOTH upstream HTTP nodes (bugs node ran first, stories second).
// In a chain, items[] only carries the immediately-previous node's output,
// so we explicitly fetch the bugs node's output via its name.
function extract(rawList, type) {
  const out = [];
  for (const raw of rawList) {
    const o = {};
    for (const f of raw.moql_field_list || []) {
      const k = f.key, v = f.value || {};
      if (v.string_value !== undefined) o[k] = v.string_value;
      else if (v.long_value !== undefined) o[k] = String(v.long_value);
      else if (v.key_label_value) o[k] = v.key_label_value.label;
      else if (v.key_label_value_list) o[k] = v.key_label_value_list.map(x => x.label).join(',');
      else if (v.user_value_list) o[k] = v.user_value_list.map(u => u.name_cn || u.name_en).join(',');
      else o[k] = '';
    }
    out.push({
      key: 'POND-' + o.work_item_id,
      type,
      title: o.name || '(无标题)',
      priority: o.priority || 'P2',
      status: o.work_item_status || '进行中',
      assignee: o.current_status_operator || '未分配',
      created_at: o.updated_at,
      updated_at: o.updated_at,
      blocked: (o.work_item_status || '').includes('阻塞'),
    });
  }
  return out;
}

function parseMcp(items) {
  const rows = [];
  for (const item of items) {
    const texts = (item.json?.result?.content || []).map(c => c.text).filter(t => !t.startsWith('logid'));
    const parsed = texts.map(t => { try { return JSON.parse(t); } catch { return null; } }).filter(Boolean);
    const result = parsed[0] || {};
    const data = result.data || {};
    const groupId = Object.keys(data)[0];
    rows.push(...(data[groupId] || []));
  }
  return rows;
}

const bugsRaw = parseMcp($('MCP: fetch bugs (issue)').all());
const storiesRaw = parseMcp($('MCP: fetch stories').all());
const all = [...extract(bugsRaw, 'bug'), ...extract(storiesRaw, 'story')];
// Always return at least one item so downstream nodes run even when the window is empty.
if (all.length === 0) {
  return [{ json: { _empty: true, key: 'EMPTY', type: 'bug', title: '', priority: 'P3', status: '已关闭', assignee: '', created_at: '', updated_at: '', blocked: false } }];
}
return all.map(r => ({ json: r }));`
    }
  }
});

const aggregate = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Aggregate (in code)',
    parameters: {
      jsCode: `const cfgNode = $('Config').first().json;
const windowHours = cfgNode.window_hours || 24;
const staleDays = cfgNode.stale_days || 3;
const now = Date.now();
const windowStart = now - windowHours * 3600 * 1000;
const staleBefore = now - staleDays * 86400 * 1000;
const rawItems = $input.all().map(i => i.json).filter(r => !r._empty);
const items = rawItems;
const inWindow = r => new Date(r.updated_at).getTime() >= windowStart;
const bugs = items.filter(r => r.type === 'bug' && inWindow(r));
const stories = items.filter(r => r.type === 'story' && inWindow(r));
const prioOrder = ['P0','P1','P2','P3'];
const prioCount = {};
for (const p of prioOrder) prioCount[p] = { new: 0, closed: 0 };
for (const b of bugs) {
  const p = prioCount[b.priority] ? b.priority : 'P2';
  if (b.status === '已关闭') prioCount[p].closed++; else prioCount[p].new++;
}
const highPriority = items
  .filter(r => r.type === 'bug' && ['P0','P1'].includes(r.priority) && r.status !== '已关闭')
  .sort((a,b) => prioOrder.indexOf(a.priority) - prioOrder.indexOf(b.priority));
const storyProgress = stories.filter(s => s.status !== '已完成');
const storyDone = stories.filter(s => s.status === '已完成');
const blocked = items.filter(r => r.blocked || r.status === '阻塞');
const staleHighPrio = items.filter(r =>
  r.type === 'bug' && ['P0','P1'].includes(r.priority) && r.status !== '已关闭' &&
  new Date(r.updated_at).getTime() < staleBefore
);
const aggregate = {
  date: new Date(now).toLocaleDateString('zh-CN', {timeZone:'Asia/Shanghai'}),
  bugs_total: bugs.length,
  bugs_new: bugs.filter(b=>b.status!=='已关闭').length,
  bugs_closed: bugs.filter(b=>b.status==='已关闭').length,
  prio: prioCount,
  stories_active: storyProgress.length,
  stories_done: storyDone.length,
};
return [{ json: { aggregate, highPriority, storyProgress, storyDone, blocked, staleHighPrio, cfg: cfgNode } }];`
    }
  }
});

const compose = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Compose digest',
    parameters: {
      jsCode: `const d = $input.first().json;
const a = d.aggregate;
const c = d.cfg;
const prio = a.prio;
const lines = [];
lines.push('*📊 研发日报 · ' + a.date + '（团队）*');
lines.push('');
lines.push('🔢 *概览*：bug ' + a.bugs_total + '（新增 ' + a.bugs_new + '，关闭 ' + a.bugs_closed + '）；需求推进 ' + (a.stories_active + a.stories_done) + ' 项');
lines.push('　按优先级：P0 新' + prio.P0.new + '/关' + prio.P0.closed + ' · P1 新' + prio.P1.new + '/关' + prio.P1.closed + ' · P2 新' + prio.P2.new + '/关' + prio.P2.closed + ' · P3 新' + prio.P3.new + '/关' + prio.P3.closed);
lines.push('');
if (d.highPriority.length) {
  lines.push('🔴 *高优 bug*（' + d.highPriority.length + '）');
  for (const b of d.highPriority.slice(0, 5)) {
    lines.push('　• \\x60' + b.key + '\\x60 [' + b.priority + '] ' + b.title + ' — @' + b.assignee + '（' + b.status + '）');
  }
  if (d.highPriority.length > 5) lines.push('　… 及另外 ' + (d.highPriority.length - 5) + ' 个');
  lines.push('');
}
if (d.storyProgress.length || d.storyDone.length) {
  lines.push('📈 *需求进展*');
  for (const s of d.storyDone.slice(0, 3)) lines.push('　✅ \\x60' + s.key + '\\x60 ' + s.title + ' — @' + s.assignee);
  for (const s of d.storyProgress.slice(0, 5)) lines.push('　🚧 \\x60' + s.key + '\\x60 ' + s.title + ' — @' + s.assignee + '（' + s.status + '）');
  lines.push('');
}
if (d.blocked.length) {
  lines.push('⛔ *阻塞项*（' + d.blocked.length + '）');
  for (const b of d.blocked.slice(0, 5)) lines.push('　• \\x60' + b.key + '\\x60 ' + b.title + ' — @' + b.assignee);
  lines.push('');
}
if (d.staleHighPrio.length) {
  lines.push('⏰ *挂起提醒*（> ' + c.stale_days + ' 天未更新的高优 bug，' + d.staleHighPrio.length + ' 个）');
  for (const b of d.staleHighPrio.slice(0, 3)) lines.push('　• \\x60' + b.key + '\\x60 ' + b.title + ' — @' + b.assignee);
}
return [{ json: { text: lines.join('\\n'), delivery_mode: c.delivery_mode, slack_webhook_url: c.slack_webhook_url } }];`
    }
  }
});

const slackPost = node({
  type: 'n8n-nodes-base.httpRequest',
  version: 4.2,
  config: {
    name: 'POST to Slack webhook',
    parameters: {
      method: 'POST',
      url: expr('{{ $json.slack_webhook_url }}'),
      sendBody: true,
      specifyBody: 'json',
      jsonBody: expr('{{ JSON.stringify({ text: $json.text }) }}'),
      options: {}
    }
  }
});

const done = node({
  type: 'n8n-nodes-base.code',
  version: 2,
  config: {
    name: 'Done (log only)',
    parameters: { jsCode: 'return items;' }
  }
});

export default workflow('meegle-daily-digest', 'Meegle 团队研发进展每日汇总')
  .add(manualTrigger).to(config)
  .add(scheduleTrigger).to(config)
  .add(config).to(mcpFetchBugs)
  .add(mcpFetchBugs).to(mcpFetchStories)
  .add(mcpFetchStories).to(normalizeMcp)
  .add(normalizeMcp).to(aggregate)
  .add(aggregate).to(compose)
  .add(compose).to(slackPost)
  .add(compose).to(done)
  .group('Data Source (Meegle MCP)', [mcpFetchBugs, mcpFetchStories, normalizeMcp], { description: 'Fetch bugs & stories from Meegle via MCP server, normalize to work_item' })
  .group('Report Engine', [aggregate, compose], { description: 'Aggregate stats in code, compose structured Chinese digest' });
