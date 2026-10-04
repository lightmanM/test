const items = $input.all();
const links = new Map();
let bodyCount = 0;
let candidateCount = 0;
let parseFailureCount = 0;
let rejectedCount = 0;
const blockedHosts = new Set([
  'mail.google.com',
  'support.google.com',
  'help.medium.com',
  'about.medium.com',
  'twitter.com',
  'x.com',
  'facebook.com',
  'linkedin.com',
]);

function decodeHtml(value) {
  return value
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>');
}

function decodeBase64Url(value) {
  try {
    return Buffer.from(value.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - value.length % 4) % 4), 'base64').toString('utf8');
  } catch {
    return '';
  }
}

function collectPayloadText(part, output) {
  if (!part || typeof part !== 'object') return;
  const mimeType = String(part.mimeType || '').toLowerCase();
  const data = part.body?.data;
  if (data && (mimeType === 'text/html' || mimeType === 'text/plain')) output.push(decodeBase64Url(data));
  for (const child of part.parts || []) collectPayloadText(child, output);
}

function cleanText(value) {
  return (value || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
}

function getEmailTimestamp(message) {
  const rawValue = message.internalDate ?? message.date ?? message.headers?.date;
  if (typeof rawValue === 'number' && Number.isFinite(rawValue)) return rawValue;
  const rawText = String(rawValue || '').replace(/^Date:\s*/i, '').trim();
  const timestamp = Date.parse(rawText);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function isArticleUrl(parsed, anchorText) {
  const host = parsed.hostname.toLowerCase();
  const parts = parsed.pathname.split('/').filter(Boolean);
  if (blockedHosts.has(host) || parts.length === 0) return false;

  const lastPart = parts.at(-1) || '';
  const hasMediumArticleId = /-[a-f0-9]{8,}$/i.test(lastPart);
  const isMediumHost = host === 'medium.com' || host.endsWith('.medium.com');
  if (isMediumHost) return parts.length >= 2 && hasMediumArticleId;

  const hasArticleLikeSlug = lastPart.length >= 24 && /[a-z]/i.test(lastPart);
  return anchorText.length >= 20 || hasArticleLikeSlug || hasMediumArticleId;
}

function parseHttpUrl(rawHref) {
  const match = rawHref.match(/^(https?):\/\/([^/?#]+)(\/[^?#]*)?(\?[^#]*)?(#.*)?$/i);
  if (!match) return null;
  const hostPort = match[2].split('@').pop();
  const hostname = hostPort.replace(/^\[|\]$/g, '').split(':')[0].toLowerCase();
  return {
    protocol: `${match[1].toLowerCase()}:`,
    hostname,
    pathname: match[3] || '/',
    query: (match[4] || '').slice(1),
  };
}

function normaliseUrl(rawHref) {
  const href = decodeHtml(rawHref).replace(/[),.;]+$/, '');
  const parsed = parseHttpUrl(href);
  if (!parsed || !['http:', 'https:'].includes(parsed.protocol)) return null;
  const keptQuery = parsed.query
    .split('&')
    .filter(Boolean)
    .filter((part) => !/^(utm_|source|ref|sk)/i.test(part.split('=')[0]))
    .join('&');
  return {
    parsed,
    url: `${parsed.protocol}//${href.match(/^(https?):\/\/([^/?#]+)/i)[2]}${parsed.pathname}${keptQuery ? `?${keptQuery}` : ''}`,
  };
}

function addLink(rawHref, rawText, emailDate, emailTimestamp) {
  candidateCount += 1;
  try {
    const normalised = normaliseUrl(rawHref);
    if (!normalised) {
      rejectedCount += 1;
      return;
    }
    const { parsed, url } = normalised;
    const anchorText = cleanText(rawText);
    if (!isArticleUrl(parsed, anchorText)) {
      rejectedCount += 1;
      return;
    }
    const existing = links.get(url);
    if (!existing || emailTimestamp >= existing.emailTimestamp) {
      links.set(url, {
        digestTitle: anchorText || url,
        emailDate,
        emailTimestamp,
      });
    }
  } catch {
    parseFailureCount += 1;
  }
}

for (const item of items) {
  const bodies = [];
  const topLevel = item.json || {};
  const emailTimestamp = getEmailTimestamp(topLevel);
  const emailDate = emailTimestamp ? new Date(emailTimestamp).toISOString() : null;
  for (const value of [topLevel.html, topLevel.textAsHtml, topLevel.text, topLevel.snippet]) {
    if (typeof value === 'string') bodies.push(value);
  }
  collectPayloadText(topLevel.payload, bodies);
  for (const body of bodies) {
    bodyCount += 1;
    const anchorPattern = /<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)<\/a>/gi;
    for (const match of body.matchAll(anchorPattern)) addLink(match[1], match[2], emailDate, emailTimestamp);
    for (const match of body.matchAll(/https?:\/\/[^\s<>\"']+/g)) addLink(match[0], '', emailDate, emailTimestamp);
  }
}

const articles = [...links.entries()]
  .sort(([, left], [, right]) => right.emailTimestamp - left.emailTimestamp)
  .slice(0, 100)
  .map(([url, details]) => ({
    url,
    digestTitle: details.digestTitle,
    emailDate: details.emailDate,
    emailTimestamp: details.emailTimestamp,
    contentStatus: 'pending',
  }));

if (articles.length === 0) {
  return [{ json: {
    noArticles: true,
    articleCount: 0,
    debug: {
      inputItems: items.length,
      bodyCount,
      candidateCount,
      parseFailureCount,
      rejectedCount,
      bufferType: typeof Buffer,
      firstItemKeys: Object.keys(items[0]?.json || {}),
      firstItemHtmlType: typeof items[0]?.json?.html,
      firstItemHtmlLength: typeof items[0]?.json?.html === 'string' ? items[0].json.html.length : 0,
    },
  } }];
}
return articles.map((article) => ({ json: { ...article, articleCount: articles.length } }));
