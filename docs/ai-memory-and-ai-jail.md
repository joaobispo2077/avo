# ai-memory and ai-jail (optional)

AVO works **fully without** [ai-memory](https://github.com/akitaonrails/ai-memory) and
[ai-jail](https://github.com/akitaonrails/ai-jail). Both are optional orchestrator
dependencies — setup never fails when they are missing.

## Invariants

| Concern | Behavior |
| --- | --- |
| Pipeline stages | Complete with neither, either, or both tools |
| Setup | `--with-memory` / `--with-jail` WARN or SKIP only — never FAIL |
| Gate 1 | Optional tools SKIP unless `validate:prerequisites --include-optional` |
| `/avo.learndown` without ai-memory | Skip MCP wiki step only; inventory, wrap, provider export, telemetry **still run** |

---

## ai-memory

### What setup does

`bash scripts/setup.sh --with-memory` (or `setup.ps1`) **only clones** upstream source to
`tools/ai-memory/`. It does **not** install the CLI, start the server, or wire Cursor MCP/hooks.

### Manual runtime install

Pick the path that matches **where your agent runs** (see
[ai-memory Windows docs](https://github.com/akitaonrails/ai-memory/blob/main/docs/windows.md)).

**Linux / macOS (agent runs natively):**

```bash
mkdir -p ~/.local/bin
curl -fsSL https://github.com/akitaonrails/ai-memory/releases/latest/download/ai-memory-wrapper \
  -o ~/.local/bin/ai-memory
chmod +x ~/.local/bin/ai-memory

docker run -d --name ai-memory --restart unless-stopped \
  -p 127.0.0.1:49374:49374 -v ai-memory-data:/data \
  akitaonrails/ai-memory:latest

ai-memory install-mcp --client cursor --apply
ai-memory install-hooks --agent cursor --apply
```

**Windows native (Cursor as Windows process):**

See upstream Scenario B or C in
[`docs/windows.md`](https://github.com/akitaonrails/ai-memory/blob/main/docs/windows.md).
Use the Docker Desktop wrapper or release zip; run `install-mcp` / `install-hooks` from
PowerShell in the **same environment** as Cursor.

**Windows via WSL2 (agent runs inside WSL):**

Install ai-memory **inside WSL**, not from native PowerShell. Hook paths must match the agent.

### Learndown without ai-memory

`/avo.learndown` still:

1. Runs inventory report
2. Writes draft wrap (`avo.wrap draft`)
3. Exports `providers/<slug>/learndowns/`
4. Emits learndown telemetry

Wrap records `aiMemory: "skipped"`. Filesystem export is the durable catalog.

### Template

Copy [`docs/templates/ai-memory/cursor-mcp.example.json`](templates/ai-memory/cursor-mcp.example.json) into `.cursor/mcp.json` (merge with existing servers).

---

## ai-jail

### Platform support

| OS | Support |
| --- | --- |
| Linux | Native (`bwrap`) |
| macOS | Native (`sandbox-exec`) |
| Windows | **WSL2 only** — no native Windows sandbox backend |

Upstream: [ai-jail README — Windows](https://github.com/akitaonrails/ai-jail#windows)

### What setup does

`--with-jail` tries to install/verify ai-jail:

- **Linux/macOS:** brew / cargo / mise; Linux also checks `bubblewrap`
- **Windows:** installs/verifies inside **default WSL distro** (`bwrap` + `ai-jail --version`)

### AVO launch pattern

Mask repo secrets; map external footage read-write (`rawDir` is outside the AVO repo):

```bash
ai-jail --mask .env --mask .ai-memory.toml \
  --rw-map /abs/path/to/raw-footage \
  ai-memory run cursor
```

Or without managed workstreams:

```bash
ai-jail --mask .env --rw-map /abs/path/to/raw-footage cursor
```

### Template

Copy [`docs/templates/ai-jail/avo.ai-jail.toml`](templates/ai-jail/avo.ai-jail.toml) to
`.ai-jail` in the AVO repo (or project root) and add your `rawDir` under `rw_maps`.

### WSL performance note

Projects on `/mnt/c/...` are slower than `~/Projects/` inside WSL. For large footage trees,
prefer cloning or symlinking into the Linux filesystem.

---

## Gate 1 optional checks

```bash
npm run validate:prerequisites -- --include-optional
```

Reports clone/binary presence, optional server probe (ai-memory), and `bwrap` hints (ai-jail).
All optional checks are WARN — never FAIL.

---

## Related

- [`docs/install/README.md`](install/README.md) — setup flags
- [`docs/avo-workflow.md`](avo-workflow.md) §7 — learndown + cleanup
- [`docs/providers.md`](providers.md) — provider-scoped learning export
