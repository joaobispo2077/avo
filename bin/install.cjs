#!/usr/bin/env node
/**
 * AVO unified cross-platform installer.
 *
 * Local:  node bin/install.cjs [flags]
 * curl:   curl -fsSL .../scripts/install/install.sh | bash
 * Windows: irm .../scripts/install/install.ps1 | iex
 *
 * Pure Node stdlib. Node ≥18 required.
 */
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const cp = require('child_process');
const crypto = require('crypto');
const zlib = require('zlib');

const REPO = process.env.AVO_INSTALL_REPO || 'joaobispo2077/avo';
const PINNED_REF = process.env.AVO_INSTALL_REF || 'main';

const PROVIDERS = [
  {
    id: 'cursor',
    label: 'Cursor',
    profile: 'cursor',
    skills: true,
    commands: true,
    detect: ['command:cursor', 'macapp:Cursor', 'dir:~/.cursor'],
  },
  {
    id: 'claude',
    label: 'Claude Code',
    profile: 'claude',
    skills: true,
    detect: ['command:claude', 'dir:~/.claude'],
  },
  {
    id: 'codex',
    label: 'Codex CLI',
    profile: 'codex',
    skills: true,
    detect: ['command:codex'],
  },
  {
    id: 'windsurf',
    label: 'Windsurf',
    profile: 'windsurf',
    skills: true,
    detect: ['command:windsurf', 'macapp:Windsurf'],
  },
  {
    id: 'cline',
    label: 'Cline',
    profile: 'cline',
    skills: true,
    detect: ['vscode-ext:saoudrizwan.claude-dev', 'vscode-ext:cline'],
  },
  {
    id: 'gemini',
    label: 'Gemini CLI',
    profile: 'gemini',
    skills: true,
    detect: ['command:gemini'],
  },
  {
    id: 'opencode',
    label: 'OpenCode',
    profile: 'opencode',
    skills: true,
    detect: ['command:opencode'],
  },
];

function die(msg) {
  console.error(msg);
  process.exit(1);
}

function expandHome(p) {
  if (!p) return p;
  if (p.startsWith('~/')) return path.join(os.homedir(), p.slice(2));
  if (p === '~') return os.homedir();
  return p;
}

const BOOL_FLAGS = {
  '--dry-run': 'dryRun',
  '--full': 'full',
  '--yes': 'yes',
  '-y': 'yes',
  '--list': 'listOnly',
  '--uninstall': 'uninstall',
  '-u': 'uninstall',
  '-h': 'help',
  '--help': 'help',
};

function parseArgs(argv) {
  const opts = {
    dryRun: false,
    full: false,
    lang: '',
    yes: false,
    listOnly: false,
    only: [],
    uninstall: false,
    help: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--') continue;
    if (a === '--lang') {
      opts.lang = argv[++i] || '';
      continue;
    }
    if (a === '--only') {
      const v = argv[++i];
      if (!v) die('error: --only requires an agent id');
      opts.only.push(v);
      continue;
    }
    const key = BOOL_FLAGS[a];
    if (!key) {
      die(`error: unknown flag: ${a}\nrun 'node bin/install.cjs --help'`);
    }
    opts[key] = true;
  }
  return opts;
}

function hasCommand(name) {
  // Installer must probe PATH for agent CLIs (where / command -v).
  try {
    if (process.platform === 'win32') {
      // eslint-disable-next-line sonarjs/no-os-command-from-path -- intentional PATH probe
      cp.execFileSync('where', [name], { stdio: 'ignore', shell: true });
    } else {
      // eslint-disable-next-line sonarjs/no-os-command-from-path -- intentional PATH probe
      cp.execFileSync('sh', ['-c', `command -v ${name}`], { stdio: 'ignore' });
    }
    return true;
  } catch {
    return false;
  }
}

function hasMacApp(name) {
  if (process.platform !== 'darwin') return false;
  return fs.existsSync(path.join('/Applications', `${name}.app`));
}

function hasDir(rel) {
  const p = expandHome(rel);
  return fs.existsSync(p) && fs.statSync(p).isDirectory();
}

function hasVSCodeExt(fragment) {
  const bases = [
    path.join(os.homedir(), '.vscode', 'extensions'),
    path.join(os.homedir(), '.cursor', 'extensions'),
  ];
  for (const base of bases) {
    if (!fs.existsSync(base)) continue;
    for (const entry of fs.readdirSync(base)) {
      if (entry.toLowerCase().includes(fragment.toLowerCase())) return true;
    }
  }
  return false;
}

function probeDetect(rule) {
  const [kind, value] = rule.split(':');
  switch (kind) {
    case 'command':
      return hasCommand(value);
    case 'macapp':
      return hasMacApp(value);
    case 'dir':
      return hasDir(value);
    case 'vscode-ext':
      return hasVSCodeExt(value);
    default:
      return false;
  }
}

