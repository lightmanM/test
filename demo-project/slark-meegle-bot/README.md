# slack-meegle-bot

Slack 里 `@toldmeegle 卡片标题 @负责人` → 自动在 Meegle 创建卡片，并在线程里回复卡片链接。组织内所有人可用。

## 一、目录结构

```
slark-meegle-bot/
├── src/
│   ├── index.js      Slack bot 主程序（Socket Mode，监听 app_mention / 斜杠命令）
│   ├── meegle.js     Meegle OpenAPI 封装（token 缓存 + 建卡 + 降级重试）
│   ├── parse.js      解析消息文本：标题 + 被 @ 的负责人
│   └── userMap.js    Slack 用户 ↔ Meegle user_key 映射读写
├── scripts/
│   ├── inspect.js    配置自检：验证凭据 + 列出可用工作项类型
│   └── test-create.js 不走 Slack，直接建一张测试卡
├── data/user-map.json 用户绑定表（由 /meegle-bind 自动写入）
└── .env              你的密钥（不要提交到 git）
```

## 二、跑起来（本地验证）

```bash
cd D:/workspace/pond/slark-meegle-bot
cp .env.example .env      # 然后把值填进去
npm install
npm run inspect           # 1. 验证 Meegle 凭据，并查到 work_item_type_key
npm run test-create       # 2. 建一张测试卡验证链路
npm start                 # 3. 启动 bot（保持这个窗口开着）
```

启动后在 Slack 频道里（先把 bot 拉进频道：`/invite @toldmeegle`）发：

```
@toldmeegle 修复登录页报错 @张三
```

bot 会在消息线程里回复卡片链接。

## 三、.env 每一项怎么填

| 变量 | 从哪来 |
|---|---|
| `SLACK_BOT_TOKEN` | Slack App → OAuth & Permissions → Bot User OAuth Token（`xoxb-`） |
| `SLACK_APP_TOKEN` | Slack App → Socket Mode → App-Level Token（`xapp-`，scope `connections:write`） |
| `MEEGLE_DOMAIN` | 国际版填 `meegle.com`；飞书项目填 `project.feishu.cn` |
| `MEEGLE_PLUGIN_ID` / `MEEGLE_PLUGIN_SECRET` | Meegle 开发者平台 → 插件 → 基本信息 |
| `MEEGLE_PROJECT_KEY` | Meegle 里双击空间图标复制 |
| `MEEGLE_SIMPLE_NAME` | 空间 URL 的域名段，如 `https://meegle.com/xxx/overview` → `xxx`（用于拼卡片链接） |
| `MEEGLE_WORK_ITEM_TYPE_KEY` | `npm run inspect` 列出来的类型 key（story / task / bug …） |
| `MEEGLE_ROLE_KEY` | 负责人角色 key，默认 `owner`；建卡报 `50006` 时改它 |
| `MEEGLE_USER_KEY` | 机器人服务账号的 user_key（双击自己头像复制），用于发起人未绑定时的兜底身份 |

## 四、Slack 侧还需要补的配置

1. **斜杠命令**（用于同事自助绑定）：Slack App → Features → Slash Commands → Create New Command
   - Command：`/meegle-bind`
   - Short Description：绑定 Meegle 账号
   - Usage Hint：`<你的 Meegle user_key>`
   - （Socket Mode 下 Request URL 可留空）
2. 改完配置记得在 Install App 页面 **Reinstall**。

## 五、让组织内所有人都能用

1. Bot 已在工作区安装（你们已完成）——任何人 @它都会触发事件。
2. **频道里要用，得先把 bot 拉进去**：`/invite @toldmeegle`；私聊则需 App Home 里打开 Messages Tab（清单里已开）。
3. **每位同事用前跑一次** `/meegle-bind <自己的 user_key>`，这样 @他 才能被写成负责人；没绑定的会被建卡时跳过，并在回复里提示。
4. 长期运行：把服务部署到一台常驻机器（或云主机/容器）上用 `pm2`、`systemd`、`docker` 守护；Socket Mode 不需要公网 IP 和域名，只要能出网即可。

## 六、行为细节

- 多个负责人：`@toldmeegle 标题 @A @B` → 都会写进负责人。
- 建卡降级策略：`负责人+描述` → `负责人` → `仅标题`，避免某个可选字段不合法导致整卡失败；回复里会说明实际生效到哪一级。
- 令牌缓存：`plugin_access_token` 有效期 2 小时，进程内缓存复用，命中 10211 自动刷新一次。
- 限流：Meegle 单 token 每接口 15 QPS，个人使用量级完全够用。
