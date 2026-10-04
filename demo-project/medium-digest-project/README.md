# Medium Digest Workflow

可复用的 n8n 工作流项目：手动查询运行时刻前 168 小时内 Gmail 中包含 `Medium` 关键词的全部邮件，从邮件正文和 MIME 内容中提取文章链接，通过独立的 Freedium/CloakBrowser 服务获取全文，使用 OpenAI-compatible Chat Completions API 过滤和总结，最后发送到 Slack。报告中的文章按邮件时间从新到旧排列。

项目不包含任何个人 Gmail、LLM 或 Slack credential。导入 n8n 后必须由部署者自行绑定凭证。

## 项目结构

```text
.
├── README.md
├── workflow/
│   ├── medium-digest.workflow.json
│   ├── extract-article-links.js
│   ├── build-window.js
│   ├── prepare-article.js
│   ├── parse-llm-result.js
│   ├── record-fetch-failure.js
│   ├── build-report.js
│   └── build-empty-report.js
└── services/
    └── medium-reader/
        ├── Dockerfile
        ├── compose.yml
        ├── .env.example
        ├── package.json
        ├── src/
        └── test/
```

## 前置条件

- 已运行的 self-hosted n8n（建议 n8n 2.x）。
- Gmail OAuth2 credential，具有读取目标邮箱的权限。
- Slack App/Bot Token，至少有 `chat:write` scope，并且 Bot 已加入目标频道。
- OpenAI-compatible API credential 和 endpoint。
- Docker、Docker Compose，以及能运行 CloakBrowser 的主机资源。

## 1. 部署全文抓取服务

```bash
cd services/medium-reader
cp .env.example .env
docker compose -f compose.yml up -d --build
curl http://127.0.0.1:8000/healthz
```

预期健康检查结果：

```json
{"status":"ok","service":"medium-freedium-reader"}
```

服务监听 `127.0.0.1:8000`，API 为：

```text
POST http://127.0.0.1:8000/extract
```

请求示例：

```json
{
  "url": "https://medium.com/@author/article-slug",
  "timeoutMs": 60000
}
```

如果 n8n 运行在 Docker Desktop 容器中，工作流默认使用：

```text
http://host.docker.internal:8000/extract
```

如果 n8n 和 reader 加入同一个 Docker network，把 `Workflow configuration` 节点中的 `freediumEndpoint` 改为：

```text
http://medium-reader:8000/extract
```

如果 n8n 位于另一台机器，改成 reader 服务可访问的 HTTPS 或内网地址，并按需在 HTTP Request 节点中配置 `Authorization: Bearer ...`。

## 2. 导入 workflow

在 n8n 中导入：

```text
workflow/medium-digest.workflow.json
```

工作流只有 Manual Trigger，没有 Schedule Trigger。每次手动执行都会查询执行时刻前 168 小时内的邮件，并可能再次发送一份 Slack 报告。

## 3. 绑定 credentials

导入后打开以下节点，分别选择部署环境中的 credential：

| 节点 | Credential 类型 | 用途 |
| --- | --- | --- |
| `Find Medium Daily Digest emails` | Gmail OAuth2 | 读取邮件 |
| `Classify and summarize article` | OpenAI API | 调用 OpenAI-compatible Chat Completions |
| `Send report to Slack` | Slack Access Token | 发送报告 |

工作流 JSON 不包含任何 credential ID、token、邮箱地址或 Slack App 信息。

Slack 建议使用 Bot User OAuth Token（通常以 `xoxb-` 开头），并在 Slack App 的 OAuth 设置中添加：

```text
chat:write
```

同时把 Bot 邀请到目标频道。Slack 当前推荐现代 App 使用 `chat:write`，而不是旧的 `chat:write:bot`。

## 4. 配置 provider 和频道

在 `Workflow configuration` 节点修改：

```text
freediumEndpoint = http://host.docker.internal:8000/extract
llmEndpoint      = https://api.openai.com/v1/chat/completions
llmModel         = gpt-4o-mini
slackChannel     = YOUR_SLACK_CHANNEL_ID
```

`llmEndpoint` 必须是完整的 Chat Completions URL。API key 只能放在 n8n credential 中，不要写进 Set/Code 节点或 Git。

## 工作流行为

1. 计算 `[now - 168h, now]` 的滚动 UTC 时间窗口，每次执行重新计算。
2. 使用 Gmail 搜索词 `Medium`，不假设邮件主题名称。
3. Gmail 节点开启 `returnAll`，读取分页结果中的全部邮件，并返回匹配邮件数量。
4. 读取 Gmail 节点返回的 `html`、`textAsHtml`、`text` 和 MIME payload。
5. 过滤头像、个人主页、会员页、图片和导航链接，只保留 Medium 文章 URL 以及有足够语义证据的自定义域名文章 URL。
6. 保留每篇文章所属邮件的日期；重复文章取较新的邮件记录，报告最终按日期倒序。
7. 逐篇调用 reader 服务。reader 使用 CloakBrowser 访问 Freedium，并返回文章正文。
8. 单篇全文抓取失败会进入失败记录分支，不终止整批文章。
9. 对正文调用 LLM，输出相关主题、中文摘要和正文中明确出现的 GitHub 仓库。
10. 合并结果并发送 Markdown 格式 Slack 报告。

## 安全与运营注意事项

- 不要把 Gmail OAuth refresh token、LLM API key、Slack token 写入仓库。
- `API_TOKEN` 可用于保护 reader 服务；启用后必须同步在 n8n HTTP Request 节点配置 Bearer header。
- Freedium 是外部服务，页面结构、限流和可用性可能变化；workflow 会记录单篇失败，但不会绕过登录、验证码或付费账户。
- 仅处理你有权访问和处理的邮件及文章，并自行确认相关服务条款和版权要求。

## 本地验证

```bash
cd services/medium-reader
npm test
docker compose -f compose.yml config
```

导入 workflow 后，先执行 reader 健康检查，再用 n8n 的 Manual Trigger 做一次小范围验证。确认 Gmail、Freedium、LLM 和 Slack 均可用后，再执行完整报告。
