#!/usr/bin/env node
// AVO telemetry — thin Node shim for JS steps (mirrors helpers/telemetry.py).
// Reports disk free / step bytes / cumulative footprint / phase N-of-total /
// rough ETA; prints a human line + an `AVO_JSON` machine line; persists rolling
// stats to .avo/state.json (same shape as the Python reporter).
// Cross-platform: node:path/fs, no hardcoded separators.

import {
  statfsSync,
  statSync,
  readdirSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve, parse as parsePath } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, '..');
const stateDir = join(repoRoot, '.avo');
const statePath = join(stateDir, 'state.json');

export function humanBytes(n) {
  n = Number(n);
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let i = 0;
  if (Math.abs(n) < 1024) return `${Math.round(n)}B`;
  while (Math.abs(n) >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(1)}${units[i]}`;
}

export function humanDuration(seconds) {
  if (seconds == null) return 'unknown';
  seconds = Math.round(seconds);
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (m < 60) return `${m}m${String(s).padStart(2, '0')}s`;
  const h = Math.floor(m / 60);
  const mm = m % 60;
  return `${h}h${String(mm).padStart(2, '0')}m`;
}

function fileSizeOrZero(p) {
  try {
    return statSync(p).size;
  } catch {
    return 0;
  }
}

function walkDirSize(root) {
  let total = 0;
  const stack = [root];
  while (stack.length) {
    const cur = stack.pop();
    let entries;
    try {
      entries = readdirSync(cur, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of entries) {
      const p = join(cur, e.name);
      if (e.isSymbolicLink()) continue;
      if (e.isDirectory()) stack.push(p);
      else if (e.isFile()) total += fileSizeOrZero(p);
    }
  }
  return total;
}

export function dirSize(target) {
  try {
    const st = statSync(target);
    if (st.isFile()) return st.size;
  } catch {
    return 0;
  }
  return walkDirSize(target);
}

export function diskFree(target) {
  const probe =
    target && existsSync(target)
      ? target
      : parsePath(resolve(target || '.')).root || process.cwd();
  try {
    const s = statfsSync(probe);
    return Number(s.bsize) * Number(s.bavail);
  } catch {
    return -1;
  }
}

function nowIso() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function packageVersion() {
  try {
    return (
      JSON.parse(readFileSync(join(repoRoot, 'package.json'), 'utf8'))
        .version || '0.0.0'
    );
  } catch {
    return '0.0.0';
  }
}

function loadState() {
  const base = {
    version: packageVersion(),
    lastUpdateCheck: null,
    transcription: {},
    stats: {},
  };
  try {
    return { ...base, ...JSON.parse(readFileSync(statePath, 'utf8')) };
  } catch {
    return base;
  }
}

function saveState(state) {
  if (!existsSync(stateDir)) mkdirSync(stateDir, { recursive: true });
  writeFileSync(statePath, JSON.stringify(state, null, 2) + '\n', 'utf8');
}

const _start = process.hrtime.bigint();

function round1(n) {
  return Math.round(n * 10) / 10;
}

function computeEta(idx, total) {
  if (!(idx && total && idx > 0 && idx < total)) return null;
  const elapsed = Number(process.hrtime.bigint() - _start) / 1e9;
  return round1((elapsed / idx) * (total - idx));
}

function emitReportLine(record, createdBytes, cumulative, free, note) {
  const { index: idx, total, phase, percent } = record;
  const label = total ? `[${idx}/${total}]` : `[${idx}]`;
  const pct = percent == null ? '' : ` ${Math.round(percent)}%`;
  let line = `${label}${pct} ${phase} | +${humanBytes(createdBytes)} step | ${humanBytes(cumulative)} total | ${humanBytes(free)} free | ETA ${humanDuration(record.etaSeconds)}`;
  if (note) line += ` | ${note}`;
  console.log(line);
  console.error('AVO_JSON ' + JSON.stringify(record));
}

function normalizeReportOptions(options) {
  const opts = options == null ? {} : options;
  return {
    createdBytes: Number(opts.createdBytes == null ? 0 : opts.createdBytes),
    note: opts.note == null ? '' : opts.note,
    index: opts.index == null ? null : opts.index,
    total: opts.total == null ? null : opts.total,
    volume: opts.volume == null ? null : opts.volume,
    emit: opts.emit == null ? true : opts.emit,
  };
}

function nextPhaseIndex(index, phases) {
  if (index == null) return phases.length + 1;
  return index;
}

function phasePercent(idx, total) {
  if (!idx || !total) return null;
  return round1((idx / total) * 100);
}

function buildReportRecord(phase, opts, free, stats) {
  const phases = stats.phases == null ? [] : stats.phases;
  const prior = Number(
    stats.cumulativeBytes == null ? 0 : stats.cumulativeBytes,
  );
  const idx = nextPhaseIndex(opts.index, phases);
  return {
    phase,
    index: idx,
    total: opts.total,
    createdBytes: opts.createdBytes,
    cumulativeBytes: prior + opts.createdBytes,
    diskFreeBytes: free,
    note: opts.note,
    ts: nowIso(),
    percent: phasePercent(idx, opts.total),
    etaSeconds: computeEta(idx, opts.total),
  };
}

function persistReportPhase(record) {
  const state = loadState();
  const stats = state.stats == null ? {} : state.stats;
  const phases = stats.phases == null ? [] : stats.phases;
  phases.push({
    phase: record.phase,
    index: record.index,
    createdBytes: record.createdBytes,
    ts: record.ts,
  });
  stats.phases = phases.slice(-200);
  stats.cumulativeBytes = record.cumulativeBytes;
  state.stats = stats;
  saveState(state);
}

export function report(phase, options) {
  const opts = normalizeReportOptions(options);
  const free = diskFree(opts.volume == null ? repoRoot : opts.volume);
  const state = loadState();
  const stats = state.stats == null ? {} : state.stats;
  const record = buildReportRecord(phase, opts, free, stats);
  persistReportPhase(record);
  if (opts.emit) {
    emitReportLine(
      record,
      opts.createdBytes,
      record.cumulativeBytes,
      free,
      opts.note,
    );
  }
  return record;
}

function emitLearndownLine(
  record,
  usedBytes,
  freedBytes,
  preservedBytes,
  note,
) {
  const preserved =
    preservedBytes == null ? '' : ` | preserved ${humanBytes(preservedBytes)}`;
  const sign = record.netBytes >= 0 ? '-' : '+';
  console.log(
    `learndown | used ${humanBytes(usedBytes)} | freed ${humanBytes(freedBytes)} | net ${sign}${humanBytes(Math.abs(record.netBytes))}${preserved}` +
      (note ? ` | ${note}` : ''),
  );
  console.error('AVO_JSON ' + JSON.stringify(record));
}

function normalizeLearndownOptions(options) {
  const opts = options == null ? {} : options;
  return {
    usedBytes: Number(opts.usedBytes == null ? 0 : opts.usedBytes),
    freedBytes: Number(opts.freedBytes == null ? 0 : opts.freedBytes),
    preservedBytes:
      opts.preservedBytes == null ? null : Number(opts.preservedBytes),
    note: opts.note == null ? '' : opts.note,
    emit: opts.emit == null ? true : opts.emit,
  };
}

export function learndown(options) {
  const opts = normalizeLearndownOptions(options);
  const record = {
    event: 'learndown',
    usedBytes: opts.usedBytes,
    freedBytes: opts.freedBytes,
    netBytes: opts.usedBytes - opts.freedBytes,
    preservedBytes: opts.preservedBytes,
    ts: nowIso(),
  };
  const state = loadState();
  const stats = state.stats == null ? {} : state.stats;
  stats.lastLearndown = record;
  state.stats = stats;
  saveState(state);

  if (opts.emit) {
    emitLearndownLine(
      record,
      opts.usedBytes,
      opts.freedBytes,
      opts.preservedBytes,
      opts.note,
    );
  }
  return record;
}

// ---- tiny CLI ---------------------------------------------------------------
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const k = a.slice(2);
      const v =
        i + 1 < argv.length && !argv[i + 1].startsWith('--')
          ? argv[++i]
          : 'true';
      out[k] = v;
    }
  }
  return out;
}

function resolvePreservedBytes(a) {
  if (a['preserved-path']) return dirSize(a['preserved-path']);
  if (a.preserved != null) return Number(a.preserved);
  return null;
}

function runReportCli(a) {
  const created = a['created-path']
    ? dirSize(a['created-path'])
    : Number(a['created-bytes'] || 0);
  report(a.phase || 'phase', {
    createdBytes: created,
    note: a.note || '',
    index: a.index ? Number(a.index) : null,
    total: a.total ? Number(a.total) : null,
    volume: a.volume || null,
  });
}

function runLearndownCli(a) {
  learndown({
    usedBytes: Number(a.used || 0),
    freedBytes: Number(a.freed || 0),
    preservedBytes: resolvePreservedBytes(a),
    note: a.note || '',
  });
}

function runCli() {
  const [cmd, ...rest] = process.argv.slice(2);
  const a = parseArgs(rest);
  if (cmd === 'report') {
    runReportCli(a);
    return;
  }
  if (cmd === 'learndown') {
    runLearndownCli(a);
    return;
  }
  console.error(
    'usage: node helpers/telemetry.mjs <report|learndown> [--flags]',
  );
  process.exit(2);
}

if (
  import.meta.url === `file://${process.argv[1]}` ||
  process.argv[1] === fileURLToPath(import.meta.url)
) {
  runCli();
}
