'use strict';

/**
 * Slack bot 主程序（Socket Mode）
 * 用法：频道里 @toldmeegle 卡片标题 @负责人  →  自动在 Meegle 建卡并回复链接
 * 启动：npm start
 */

const { App } = require('@slack/bolt');
const { parseMentionText, slackMention } = require('./parse');
const { createWorkItem, cardUrl } = require('./meegle');
const { getMeegleUserKey, bindUser } = require('./userMap');

const BIND_HINT = '用法：`@toldmeegle 卡片标题 @负责人`\n例如：`@toldmeegle 修复登录页报错 @张三`';

const app = new App({
  token: process.env.SLACK_BOT_TOKEN,
  appToken: process.env.SLACK_APP_TOKEN,
  socketMode: true,
});

let botUserId = '';

/** 处理 @机器人 的消息 */
app.event('app_mention', async ({ event, client, context }) => {
  const { title, assigneeSlackIds } = parseMentionText(event.text || '', botUserId);

  const reply = (text) =>
    client.chat.postMessage({ channel: event.channel, thread_ts: event.ts, text });

  if (!title) {
    await reply(`没识别到卡片标题。${BIND_HINT}`);
    return;
  }

  // 1) 把被 @ 的 Slack 用户映射成 Meegle user_key
  const assigneeUserKeys = [];
  const unmapped = [];
  for (const slackId of assigneeSlackIds) {
    const key = getMeegleUserKey(slackId);
    if (key) assigneeUserKeys.push(key);
    else unmapped.push(slackId);
  }

  // 2) 发起人身份：优先用他自己绑定的 user_key，未绑定则用服务账号
  const requesterKey = getMeegleUserKey(event.user) || process.env.MEEGLE_USER_KEY || '';

  const description = [
    `由 Slack 创建：<@${event.user}>`,
    `原始消息：${event.text || ''}`,
    context.channelId ? `频道：<#${context.channelId}>` : '',
  ]
    .filter(Boolean)
    .join('\n');

  try {
    const created = await createWorkItem({
      name: title,
      assigneeUserKeys,
      description,
      requesterUserKey: requesterKey,
    });

    const lines = [`✅ 已创建卡片：<${cardUrl(created.id)}|${title}>`];
    if (assigneeUserKeys.length && created.assignApplied) {
      lines.push(`负责人：${assigneeSlackIds.map(slackMention).join(' ')}`);
    } else if (assigneeUserKeys.length) {
      lines.push('⚠️ 负责人未能自动写入（角色配置不匹配），请到卡片里手动指定。');
    }
    if (unmapped.length) {
      lines.push(
        `⚠️ 以下同事还没绑定 Meegle 账号，未加入负责人：${unmapped.map(slackMention).join(' ')}\n` +
          '请各自执行 `/meegle-bind <你的 Meegle user_key>` 绑定一次（user_key 在 Meegle 里双击自己头像复制）。',
      );
    }
    await reply(lines.join('\n'));
  } catch (err) {
    console.error('[app_mention] 创建失败', err);
    await reply(
      `❌ 创建卡片失败：\n\`\`\`${String(err.message).slice(0, 800)}\`\`\`\n请检查 bot 日志或 Meegle 配置。`,
    );
  }
});

/** 自助绑定：/meegle-bind <user_key> */
app.command('/meegle-bind', async ({ command, ack, respond }) => {
  await ack();
  const userKey = (command.text || '').trim();
  if (!userKey) {
    await respond('用法：`/meegle-bind <你的 Meegle user_key>`\nuser_key 获取方式：在 Meegle 里双击自己的头像复制。');
    return;
  }
  bindUser(command.user_id, userKey, command.user_name);
  await respond(`✅ 绑定成功，之后 @你 建卡时会自动把你设为负责人。`);
});

(async () => {
  const auth = await app.client.auth.test();
  botUserId = auth.user_id;
  await app.start();
  console.log(`⚡ Slack Meegle bot 已启动，bot user_id = ${botUserId}`);
})();
