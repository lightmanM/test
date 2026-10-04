const DEFAULT_FREEDIUM_BASE_URL = 'https://freedium-mirror.cfd';

function isPrivateHostname(hostname) {
  const ipv4 = hostname.split('.').map((part) => Number(part));
  const isIpv4 = ipv4.length === 4 && ipv4.every((part) => Number.isInteger(part) && part >= 0 && part <= 255);
  if (isIpv4) {
    return ipv4[0] === 10
      || ipv4[0] === 127
      || (ipv4[0] === 169 && ipv4[1] === 254)
      || (ipv4[0] === 172 && ipv4[1] >= 16 && ipv4[1] <= 31)
      || (ipv4[0] === 192 && ipv4[1] === 168);
  }

  return hostname === 'localhost'
    || hostname.endsWith('.localhost')
    || hostname.endsWith('.local')
    || hostname === '::1'
    || hostname === '[::1]'
    || hostname.startsWith('fc')
    || hostname.startsWith('fd')
    || hostname.startsWith('fe80:');
}

export function normalizeSourceUrl(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 4096) {
    throw new Error('url must be a non-empty string no longer than 4096 characters');
  }

  const url = new URL(value);
  if (!['http:', 'https:'].includes(url.protocol)) {
    throw new Error('url must use http or https');
  }

  const hostname = url.hostname.toLowerCase();
  if (isPrivateHostname(hostname)) {
    throw new Error('private or local URLs are not allowed');
  }

  url.hash = '';
  return url.toString();
}

export function buildFreediumUrls(sourceUrl, baseUrl = DEFAULT_FREEDIUM_BASE_URL) {
  const base = new URL(baseUrl);
  if (!['http:', 'https:'].includes(base.protocol)) {
    throw new Error('FREEDIUM_BASE_URL must use http or https');
  }

  const prefix = base.toString().replace(/\/$/, '');
  const raw = `${prefix}/${sourceUrl}`;
  const encoded = `${prefix}/${encodeURIComponent(sourceUrl)}`;
  return [...new Set([raw, encoded])];
}

export function clampTimeout(value, fallback = 60000) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(Math.max(Math.round(parsed), 5000), 120000);
}

export const defaultFreediumBaseUrl = DEFAULT_FREEDIUM_BASE_URL;
