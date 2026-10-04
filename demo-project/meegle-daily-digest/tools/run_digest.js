#!/usr/bin/env node
// Offline runner: executes the exact Aggregate + Compose logic from the n8n
// workflow against data/mock_items.json (or a custom JSON file), prints the
// Slack message to stdout, and optionally POSTs to a real Slack webhook.
//
// Usage:
//   node tools/run_digest.js                       # mock data → stdout
//   node tools/run_digest.js path/to/items.json    # custom data → stdout
//   DELIVERY=slack SLACK_WEBHOOK_URL=https://hooks.slack.com/... node tools/run_digest.js
//
// Mirrors the workflow's Code nodes verbatim so offline output == n8n output.

const fs = require('fs');
const path = require('path');

const dataFile = process.argv[2] || path.join(__dirname, '..', 'data', 'mock_items.json');
const items = JSON.parse(fs.readFileSync(dataFile, 'utf8'));

const windowHours = parseInt(process.env.WINDOW_HOURS || '24', 10);
const staleDays = parseInt(process.env.STALE_DAYS || '3', 10);

// If using mock data, shift timestamps so "now" aligns with the latest mock
// entry — keeps the demo deterministic regardless of when it is run.
let now = Date.now();
if (dataFile.includes('mock_items.json')) {
  const latest = Math.max(...items.map(r => new Date(r.updated_at).getTime()));
  now = latest + 3600 * 1000; // 1h after the most recent mock update
}
const windowStart = now - windowHours * 3600 * 1000;
const staleBefore = now - staleDays * 86400 * 1000;

const inWindow = r => new Date(r.updated_at).getTime() >= windowStart;
const bugs = items.filter(r => r.type === 'bug' && inWindow(r));
const stories = items.filter(r => r.type === 'story' && inWindow(r));

const prioOrder = ['P0', 'P1', 'P2', 'P3'];
const prioCount = {};
for (const p of prioOrder) prioCount[p] = { new: 0, closed: 0 };
for (const b of bugs) {
  const p = prioCount[b.priority] ? b.priority : 'P2';
  if (b.status === '已关闭') prioCount[p].closed++; else prioCount[p].new++;
}

const highPriority = items
  .filter(r => r.type === 'bug' && ['P0', 'P1'].includes(r.priority) && r.status !== '已关闭')
  .sort((a, b) => prioOrder.indexOf(a.priority) - prioOrder.indexOf(b.priority));

const storyProgress = stories.filter(s => s.status !== '已完成');
const storyDone = stories.filter(s => s.status === '已完成');
const blocked = items.filter(r => r.blocked || r.status === '阻塞');
const staleHighPrio = items.filter(r =>
  r.type === 'bug' && ['P0', 'P1'].includes(r.priority) && r.status !== '已关闭' &&
  new Date(r.updated_at).getTime() < staleBefore
);

const aggregate = {
  date: new Date(now).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' }),
  bugs_total: bugs.length,
  bugs_new: bugs.filter(b => b.status !== '已关闭').length,
  bugs_closed: bugs.filter(b => b.status === '已关闭').length,
  prio: prioCount,
  stories_active: storyProgress.length,
  stories_done: storyDone.length,
};

// ---- Compose (mirrors the n8n Compose node) ----
const a = aggregate;
const prio = a.prio;
const lines = [];
lines.push(`*📊 研发日报 · ${a.date}（团队）*`);
lines.push('');
lines.push(`🔢 *概览*：bug ${a.bugs_total}（新增 ${a.bugs_new}，关闭 ${a.bugs_closed}）；需求推进 ${a.stories_active + a.stories_done} 项`);
lines.push(`　按优先级：P0 新${prio.P0.new}/关${prio.P0.closed} · P1 新${prio.P1.new}/关${prio.P1.closed} · P2 新${prio.P2.new}/关${prio.P2.closed} · P3 新${prio.P3.new}/关${prio.P3.closed}`);
lines.push('');

if (highPriority.length) {
  lines.push(`🔴 *高优 bug*（${highPriority.length}）`);
  for (const b of highPriority.slice(0, 5)) {
    lines.push(`　• \`${b.key}\` [${b.priority}] ${b.title} — @${b.assignee}（${b.status}）`);
  }
  if (highPriority.length > 5) lines.push(`　… 及另外 ${highPriority.length - 5} 个`);
  lines.push('');
}

if (storyProgress.length || storyDone.length) {
  lines.push('📈 *需求进展*');
  for (const s of storyDone.slice(0, 3)) lines.push(`　✅ \`${s.key}\` ${s.title} — @${s.assignee}`);
  for (const s of storyProgress.slice(0, 5)) lines.push(`　🚧 \`${s.key}\` ${s.title} — @${s.assignee}（${s.status}）`);
  lines.push('');
}

if (blocked.length) {
  lines.push(`⛔ *阻塞项*（${blocked.length}）`);
  for (const b of blocked.slice(0, 5)) lines.push(`　• \`${b.key}\` ${b.title} — @${b.assignee}`);
  lines.push('');
}

if (staleHighPrio.length) {
  lines.push(`⏰ *挂起提醒*（> ${staleDays} 天未更新的高优 bug，${staleHighPrio.length} 个）`);
  for (const b of staleHighPrio.slice(0, 3)) lines.push(`　• \`${b.key}\` ${b.title} — @${b.assignee}`);
}

const text = lines.join('\n');
console.log(text);

// Optional live delivery
if ((process.env.DELIVERY || 'stdout') === 'slack') {
  const hook = process.env.SLACK_WEBHOOK_URL;
  if (!hook) { console.error('\n[delivery] SLACK_WEBHOOK_URL not set'); process.exit(1); }
  fetch(hook, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  }).then(async r => {
    const body = await r.text();
    console.log(`\n[delivery] Slack webhook → HTTP ${r.status} ${body}`);
    process.exit(r.ok ? 0 : 2);
  }).catch(e => { console.error('[delivery] error', e); process.exit(2); });
}