function detectProvider(provider) {
  return provider.detect.some(probeDetect);
}

function repoRoot() {
  const here = path.dirname(path.dirname(__filename));
  if (
    fs.existsSync(path.join(here, 'SKILL.md')) &&
    fs.existsSync(path.join(here, 'bin', 'install.cjs'))
  ) {
    return here;
  }
  return null;
}

function log(msg, opts = {}) {
  if (opts.dry) console.log(`[dry-run] ${msg}`);
  else console.log(msg);
}

function run(cmd, args, opts = {}) {
  const line = `${cmd} ${args.join(' ')}`;
  if (opts.dryRun) {
    log(line, { dry: true });
    return { status: 0 };
  }
  return cp.spawnSync(cmd, args, {
    stdio: 'inherit',
    shell: process.platform === 'win32',
  });
}

function copyRecursive(src, dest, dryRun) {
  if (!fs.existsSync(src)) return;
  log(`copy ${src} → ${dest}`, { dry: dryRun });
  if (dryRun) return;
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyRecursive(s, d, false);
    else {
      fs.mkdirSync(path.dirname(d), { recursive: true });
      fs.copyFileSync(s, d);
    }
  }
}

function installSkillsViaNpx(profile, opts) {
  const spec = `github:${REPO}#${PINNED_REF}`;
  const args = ['-y', 'skills', 'add', spec, '-a', profile];
  if (opts.yes) args.push('--yes');
  log(`npx ${args.join(' ')}`, { dry: opts.dryRun });
  if (opts.dryRun) return true;
  const r = run('npx', args, opts);
  return (r.status ?? 1) === 0;
}

function readSkillsManifest(root) {
  const path_ = path.join(root, 'skills.json');
  if (!fs.existsSync(path_)) return { skills: [] };
  try {
    return JSON.parse(fs.readFileSync(path_, 'utf8'));
  } catch {
    return { skills: [] };
  }
}

/** Agent-local skills dirs used when npx skills add fails (local clone required). */
function skillDestBase(profile) {
  const home = os.homedir();
  const map = {
    claude: path.join(home, '.claude', 'skills'),
    cursor: path.join(home, '.cursor', 'skills'),
    codex: path.join(home, '.codex', 'skills'),
    windsurf: path.join(home, '.codeium', 'windsurf', 'skills'),
    cline: path.join(home, '.cline', 'skills'),
    gemini: path.join(home, '.gemini', 'skills'),
    opencode: path.join(home, '.config', 'opencode', 'skills'),
  };
  return map[profile] || null;
}

function installSkillsFallback(root, profile, opts) {
  const base = skillDestBase(profile);
  if (!base || !root) return false;
  const manifest = readSkillsManifest(root);
  const entries = manifest.skills || [];
  if (!entries.length) return false;
  let copied = 0;
  for (const entry of entries) {
    const rel = entry.path || '';
    const skillDir = path.join(root, path.dirname(rel));
    const name = entry.name || path.basename(path.dirname(rel));
    if (!fs.existsSync(skillDir)) continue;
    copyRecursive(skillDir, path.join(base, name), opts.dryRun);
    copied++;
  }
  return copied > 0;
}

function installCursorCommands(root, opts) {
  const src = path.join(root, 'commands', 'avo');
  if (!fs.existsSync(src)) {
    log('  skip commands: commands/avo not found', { dry: opts.dryRun });
    return;
  }
  const targets = [];
  const cwdRoot = process.cwd();
  const configAtRoot = path.join(cwdRoot, 'avo.config.json');
  const configNested = path.join(cwdRoot, 'config', 'avo.config.json');
  if (fs.existsSync(configAtRoot) || fs.existsSync(configNested)) {
    targets.push(path.join(cwdRoot, '.cursor', 'commands', 'avo'));
  }
  targets.push(path.join(os.homedir(), '.cursor', 'commands', 'avo'));
  for (const dest of targets) {
    copyRecursive(src, dest, opts.dryRun);
  }
}

function installProvider(provider, root, opts) {
  log(`\n→ ${provider.label}`);
  let ok = true;
  if (provider.skills && provider.profile) {
    ok = installSkillsViaNpx(provider.profile, opts);
    if (!ok && root) {
      const dest = skillDestBase(provider.profile);
      log(`  fallback: copy skills.json → ${dest || '(unknown profile)'}`);
      if (installSkillsFallback(root, provider.profile, opts)) ok = true;
    }
  }
  if (provider.commands && root) installCursorCommands(root, opts);
  return ok;
}

