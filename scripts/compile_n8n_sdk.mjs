#!/usr/bin/env node
// Compile an n8n Workflow-SDK source file (export default workflow(...)) to n8n workflow JSON.
//
// Usage (from repo root, after `npm install --prefix scripts`):
//   node scripts/compile_n8n_sdk.mjs <sdk-source.js> <output.json>
//
// The SDK source imports '@n8n/workflow-sdk', which only resolves next to scripts/node_modules,
// so the source is copied into scripts/ under a temporary name before importing it.

import { copyFileSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const [, , source, output] = process.argv;
if (!source || !output) {
  console.error('usage: node scripts/compile_n8n_sdk.mjs <sdk-source.js> <output.json>');
  process.exit(2);
}

const scriptsDir = dirname(fileURLToPath(import.meta.url));
const tmp = join(scriptsDir, `.tmp-${process.pid}-${basename(source).replace(/\.[cm]?js$/, '')}.mjs`);

try {
  copyFileSync(resolve(source), tmp);
  const mod = await import(pathToFileURL(tmp).href);
  const json = mod.default.toJSON();
  mkdirSync(dirname(resolve(output)), { recursive: true });
  writeFileSync(resolve(output), JSON.stringify(json, null, 2) + '\n');
  console.log(`compiled ${source} -> ${output} (${json.nodes.length} nodes)`);
} finally {
  rmSync(tmp, { force: true });
}
