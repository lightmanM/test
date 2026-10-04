import http from 'node:http';
import { launch } from 'cloakbrowser';
import {
  buildFreediumUrls,
  clampTimeout,
  defaultFreediumBaseUrl,
  normalizeSourceUrl,
} from './core.mjs';

const host = process.env.HOST ?? '0.0.0.0';
const port = Number(process.env.PORT ?? 8000);
const freediumBaseUrl = process.env.FREEDIUM_BASE_URL ?? defaultFreediumBaseUrl;
const apiToken = process.env.API_TOKEN;
const maxBodyBytes = 64 * 1024;
const minContentCharacters = Number(process.env.MIN_CONTENT_CHARACTERS ?? 400);

let browserPromise;
let extractionQueue = Promise.resolve();

function sendJson(response, statusCode, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
  });
  response.end(body);
}

function readJson(request) {
  return new Promise((resolve, reject) => {
    let size = 0;
    let body = '';

    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      size += Buffer.byteLength(chunk);
      if (size > maxBodyBytes) {
        reject(Object.assign(new Error('request body is too large'), { statusCode: 413 }));
        request.destroy();
        return;
      }
      body += chunk;
    });
    request.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(Object.assign(new Error('request body must be valid JSON'), { statusCode: 400 }));
      }
    });
    request.on('error', reject);
  });
}

async function getBrowser() {
  if (!browserPromise) {
    browserPromise = launch({
      headless: process.env.HEADLESS !== 'false',
      humanize: false,
    }).catch((error) => {
      browserPromise = undefined;
      throw error;
    });
  }
  return browserPromise;
}

function enqueueExtraction(task) {
  const next = extractionQueue.then(task, task);
  extractionQueue = next.catch(() => undefined);
  return next;
}

async function extractPage(page, timeoutMs) {
  await page.waitForLoadState('domcontentloaded', { timeout: timeoutMs }).catch(() => undefined);
  await page.waitForTimeout(750);

  return page.evaluate(() => {
    const selectors = [
      'article',
      'main',
      '[role="main"]',
      '.article-content',
      '[class*="article-body"]',
      '[class*="post-content"]',
    ];

    const cleanText = (node) => {
      const clone = node.cloneNode(true);
      clone.querySelectorAll('script,style,noscript,nav,header,footer,aside,form,button').forEach((item) => item.remove());
      return (clone.innerText || clone.textContent || '').replace(/\n{3,}/g, '\n\n').trim();
    };

    const candidates = selectors
      .flatMap((selector) => [...document.querySelectorAll(selector)])
      .map((node) => cleanText(node))
      .filter(Boolean)
      .sort((a, b) => b.length - a.length);

    const bodyText = cleanText(document.body);
    const content = candidates[0] ?? bodyText;
    const title = document.querySelector('h1')?.textContent?.trim()
      || document.querySelector('meta[property="og:title"]')?.getAttribute('content')?.trim()
      || document.title?.trim()
      || null;
    const author = document.querySelector('meta[name="author"]')?.getAttribute('content')?.trim()
      || document.querySelector('[rel="author"]')?.textContent?.trim()
      || null;

    return { title, author, content };
  });
}

async function extractArticle(sourceUrl, timeoutMs) {
  const browser = await getBrowser();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  let lastError = 'Freedium returned no article text';
  let lastFreediumUrl;

  try {
    for (const freediumUrl of buildFreediumUrls(sourceUrl, freediumBaseUrl)) {
      lastFreediumUrl = freediumUrl;
      try {
        await page.goto(freediumUrl, { waitUntil: 'domcontentloaded', timeout: timeoutMs });
        const extracted = await extractPage(page, timeoutMs);
        if (extracted.content && extracted.content.length >= minContentCharacters) {
          return {
            sourceUrl,
            freediumUrl,
            title: extracted.title,
            author: extracted.author,
            content: extracted.content,
            contentStatus: 'success',
            error: null,
          };
        }
        lastError = 'Freedium page contained insufficient article text';
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
    }
  } finally {
    await page.close().catch(() => undefined);
  }

  return {
    sourceUrl,
    freediumUrl: lastFreediumUrl,
    title: null,
    author: null,
    content: null,
    contentStatus: 'failed',
    error: lastError,
  };
}

async function handleExtract(request, response) {
  if (apiToken && request.headers.authorization !== `Bearer ${apiToken}`) {
    sendJson(response, 401, { error: 'unauthorized' });
    return;
  }

  let input;
  try {
    input = await readJson(request);
    const sourceUrl = normalizeSourceUrl(input.url ?? input.sourceUrl);
    const timeoutMs = clampTimeout(input.timeoutMs);
    const result = await enqueueExtraction(() => extractArticle(sourceUrl, timeoutMs));
    sendJson(response, 200, result);
  } catch (error) {
    const statusCode = error.statusCode ?? 400;
    sendJson(response, statusCode, {
      contentStatus: 'failed',
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

const server = http.createServer(async (request, response) => {
  if (request.method === 'GET' && request.url === '/healthz') {
    sendJson(response, 200, { status: 'ok', service: 'medium-freedium-reader' });
    return;
  }

  if (request.method === 'POST' && request.url === '/extract') {
    await handleExtract(request, response);
    return;
  }

  sendJson(response, 404, { error: 'not_found' });
});

async function shutdown(signal) {
  server.close();
  if (browserPromise) {
    const browser = await browserPromise.catch(() => undefined);
    await browser?.close().catch(() => undefined);
  }
  console.log(`received ${signal}, shut down`);
  process.exit(0);
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));

server.listen(port, host, () => {
  console.log(`medium-freedium-reader listening on http://${host}:${port}`);
});

export { extractArticle };
