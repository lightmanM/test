'use strict';

/**
 * 解析 Slack 消息文本
 * 输入：`<@U0BOT> 修复登录页报错 <@U0ALICE> <@U0BOB>`
 * 输出：{ title: '修复登录页报错', assigneeSlackIds: ['U0ALICE', 'U0BOB'] }
 * 说明：Slack 里被 @ 的对象会以 <@Uxxxx> 形式出现在 event.text 中；
 *      机器人自己被提及的那一段会被剔除，不计入负责人。
 */
function parseMentionText(text, botUserId) {
  const assigneeSlackIds = [];

  let cleaned = String(text || '')
    .replace(/<@([A-Z0-9_]+)(\|[^>]*)?>/g, (match, id) => {
      if (botUserId && id === botUserId) return ' ';
      assigneeSlackIds.push(id);
      return ' ';
    })
    // 还原 Slack 转义的实体
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim();

  // 去掉开头/结尾残留的标点，如 "@bot: 标题"
  cleaned = cleaned.replace(/^[\s:：,，、\-]+/, '').replace(/[\s:：,，、]+$/, '').trim();

  return { title: cleaned, assigneeSlackIds: [...new Set(assigneeSlackIds)] };
}

/** 把 Slack 用户 id 渲染成可点击的 @ 提及 */
function slackMention(userId) {
  return `<@${userId}>`;
}

module.exports = { parseMentionText, slackMention };
