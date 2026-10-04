# Solver 提交（6 项内容）

> Pond 内部验证 · 验证二 · Orville
> 提交日期：2026-10-01
> 审核人：Lightman
> **在线 demo**：https://orville-wang.app.n8n.cloud/workflow/rL4J3jp2pyVGdigm

---

## ① What did you complete?

一个**已部署到 n8n Cloud 并用真实公司数据跑通**的工作流：
每工作日 09:00 从 Meegle 项目空间（Pond Engineering）拉取整个团队近 24h 的 bug（issue）
和需求（story）变更，在代码层完成聚合并生成结构化中文日报，可推送到 Slack。

**已验证能力**：
- ✅ 接 Meegle 官方 MCP server（`https://meegle.com/mcp_server/v1`），用 MQL 查询 work_item
- ✅ 并行拉取 issues（缺陷）+ stories（需求），统一为 work_item 结构
- ✅ 聚合在代码层（不依赖 LLM 算数，避免漏报/虚报）：
  - 新增 vs 关闭 bug 数、按 P0/P1/P2/P3 优先级分布
  - 活跃高优 bug 全列表（不受时间窗限制）
  - 需求进展（进行中 / 已完成）
  - 阻塞项 + 挂起提醒（>3 天未更新的高优 bug）
- ✅ 生成 5 段式 Markdown 日报（概览 / 高优 bug / 需求进展 / 阻塞项 / 挂起）
- ✅ 双投递通道：Slack Incoming Webhook / 仅落执行日志
- ✅ n8n Cloud 已上线，手动触发已验证（execution id=3，status=success）
- ✅ 离线 runner 同步验证（与 n8n 节点代码同源）

**设计要点**：日报的"事实骨架"完全由代码保证（不凭感觉写），LLM 仅可作为可选
"语气润色"叠加层，不影响正确性。这也是从 n8n 模板库（#9683 把 ticket 全量丢
给 GPT 写报告）观察反模式后的主动设计。

---

## ② Source code / repo

```
meegle-daily-digest/
├── README.md                              ← 部署指南（3 条路径任选）
├── DEPLOYMENT.md                          ← 本文件
├── meegle-daily-digest.n8n-cloud-sdk.js   ⭐ 工作流定义（n8n Workflow SDK）
├── data/mock_items.json                   ← 11 条 mock work_item
├── tools/
│   ├── run_digest.js                      ← 核心逻辑
│   └── fetch_meegle_mcp.js                ← Meegle MCP 客户端
└── demo/self-test-output.txt              ← 快照 + 断言
```

**文件大小**：总计 < 30 KB，无 npm 依赖（Node ≥ 18 即可跑 tools/）。

---

## ③ Demo Recording

**真实数据下的端到端验证已完成**：

**n8n Cloud Execution #3**（2026-10-01 08:59 UTC，触发方式 = 手动，窗口 = 30 天）：

```
*📊 研发日报 · 2026/10/1（团队）*

🔢 *概览*：bug 50（新增 27，关闭 23）；需求推进 4 项
　按优先级：P0 新22/关21 · P1 新2/关2 · P2 新3/关0 · P3 新0/关0

🔴 *高优 bug*（24）
　• `POND-15156915` [P0] 线上 — @ruby（待线上验证）
　• `POND-15125988` [P0] 需求 — @bill.pan,ruby（开始）
　… 及另外 19 个

📈 *需求进展*
　🚧 `POND-13788765` Pond AI Agent Marketplace — @jerry,Devin Yang,Lightman Miao,bill.pan,ruby,Liz Song,depp,Orville Wang（started）

⏰ *挂起提醒*（> 3 天未更新的高优 bug，10 个）
```

**点开看每节点的真实输入输出**：
https://orville-wang.app.n8n.cloud/workflow/rL4J3jp2pyVGdigm
→ 左侧 "Executions" 标签 → id=3

**离线 snapshot**：`demo/self-test-output.txt` 附 6 条断言（优先级排序、
窗口边界、挂起命中等），供 code review 时逐条比对。

---

## ④ Playable prototype URL and access code

