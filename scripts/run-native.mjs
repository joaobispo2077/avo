#!/usr/bin/env node
// AVO — dispatch a native script (scripts/<name>.ps1 on Windows,
// scripts/<name>.sh elsewhere), forwarding any extra args unchanged.
// Used by package.json wrappers (e.g. `npm run setup -- --lang pt`).
// Cross-platform: path built with node:path; no hardcoded separators.

import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { existsSync } from "node:fs";

const scriptsDir = dirname(fileURLToPath(import.meta.url));

const [name, ...forwarded] = process.argv.slice(2);
if (!name) {
  console.error("usage: node scripts/run-native.mjs <script-name> [args...]");
  process.exit(2);
}

const isWindows = process.platform === "win32";

function which(cmd) {
  const probe = isWindows ? "where" : "command";
  const args = isWindows ? [cmd] : ["-v", cmd];
  const r = spawnSync(probe, args, { stdio: "ignore", shell: isWindows });
  return r.status === 0;
}

let cmd;
let args;

if (isWindows) {
  const ps1 = join(scriptsDir, `${name}.ps1`);
  if (!existsSync(ps1)) {
    console.error(`native script not found: ${ps1}`);
    process.exit(2);
  }
  const shell = which("pwsh") ? "pwsh" : "powershell";
  cmd = shell;
  args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, ...forwarded];
} else {
  const sh = join(scriptsDir, `${name}.sh`);
  if (!existsSync(sh)) {
    console.error(`native script not found: ${sh}`);
    process.exit(2);
  }
  cmd = "bash";
  args = [sh, ...forwarded];
}

const result = spawnSync(cmd, args, { stdio: "inherit" });
if (result.error) {
  console.error(`failed to launch ${cmd}: ${result.error.message}`);
  process.exit(1);
}
process.exit(result.status ?? 1);
