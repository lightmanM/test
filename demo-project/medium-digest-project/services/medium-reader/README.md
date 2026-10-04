# Medium/Freedium Reader

独立的 Node.js 抓取服务，供 n8n 通过 HTTP 调用。服务接受 Medium、Medium publication 自定义域名及其他公开文章 URL，页面访问使用 Freedium，并通过 CloakBrowser 的 Playwright API 提取正文。

## Run with Docker

```bash
cd medium-reader
docker compose up -d --build
curl http://127.0.0.1:8000/healthz
```

同一台机器上的 Docker n8n 可以通过 `http://host.docker.internal:8000/extract` 调用本服务（Docker Desktop）。如果 n8n 和本服务加入同一个 Docker network，则使用 `http://medium-reader:8000/extract`。

## API

### `GET /healthz`

返回服务存活状态。

### `POST /extract`

请求：

```json
{
  "url": "https://medium.com/@author/article-slug",
  "timeoutMs": 60000
}
```

成功响应：

```json
{
  "sourceUrl": "https://medium.com/@author/article-slug",
  "freediumUrl": "https://freedium-mirror.cfd/https://medium.com/@author/article-slug",
  "title": "Article title",
  "author": "Author",
  "content": "Full article text",
  "contentStatus": "success",
  "error": null
}
```

单篇抓取失败仍返回 HTTP 200，但 `contentStatus` 为 `failed`，便于 n8n 继续处理其他文章。非法 URL、私有/本地 URL 或无效 JSON 返回 4xx。

## Configuration

- `FREEDIUM_BASE_URL`: 默认 `https://freedium-mirror.cfd`。
- `MIN_CONTENT_CHARACTERS`: 判定正文成功的最小字符数，默认 `400`。
- `HEADLESS`: 默认 `true`；仅在调试时设置为 `false`。
- `API_TOKEN`: 可选。设置后，`POST /extract` 必须携带 `Authorization: Bearer <API_TOKEN>`。

浏览器二进制在镜像构建阶段预下载，避免首次 n8n 执行时才下载。Freedium 是外部 beta 服务，页面变化、限流或不可用时会返回 `failed` 状态；此服务不处理登录、验证码或付费账户。

该服务只适用于你有权访问和处理的内容。Medium/Freedium 的服务条款、版权和自动化访问限制不由本项目规避或解决，部署前请自行确认使用场景。
