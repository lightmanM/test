'use strict';

/**
 * 配置自检脚本：验证凭据可用 + 查出正确的工作项类型 key
 * 运行：npm run inspect
 */

const { getPluginToken, listWorkItemTypes, config } = require('../src/meegle');

(async () => {
  const masked = (s) => (s ? `${String(s).slice(0, 8)}****` : '(未配置)');

  console.log('—— 当前配置 ——');
  console.log('域名 domain      :', config.DOMAIN);
  console.log('空间 project_key :', config.PROJECT_KEY || '(未配置)');
  console.log('插件 ID          :', masked(process.env.MEEGLE_PLUGIN_ID));
  console.log('服务 user_key    :', masked(config.SERVICE_USER_KEY));
  console.log('');

  console.log('—— 1. 获取 plugin_access_token ——');
  try {
    const token = await getPluginToken();
    console.log('✅ 成功：', masked(token));
  } catch (err) {
    console.log('❌ 失败：', err.message);
    console.log('   检查 MEEGLE_PLUGIN_ID / MEEGLE_PLUGIN_SECRET，以及 MEEGLE_DOMAIN 是否为 meegle.com');
    return;
  }

  console.log('');
  console.log('—— 2. 查询空间下的工作项类型（all-types）——');
  try {
    const res = await listWorkItemTypes(config.SERVICE_USER_KEY);
    if (res.err_code !== 0) {
      console.log(`❌ 接口返回错误 [${res.err_code}] ${res.err_msg}`);
      console.log('   若提示权限问题：把 MEEGLE_USER_KEY 换成空间内成员的 user_key，或在插件权限管理里放开对应权限。');
      return;
    }
    const list = res.data || [];
    if (!list.length) {
      console.log('⚠️ 返回为空，检查 MEEGLE_PROJECT_KEY 是否正确');
      return;
    }
    console.log('✅ 可用工作项类型：');
    list.forEach((t) => {
      const key = t.type_key || t.work_item_type_key || t.key || JSON.stringify(t);
      const name = t.name || t.type_name || '';
      console.log(`   - ${key}${name ? `  (${name})` : ''}`);
    });
    console.log('');
    console.log('把想要的类型填到 .env 的 MEEGLE_WORK_ITEM_TYPE_KEY，然后执行 npm run test-create 验证建卡。');
  } catch (err) {
    console.log('❌ 调用失败：', err.message);
  }
})();
