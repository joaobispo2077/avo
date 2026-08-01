#!/usr/bin/env node
// AVO telemetry — thin Node shim for JS steps (mirrors helpers/telemetry.py).
// Reports disk free / step bytes / cumulative footprint / phase N-of-total /
// rough ETA; prints a human line + an `AVO_JSON` machine line; persists rolling
// stats to .avo/state.json (same shape as the Python reporter).
// Cross-platform: node:path/fs, no hardcoded separators.

import { statfsSync, statSync, readdirSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve, parse as parsePath } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..");
const stateDir = join(repoRoot, ".avo");
const statePath = join(stateDir, "state.json");

export function humanBytes(n) {
  n = Number(n);
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let i = 0;
  if (Math.abs(n) < 1024) return `${Math.round(n)}B`;
  while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(1)}${units[i]}`;
}

export function humanDuration(seconds) {
  if (seconds == null) return "unknown";
  seconds = Math.round(seconds);
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60), s = seconds % 60;
  if (m < 60) return `${m}m${String(s).padStart(2, "0")}s`;
  const h = Math.floor(m / 60), mm = m % 60;
  return `${h}h${String(mm).padStart(2, "0")}m`;
}

export function dirSize(target) {
  try {
    const st = statSync(target);
    if (st.isFile()) return st.size;
  } catch { return 0; }
  let total = 0;
  const stack = [target];
  while (stack.length) {
    const cur = stack.pop();
    let entries;
    try { entries = readdirSync(cur, { withFileTypes: true }); } catch { continue; }
    for (const e of entries) {
      const p = join(cur, e.name);
      if (e.isSymbolicLink()) continue;
      if (e.isDirectory()) stack.push(p);
      else if (e.isFile()) { try { total += statSync(p).size; } catch { /* ignore */ } }
    }
  }
  return total;
}

export function diskFree(target) {
  const probe = target && existsSync(target) ? target : (parsePath(resolve(target || ".")).root || process.cwd());
  try {
    const s = statfsSync(probe);
    return Number(s.bsize) * Number(s.bavail);
  } catch { return -1; }
}

function nowIso() { return new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); }

function packageVersion() {
  try {
    return JSON.parse(readFileSync(join(repoRoot, "package.json"), "utf8")).version || "0.0.0";
  } catch { return "0.0.0"; }
}

function loadState() {
  const base = { version: packageVersion(), lastUpdateCheck: null, transcription: {}, stats: {} };
  try { return { ...base, ...JSON.parse(readFileSync(statePath, "utf8")) }; }
  catch { return base; }
}

function saveState(state) {
  if (!existsSync(stateDir)) mkdirSync(stateDir, { recursive: true });
  writeFileSync(statePath, JSON.stringify(state, null, 2) + "\n", "utf8");
}

const _start = process.hrtime.bigint();

export function report(phase, {
  createdBytes = 0, note = "", index = null, total = null, volume = null, emit = true,
} = {}) {
  const vol = volume || repoRoot;
  const free = diskFree(vol);

  const state = loadState();
  const stats = state.stats || {};
  const cumulative = Number(stats.cumulativeBytes || 0) + Number(createdBytes);
  const phases = stats.phases || [];

  const idx = index ?? (phases.length + 1);
  const percent = idx && total ? (idx / total) * 100 : null;

  let etaSeconds = null;
  if (idx && total && idx > 0 && idx < total) {
    const elapsed = Number(process.hrtime.bigint() - _start) / 1e9;
    etaSeconds = (elapsed / idx) * (total - idx);
  }

  const record = {
    phase, index: idx, total, createdBytes: Number(createdBytes),
    cumulativeBytes: cumulative, diskFreeBytes: free, note, ts: nowIso(),
    percent: percent == null ? null : Math.round(percent * 10) / 10,
    etaSeconds: etaSeconds == null ? null : Math.round(etaSeconds * 10) / 10,
  };

  phases.push({ phase, index: idx, createdBytes: Number(createdBytes), ts: record.ts });
  stats.phases = phases.slice(-200);
  stats.cumulativeBytes = cumulative;
  state.stats = stats;
  saveState(state);

  if (emit) {
    const label = total ? `[${idx}/${total}]` : `[${idx}]`;
    const pct = percent == null ? "" : ` ${Math.round(percent)}%`;
    let line = `${label}${pct} ${phase} | +${humanBytes(createdBytes)} step | ${humanBytes(cumulative)} total | ${humanBytes(free)} free | ETA ${humanDuration(etaSeconds)}`;
    if (note) line += ` | ${note}`;
    console.log(line);
    console.error("AVO_JSON " + JSON.stringify(record));
  }
  return record;
}

export function learndown({ usedBytes = 0, freedBytes = 0, preservedBytes = null, note = "", emit = true } = {}) {
  const net = Number(usedBytes) - Number(freedBytes);
  const record = {
    event: "learndown", usedBytes: Number(usedBytes), freedBytes: Number(freedBytes),
    netBytes: net, preservedBytes: preservedBytes == null ? null : Number(preservedBytes), ts: nowIso(),
  };
  const state = loadState();
  const stats = state.stats || {};
  stats.lastLearndown = record;
  state.stats = stats;
  saveState(state);

  if (emit) {
    const preserved = preservedBytes == null ? "" : ` | preserved ${humanBytes(preservedBytes)}`;
    const sign = net >= 0 ? "-" : "+";
    console.log(`learndown | used ${humanBytes(usedBytes)} | freed ${humanBytes(freedBytes)} | net ${sign}${humanBytes(Math.abs(net))}${preserved}` + (note ? ` | ${note}` : ""));
    console.error("AVO_JSON " + JSON.stringify(record));
  }
  return record;
}

// ---- tiny CLI ---------------------------------------------------------------
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) { const k = a.slice(2); const v = (i + 1 < argv.length && !argv[i + 1].startsWith("--")) ? argv[++i] : "true"; out[k] = v; }
  }
  return out;
}

if (import.meta.url === `file://${process.argv[1]}` || process.argv[1] === fileURLToPath(import.meta.url)) {
  const [cmd, ...rest] = process.argv.slice(2);
  const a = parseArgs(rest);
  if (cmd === "report") {
    const created = a["created-path"] ? dirSize(a["created-path"]) : Number(a["created-bytes"] || 0);
    report(a.phase || "phase", {
      createdBytes: created, note: a.note || "",
      index: a.index ? Number(a.index) : null, total: a.total ? Number(a.total) : null,
      volume: a.volume || null,
    });
  } else if (cmd === "learndown") {
    const preserved = a["preserved-path"] ? dirSize(a["preserved-path"]) : (a.preserved != null ? Number(a.preserved) : null);
    learndown({ usedBytes: Number(a.used || 0), freedBytes: Number(a.freed || 0), preservedBytes: preserved, note: a.note || "" });
  } else {
    console.error("usage: node helpers/telemetry.mjs <report|learndown> [--flags]");
    process.exit(2);
  }
}