function runFullSetup(opts) {
  const root = repoRoot() || process.cwd();
  const isWin = process.platform === 'win32';
  const script = isWin ? 'scripts/setup.ps1' : 'scripts/setup.sh';
  const scriptPath = path.join(root, script);
  if (!fs.existsSync(scriptPath)) {
    die(`error: --full requires AVO repo clone with ${script}`);
  }
  const args = [];
  if (opts.lang) args.push('--lang', opts.lang);
  if (opts.yes) args.push('--yes');
  if (opts.dryRun) args.push('--dry-run');
  if (isWin) {
    const shell = hasCommand('pwsh') ? 'pwsh' : 'powershell';
    run(
      shell,
      [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        scriptPath,
        ...args,
      ],
      opts,
    );
  } else {
    run('bash', [scriptPath, ...args], opts);
  }
}

function detectEngineArch() {
  const plat = process.platform;
  const arch = process.arch;
  if (plat === 'win32' && arch === 'x64') {
    return { id: 'win-x64', slug: 'windows-x64' };
  }
  if (plat === 'darwin' && arch === 'arm64') {
    return { id: 'macos-arm64', slug: 'macos-arm64' };
  }
  if (plat === 'linux' && arch === 'x64') {
    return { id: 'linux-x64', slug: 'linux-x64' };
  }
  return null;
}

function enginePrefix() {
  return path.join(os.homedir(), '.avo');
}

function releaseAssetBase() {
  const raw = process.env.AVO_ENGINE_VERSION || PINNED_REF;
  const ver = String(raw).replace(/^v/, '');
  if (/^\d+\.\d+\.\d+/.test(ver)) {
    return `https://github.com/${REPO}/releases/download/v${ver}`;
  }
  return `https://github.com/${REPO}/releases/latest/download`;
}

function parseSums(text, slug) {
  const suffix = `-${slug}.zip`;
  for (const line of text.split(/\r?\n/)) {
    const parts = line.trim().split(/\s+/);
    if (parts.length < 2) continue;
    const name = parts[parts.length - 1].replace(/^\*/, '');
    if (name.endsWith(suffix)) {
      return { hash: parts[0].toLowerCase(), zipName: name };
    }
  }
  return null;
}

