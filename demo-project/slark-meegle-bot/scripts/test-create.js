'use strict';

/**
 * 不经过 Slack，直接调 Meegle 建一张测试卡，用于验证配置
 * 运行：npm run test-create
 */

const { createWorkItem, cardUrl, config } = require('../src/meegle');

(async () => {
  const name = `[Slack bot 联通测试] ${new Date().toLocaleString('zh-CN')}`;
  console.log('尝试创建：', name);
  console.log('空间：', config.PROJECT_KEY, '｜类型：', config.TYPE_KEY, '｜角色：', config.ROLE_KEY || '(空)');
  try {
    const created = await createWorkItem({
      name,
      assigneeUserKeys: [],
      description: '来自 slack-meegle-bot 的连通性测试，可删除。',
      requesterUserKey: config.SERVICE_USER_KEY,
    });
    console.log(`✅ 创建成功，工作项 ID = ${created.id}（提交方式：${created.level}）`);
    console.log('链接：', cardUrl(created.id));
    console.log('如果链接打不开，改 .env 里的 MEEGLE_SIMPLE_NAME 为空间 URL 的域名段即可。');
  } catch (err) {
    console.log('❌ 创建失败：');
    console.log(err.message);
  }
})();
