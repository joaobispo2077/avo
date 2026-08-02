#!/usr/bin/env node
/**
 * Set pyproject.toml [project].version to match semantic-release next version.
 * Usage: node scripts/ci/sync-pyproject-version.mjs <version>
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const version = process.argv[2];
if (!version) {
  console.error('usage: sync-pyproject-version.mjs <version>');
  process.exit(1);
}

const root = resolve(import.meta.dirname, '../..');
const path = resolve(root, 'pyproject.toml');
const text = readFileSync(path, 'utf8');
const next = text.replace(
  /^version\s*=\s*"[^"]+"/m,
  `version = "${version}"`,
);
if (next === text) {
  console.error('error: could not update version in pyproject.toml');
  process.exit(1);
}
writeFileSync(path, next, 'utf8');
console.log(`pyproject.toml version -> ${version}`);