async function httpGetBuffer(url) {
  const res = await fetch(url, {
    redirect: 'follow',
    headers: { 'User-Agent': 'avo-install' },
  });
  if (!res.ok) {
    const err = new Error(`HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return Buffer.from(await res.arrayBuffer());
}

function extractZipBuffer(buf, destRoot) {
  let offset = 0;
  const root = path.resolve(destRoot);
  while (offset + 30 <= buf.length) {
    if (buf.readUInt32LE(offset) !== 0x04034b50) break;
    const flags = buf.readUInt16LE(offset + 6);
    const method = buf.readUInt16LE(offset + 8);
    const compressedSize = buf.readUInt32LE(offset + 18);
    const nameLen = buf.readUInt16LE(offset + 26);
    const extraLen = buf.readUInt16LE(offset + 28);
    const name = buf
      .subarray(offset + 30, offset + 30 + nameLen)
      .toString('utf8');
    const dataStart = offset + 30 + nameLen + extraLen;
    if (flags & 8) {
      throw new Error('zip data descriptor unsupported');
    }
    const data = buf.subarray(dataStart, dataStart + compressedSize);
    offset = dataStart + compressedSize;
    if (name.endsWith('/')) continue;
    const target = path.resolve(destRoot, name);
    if (target !== root && !target.startsWith(root + path.sep)) continue;
    fs.mkdirSync(path.dirname(target), { recursive: true });
    if (method === 0) fs.writeFileSync(target, data);
    else if (method === 8) fs.writeFileSync(target, zlib.inflateRawSync(data));
    else throw new Error(`unsupported zip method ${method}`);
  }
}

function mergeDir(src, dst) {
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const from = path.join(src, entry.name);
    const to = path.join(dst, entry.name);
    if (entry.isDirectory()) {
      fs.mkdirSync(to, { recursive: true });
      mergeDir(from, to);
    } else {
      fs.mkdirSync(path.dirname(to), { recursive: true });
      fs.copyFileSync(from, to);
    }
  }
}

async function installEngine(opts) {
  if (opts.uninstall || process.env.AVO_SKIP_ENGINE === '1') return;
  const detected = detectEngineArch();
  const prefix = enginePrefix();
  if (!detected) {
    log(
      'Engine zip skipped: this OS/arch is not a v1 target (Windows x64, macOS arm64, Linux x64). Skills still install.',
      { dry: opts.dryRun },
    );
    return;
  }
  const launcherHint = path.join(
    prefix,
    'bin',
    process.platform === 'win32' ? 'avo.exe' : 'avo',
  );
  log(`engine zip ${detected.slug} → ${launcherHint}`, { dry: opts.dryRun });
  if (opts.dryRun) return;
  const base = releaseAssetBase();
  let sumsBuf;
  try {
    sumsBuf = await httpGetBuffer(`${base}/SHA256SUMS`);
  } catch {
    log(
      'Engine zip skipped: no SHA256SUMS on this release (skills installed).',
    );
    return;
  }
  const parsed = parseSums(sumsBuf.toString('utf8'), detected.slug);
  if (!parsed) {
    log(`Engine zip skipped: no asset for ${detected.slug}.`);
    return;
  }
  const zipBuf = await httpGetBuffer(`${base}/${parsed.zipName}`);
  if (
    crypto.createHash('sha256').update(zipBuf).digest('hex') !== parsed.hash
  ) {
    die(`Engine SHA256 mismatch for ${parsed.zipName}; previous install kept.`);
  }
  const staging = path.join(prefix, '.staging');
  fs.rmSync(staging, { recursive: true, force: true });
  fs.mkdirSync(staging, { recursive: true });
  try {
    extractZipBuffer(zipBuf, staging);
    mergeDir(staging, prefix);
  } finally {
    fs.rmSync(staging, { recursive: true, force: true });
  }
  const launcher = fs.existsSync(path.join(prefix, 'bin', 'avo.exe'))
    ? path.join(prefix, 'bin', 'avo.exe')
    : path.join(prefix, 'bin', 'avo');
  if (process.platform !== 'win32' && fs.existsSync(launcher)) {
    // eslint-disable-next-line sonarjs/file-permissions -- Unix engine launcher must be executable
    fs.chmodSync(launcher, 0o755);
  }
  log(`engine: ${launcher}`);
}

function printHelp() {
  console.log(`AVO installer — agent skills + engine zip + optional full toolchain

Usage:
  node bin/install.cjs [flags]
  curl -fsSL https://raw.githubusercontent.com/${REPO}/${PINNED_REF}/scripts/install/install.sh | bash
  irm https://raw.githubusercontent.com/${REPO}/${PINNED_REF}/scripts/install/install.ps1 | iex

Flags:
  --dry-run       Print actions only
  --full          Also run scripts/setup (ffmpeg, whisper, watch-skill, …)
  --lang CODE     Transcription language for --full (e.g. en, pt)
  --only AGENT    Install for one agent (cursor, claude, codex, …)
  --list          List supported agents
  --yes, -y       Non-interactive
  --uninstall     Remove AVO skills (best-effort)
  -h, --help      Show help

Per-agent skills only (does not download the engine zip):
  npx skills add ${REPO} -a cursor

Env:
  AVO_INSTALL_REPO    GitHub slug (default: ${REPO})
  AVO_INSTALL_REF     Git ref (default: ${PINNED_REF})
  AVO_ENGINE_VERSION  Release version for the engine zip (default: latest)
`);
}

function ensureNodeVersion() {
  if (!hasCommand('node')) {
    die('AVO: Node.js required (≥18). Install from https://nodejs.org');
  }
  const major = parseInt(process.versions.node.split('.')[0], 10);
  if (major < 18) {
    die(`AVO: Node ${process.versions.node} too old. Need ≥18.`);
  }
}

/** @returns {typeof PROVIDERS | null} null when nothing to install */
function resolveTargets(opts) {
  if (opts.only.length) {
    const targets = PROVIDERS.filter((p) => opts.only.includes(p.id));
    if (!targets.length) {
      die(`error: unknown agent(s): ${opts.only.join(', ')}\nuse --list`);
    }
    return targets;
  }
  const detected = PROVIDERS.filter(detectProvider);
  if (!detected.length) {
    log(
      'No supported agents detected. Use --only AGENT or install an agent first.',
    );
    log('Supported: ' + PROVIDERS.map((p) => p.id).join(', '));
    return null;
  }
  return detected;
}

function finishInstall(opts, failed) {
  if (opts.full) {
    log('\n→ Full toolchain (setup.sh)');
    runFullSetup(opts);
  } else {
    log(
      '\nLauncher: ~/.avo/bin/avo. ffmpeg/HyperFrames/watch-skill stay outside the zip. See docs/install/README.md.',
    );
  }
  if (failed) die(`\n${failed} agent(s) failed. See docs/install/README.md.`);
  log('\nDone.');
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    printHelp();
    return;
  }
  ensureNodeVersion();

  if (opts.listOnly) {
    for (const p of PROVIDERS) console.log(`${p.id.padEnd(12)} ${p.label}`);
    return;
  }

  const root = repoRoot();
  if (root) log(`AVO repo: ${root}`);
  else log(`AVO: remote install (${REPO}@${PINNED_REF})`);

  const targets = resolveTargets(opts);
  if (!targets) return;

  log(`Installing for: ${targets.map((t) => t.label).join(', ')}`);
  let failed = 0;
  for (const p of targets) {
    if (!installProvider(p, root, opts)) failed++;
  }
  await installEngine(opts);
  finishInstall(opts, failed);
}

main().catch((err) => die(err.message || String(err)));
