import test from 'node:test';
import assert from 'node:assert/strict';
import { buildFreediumUrls, clampTimeout, normalizeSourceUrl } from '../src/core.mjs';

test('accepts Medium and custom-domain URLs and removes fragments', () => {
  assert.equal(
    normalizeSourceUrl('https://medium.com/example/story#comments'),
    'https://medium.com/example/story',
  );
  assert.equal(normalizeSourceUrl('https://blog.medium.com/story'), 'https://blog.medium.com/story');
  assert.equal(normalizeSourceUrl('https://example.org/publication/story'), 'https://example.org/publication/story');
});

test('rejects unsafe URLs', () => {
  assert.throws(() => normalizeSourceUrl('http://127.0.0.1:8000/secret'), /private or local/);
  assert.throws(() => normalizeSourceUrl('http://service.local/article'), /private or local/);
  assert.throws(() => normalizeSourceUrl('javascript:alert(1)'), /http or https/);
});

test('builds raw and encoded Freedium URLs', () => {
  const urls = buildFreediumUrls('https://medium.com/example/story');
  assert.equal(urls.length, 2);
  assert.match(urls[0], /^https:\/\/freedium-mirror\.cfd\/https:\/\/medium\.com/);
  assert.match(urls[1], /%3A%2F%2Fmedium\.com/);
});

test('clamps extraction timeout', () => {
  assert.equal(clampTimeout(1000), 5000);
  assert.equal(clampTimeout(60000), 60000);
  assert.equal(clampTimeout(999999), 120000);
});