- ** Workflow URL**：https://orville-wang.app.n8n.cloud/workflow/rL4J3jp2pyVGdigm
- **Access**：与 Orville 在同一 n8n Cloud 组织即可访问；同事需要权限请联系
  wangaotongji@gmail.com 邀请进 workspace

**如何试**：
1. 打开上面的 URL
2. 点击画布的 "Execute workflow" 按钮（左上）
3. 等 5-8 秒，点击最后一个节点 `Done (log only)` 看 output
4. 或在 "Executions" 标签看最近一次的完整 run 记录

---

## ⑤ Deployment instructions, environment configuration, and test steps

详见 `README.md`（含路径 A/B/C 三条部署选项）。此处摘要：

### 前置要求
- n8n Cloud 账号（或 self-host n8n ≥ 1.0，需能访问 meegle.com）
- Meegle MCP token（找 Meegle 管理员开通）
- 可选：Slack Incoming Webhook（用于真实推送）

### 必要配置（填到 Config 节点）

| 字段 | 示例 |
|---|---|
| `meegle_mcp_token` | `m-AB-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` |
| `meegle_project_key` | `693a4c95897fcda33ebe0175`（Pond Engineering） |
| `meegle_simple_name` | `c4u20i` |

### 测试步骤

- [ ] **T1 冒烟**：UI 点 "Execute workflow"，等 5-8s，看 `Done (log only)` 节点输出含 5 个分节
- [ ] **T2 数据真实性**：打开 `MCP: fetch bugs (issue)` 节点的 output，确认 moql_field_list 非空
- [ ] **T3 高优 bug 正确性**：与 Meegle UI 直接对比近 N 天的 P0/P1 issue 清单
- [ ] **T4 空场景**：把 `window_hours` 改成 `1` 触发一次，应生成"今日无变更"的日报（不报错）
- [ ] **T5 边界**：`window_hours` 改成 `720`（30 天），"高优 bug" 数应不变（活跃 bug 不受窗口影响）
- [ ] **T6 Slack 投递**：配 webhook，`delivery_mode=slack`，确认日报进入测试频道
- [ ] **T7 持续运行**：Activate workflow，观察 1 周每天 09:00 是否按时触发

### ⚠️ 三大坑（部署前必读）

1. **n8n Cloud 默认禁用 `$env`** → 使用 n8n Variables / 硬编码 / Credentials
2. **HTTP 节点串联丢中间结果** → 下游 Code 节点用 `$('NodeName').all()` 跨节点访问
3. **空 items 短路整条链路** → Normalize 输出 sentinel，下游 filter `_empty: true` 处理

---

## ⑥ Any additional operating or maintenance costs?

| 项 | 成本 | 备注 |
|---|---|---|
| n8n Cloud | Pond 已有订阅 | 无增量 |
| Meegle MCP | 内部系统 | $0 |
| Slack Webhook | 免费 | $0 |
| **总增量** | **$0/月** | 无需 Billy 报销 |

如未来要接 LLM 节点做"语气润色"（可选）：GPT-4o-mini，约 $0.30/月。

---

## 附：踩坑记录（对 Pond 平台设计的参考价值）

以下内容摘自部署实际过程，可作为 Pond 平台"Serverless n8n 托管"特性的设计依据：

1. **`N8N_BLOCK_ENV_ACCESS_IN_NODE` 是 n8n Cloud 默认**
   → Pond 平台如托管用户 n8n 工作流，需提供 self-service 的**变量管理 UI**
     （等价 n8n Variables），否则用户只能硬编码密钥（严重的安全问题）

2. **HTTP 节点链式行为不直观**（下游只见紧邻上游）
   → Pond 平台在引导用户组合多个数据源时，应推荐**并行 + Merge** 模式而非链式，
     或在 SDK 层面提供 `$('NodeName').all()` 的跨节点语法糖

3. **空 items 静默短路**（无 error 但下游不跑）
   → Pond 的"试运行"功能应该显式提示 user "上游返回 0 条，下游被跳过"，
     否则用户会以为节点没生效

4. **凭证管理**
   → Meegle MCP token 是长期凭证，应走 n8n **Credentials**（Header Auth 类型），
     不要放进 Set 节点的值里（会导致每次 export workflow 都泄露 token）

---

**提交完毕** ✅
