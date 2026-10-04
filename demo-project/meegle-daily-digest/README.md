# Meegle 团队研发进展每日汇总

> Orville · 2026-10-01
> **在线 demo**（已跑通真实数据）：https://orville-wang.app.n8n.cloud/workflow/rL4J3jp2pyVGdigm

每工作日 09:00 从 Meegle 拉取整个团队近 24h 的 bug/需求变更，代码层聚合，生成结构化中文日报，推送 Slack。

---

## 📦 这个包是什么

一个**可以在你本机 / n8n Cloud / n8n self-host 任一环境直接部署**的工作流。
部署只需选一条路（推荐 Cloud，3 分钟跑通）：

| 路径 | 适合 | 时长 |
|---|---|---|
| **A. n8n Cloud（推荐）** | 生产/试用 | ~3 min |
| **B. n8n self-host 导入 JSON** | 已自有 n8n 实例 | ~5 min |
| **C. 不起 n8n，直接验证逻辑** | 审核 smoke test | ~1 min |

---

## 🚀 路径 A：n8n Cloud 部署（推荐）

我已在 demo workspace 上跑过一次：https://orville-wang.app.n8n.cloud/workflow/rL4J3jp2pyVGdigm

部署到你自己（或 Pond 官方）n8n Cloud workspace：

1. 登录 n8n Cloud，开通 MCP server：https://docs.n8n.io/advanced-ai/accessing-n8n-mcp-server/
2. 用 MCP 客户端（Claude Code / Cursor）连接你的 n8n Cloud MCP
3. 让 AI 读取本目录下的 `meegle-daily-digest.n8n-cloud-sdk.js`，调用 `validate_workflow` + `create_workflow_from_code` 即可

**或者直接打开我这份**（demo 已跑通）：https://orville-wang.app.n8n.cloud/workflow/rL4J3jp2pyVGdigm → 在 UI 里点 "Duplicate" 到你自己的 workspace。

### 配置

打开 workflow 的 `Config` 节点，填三项：

| 字段 | 怎么拿 |
|---|---|
| `meegle_mcp_token` | 找 Meegle 管理员开通，形如 `m-AB-xxxxxxxx-xxxx-...` |
| `meegle_project_key` | Meegle 空间「设置 → 基本信息」，Pond Engineering 是 `693a4c95897fcda33ebe0175` |
| `meegle_simple_name` | 同上页面，Pond Engineering 是 `c4u20i` |

推送 Slack 的话再填：
- `delivery_mode` = `slack`
- `slack_webhook_url` = 你的 [Incoming Webhook](https://api.slack.com/messaging/webhooks)

### 激活

- 默认 `inactive`，schedule 不生效。
- 要每天 9 点自动跑，UI 右上 "Activate" 切换为 Active。

---

## 🏠 路径 B：n8n self-host 导入 JSON

> 如果你已有自己跑的 n8n（不在 Cloud），这条最简单——但**需要能访问外网**（meegle.com）。

工作流源码在 `meegle-daily-digest.n8n-cloud-sdk.js`。鉴于 n8n 目前不支持直接 import SDK code，
你有两个选择：

1. 在 n8n Cloud 上部署好（路径 A），然后用 UI 的 **Download** 按钮导出 JSON，拷到 self-host import
2. 参考 SDK code 手工在 self-host 画布上搭 12 个节点（不推荐，费时）

---

## 🧪 路径 C：不起 n8n，1 分钟验证核心逻辑

专为 code review 准备。Node ≥ 18，无 npm 依赖：

```bash
cd meegle-daily-digest

# Smoke 1: 内置 mock 数据
node tools/run_digest.js

# Smoke 2: 真实 Meegle 数据（需 token）
export MEEGLE_MCP_TOKEN=m-AB-xxxxxxxx-xxxx-...
node tools/fetch_meegle_mcp.js | WINDOW_HOURS=720 node tools/run_digest.js /dev/stdin
```

期望输出示例见 `demo/self-test-output.txt`（这是 2026-09-29 的快照）。

---

## 📁 文件清单

```
meegle-daily-digest/
├── README.md                              ← 本文件
├── meegle-daily-digest.n8n-cloud-sdk.js   ⭐ 工作流定义（n8n Workflow SDK，可部署）
├── DEPLOYMENT.md                          ← 6 项提交表单内容（供 Liz 参考）
├── data/
│   └── mock_items.json                    ← 11 条 mock work_item（供 smoke test）
├── tools/
│   ├── run_digest.js                      ← 核心逻辑：聚合 + 日报生成
│   └── fetch_meegle_mcp.js                ← Meegle MCP 客户端
└── demo/
    └── self-test-output.txt               ← 离线 runner 执行快照 + 6 条断言
```

---

## 🏗️ 工作流结构（12 节点）

```
┌─ Trigger ──────────────────────────────────────────────┐
│ Manual Trigger (demo)   OR   Schedule 09:00 Weekdays   │
└────────────────────────┬───────────────────────────────┘
                         ↓
                    ┌── Config ──┐      ← 所有可调参数集中在这里
                    └─────┬──────┘
                          ↓
         ┌──── MCP: fetch bugs (issue) ────┐
         └────┬─────────────────────────────┘
              ↓
         ┌──── MCP: fetch stories ─────────┐
         └────┬─────────────────────────────┘
              ↓
         ┌──── Normalize MCP results ──────┐  ← 解析 moql_field_list → work_item
         └────┬─────────────────────────────┘
              ↓
         ┌──── Aggregate (in code) ────────┐  ← 优先级/高优/阻塞/挂起统计
         └────┬─────────────────────────────┘
              ↓
         ┌──── Compose digest ─────────────┐  ← 生成 Markdown 日报
         └────┬─────────────────────────────┘
              ↓
        ┌─────┴──────┐
        ↓            ↓
   Slack webhook   Done (log only)
```

---

## 💰 成本

| 项 | 成本 | 说明 |
|---|---|---|
| n8n Cloud | 订阅价（Pond 已有） | 无增量 |
| Meegle OpenAPI | 内部系统 | $0 |
| Slack Incoming Webhook | 免费 | $0 |
| **增量总成本** | **$0** | 无需 Billy 报销 |

---

## 🐛 已知的 3 个 n8n Cloud 坑（部署前必读）

1. **`$env` 被禁用**：`N8N_BLOCK_ENV_ACCESS_IN_NODE=true` 是 Cloud 默认。config 务必走 hard-code 或 n8n Variables（不要写 `{{ $env.X }}`）。
2. **HTTP 节点串联时下游只能看到紧邻上游 items**：要拿 bugs + stories 两个 HTTP 的输出，在下游 Code 节点里用 `$('NodeName').all()` 跨节点取，不要依赖链式 `items` 变量。
3. **上游返回 0 items 时整条链路终止**：Normalize 节点要在空输入时也产出至少一条 item（可以打 `_empty: true` 哨兵），下游 Aggregate filter 掉。

详见 `DEPLOYMENT.md` 的「踩坑记录」节。

---

## 🔐 安全注意

- `meegle_mcp_token` 是长期凭证，**不要 commit 到任何 git 仓库**
- 生产部署建议把 token 放到 **n8n Credentials**（type = Header Auth），Config 节点改成 `{{ $credentials.headerAuth.value }}` 引用
- Slack webhook URL 同理
