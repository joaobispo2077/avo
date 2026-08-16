# avo.mcp — local orchestrator MCP (stdio)

**Audience:** driving agents and operators wiring Cursor / Claude Code / VS Code.  
**Positioning:** AVO’s **orchestrator** MCP adapter over pipeline/CLI helpers — **not** an editor/NLE MCP. See [`why-not-editor-mcp.md`](why-not-editor-mcp.md).

`avo.mcp` is **additive**. Skills, repo clone, and `avo` CLI remain first-class and work without the MCP process. MCP does not replace watch-skill verify (separate MCP/CLI/REST when you use it).

**Cloud / Docker is not required** for phase-1. Remote/container MCP is future backlog only (`specs/backlog/avo-mcp-cloud.md`) and must never gate local install or use.

**Local `avo.mcp` is auth-free** (no OAuth, IdP, API keys, or login gates). Cloud MCP authentication is backlog-only — see [Auth](#auth-local-vs-cloud).

---

## Protocol posture (MCP 2026-07-28 + MRTR)

AVO targets the **MCP 2026-07-28** stateless core and the draft **Multi Round-Trip Requests (MRTR)** pattern for gated tools. Local stdio (`python -m avo.mcp`) remains the default happy path; this posture is serverless-*ready* without requiring cloud.

| Posture | Meaning for operators |
| --- | --- |
| **Stateless core** | Each `tools/call` (and other supported requests) is self-contained. The server does not need sticky sessions, shared session memory, or load-balancer affinity to finish a call. Continuity for gated flows is carried by the client, not a server-side session store. |
| **MRTR for gated tools** | Destructive / approval-style tools may return `InputRequiredResult` (`resultType: "input_required"`) with `inputRequests` and/or opaque `requestState`. The harness gathers input, then **retries** the same call with `inputResponses` and the echoed `requestState`. The server must not hang waiting if the client never retries. |
| **Local default** | Stdio child process launched by the harness — unchanged. Stateless/MRTR design does not force HTTP, Docker, or remote hosting. |

**References:**

- [Multi Round-Trip Requests (MRTR) draft](https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr)
- [Bringing MCP 2026-07-28 to Claude](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude) (2026-07-28 announcement)

`requestState` is opaque to the client but treated as attacker-controlled on the server (integrity / expiry / tool binding). Harness or SDK support for MRTR may roll out with 2026-07-28; until then, destructive tools still carry description warnings.

---

## Auth (local vs cloud)

| Surface | Auth |
| --- | --- |
| Local `avo.mcp` (stdio) | **None** — works without an account |
| Future cloud / remote MCP | **Backlog only** — late milestone in `specs/backlog/avo-cloud.md`; never a prerequisite for local MCP, skills, or CLI |

Do not expect login gates, OAuth, or API keys on the local stdio path.

---

## Install (optional extra)

Default / Gate 1 installs do **not** pull the MCP SDK. Opt in:

```bash
# editable checkout from repo root
pip install -e ".[mcp]"

# or after a normal install
pip install "avo[mcp]"
```

That installs the official Python `mcp` package (`mcp>=1.28`). Prefer SDK v2 `MCPServer` (stdio). Core `pyproject.toml` runtime deps stay free of `mcp`.

If you launch without the extra:

```text
avo.mcp requires the optional 'mcp' package.
Install with: pip install 'avo[mcp]'
```

(message on **stderr**, non-zero exit)

---

## Run locally

Phase-1 transport is **stdio only** (JSON-RPC on stdin/stdout). No listen port.

```bash
# from an installed env with avo[mcp]
python -m avo.mcp

# editable layout (src layout) — set PYTHONPATH if needed
PYTHONPATH=src python -m avo.mcp
```

On Windows PowerShell (editable):

```powershell
$env:PYTHONPATH = "src"
python -m avo.mcp
```

**Stdout purity:** stdout is reserved for MCP framing. Logs go to **stderr** only. Do not `print()` to stdout from MCP process code or import-time side effects.

The harness starts one child process per config. No shared daemon is required. Prefer absolute paths for `command` / working directory when the harness cwd is not the AVO repo.

---

## Harness wiring overview

Hosts launch a child process and speak MCP over stdio. Config is a launch command — **not** the HTTP `url` pattern used by ai-memory templates.

| Host | Config location | Shape |
| --- | --- | --- |
| Cursor | `.cursor/mcp.json` | `{ "mcpServers": { "avo": { "command", "args", "env?" } } }` |
| Claude Desktop | `claude_desktop_config.json` | same `mcpServers` shape |
| Claude Code | CLI | `claude mcp add avo -- <command…>` |
| VS Code | `.vscode/mcp.json` | `{ "servers": { "avo": { "type": "stdio", "command", "args" } } }` |

### Cursor example (stdio)

```json
{
  "mcpServers": {
    "avo": {
      "command": "uv",
      "args": ["run", "--frozen", "python", "-m", "avo.mcp"],
      "env": {
        "PYTHONPATH": "src"
      }
    }
  }
}
```

Alternate after `pip install -e ".[mcp]"`: `"command": "python"`, `"args": ["-m", "avo.mcp"]` using the project venv’s Python (prefer absolute path to that interpreter).

### Claude Code one-liner

```bash
claude mcp add avo -- python -m avo.mcp
```

With editable `src` layout:

```bash
claude mcp add avo --env PYTHONPATH=src -- python -m avo.mcp
```

Copy-paste templates:

- [`templates/avo-mcp/cursor-mcp.example.json`](templates/avo-mcp/cursor-mcp.example.json) — Cursor `.cursor/mcp.json` (`mcpServers` + stdio `command`/`args`; `uv run` editable layout)
- [`templates/avo-mcp/claude-code.md`](templates/avo-mcp/claude-code.md) — `claude mcp add` one-liners

Keep them distinct from [`templates/ai-memory/cursor-mcp.example.json`](templates/ai-memory/cursor-mcp.example.json) (HTTP `url` pattern).

---

## Coexistence with skills and CLI

| Surface | Role | MCP required? |
| --- | --- | --- |
| Skills / `/avo.*` commands | Agent workflows, editorial gates | No |
| `python -m avo.cli` / `avo` CLI | Same pipeline/timeline ops from a shell | No |
| `python -m avo.mcp` | Harness tool list + invoke over stdio | Optional |

Same semantics: bridged tools map to CLI argv (`avo_<group>_<subcommand>` → `avo.cli.main([...])` in-process). Prefer skills/CLI when that fits the workflow; use MCP when the harness should list/call tools directly.

**Out of phase-1 bridge:** other `python -m avo.*` modules (`models_cli`, `transcribe`, `init_project`, …) stay available outside MCP. Scope is `cli.py` groups plus meta tools.

Destructive ops (e.g. `cleanup execute`) stay exposed with **warnings in tool descriptions**. Prefer **MRTR confirmation** (see [Protocol posture](#protocol-posture-mcp-2026-07-28--mrtr)) when the harness supports it — do not call them in smoke tests.

---

## Smoke checklist

After install + harness wire (or a manual stdio session with an MCP client):

1. **Process starts** — harness shows `avo` / `avo.mcp` connected; no missing-`mcp` stderr.
2. **`avo_health`** — call with no args / no `--project`. Expect success payload roughly:
   - `ok: true`
   - `name: "avo.mcp"`
   - `version: "…"` (installed `avo` version)
   - `transport: "stdio"` (or equivalent)
3. **`avo_list_capabilities`** — lists registered tools/groups; includes a docs pointer to `docs/avo-mcp.md`. Optional group filter when supported.
4. **Do not** require a real `providers/` tree or footage `rawDir` for meta smoke.
5. **Do not** invoke destructive tools (`avo_cleanup_execute`, migrate activate/rollback, etc.) during smoke.

Manual harness E2E inside the Cursor UI is operator smoke; automated CI uses fixtures only (`pytest -m "not project"`). Integration smoke: `tests/integration/test_avo_mcp_stdio.py` (in-process MCP `Client` against `create_server()` — no blocking stdio child, no `providers/*` or footage roots).

---

## What this is not

| Topic | Status |
| --- | --- |
| CapCut / DaVinci / Premiere timeline MCP | Out of scope — [`why-not-editor-mcp.md`](why-not-editor-mcp.md) |
| Streamable HTTP / SSE as ship requirement | Out of phase-1 |
| Docker image / cloud-hosted MCP | **Backlog only** — not required; see `specs/backlog/avo-mcp-cloud.md` |
| Local MCP authentication (OAuth / IdP / API keys) | Out of scope — local stdio stays auth-free |
| Cloud MCP authentication | **Backlog only** — late `avo.cloud` milestone; see `specs/backlog/avo-cloud.md` |
| Sticky sessions / shared MCP session store | Out of scope — stateless core (2026-07-28) |
| Replacing watch-skill | Never — verify stays separate |
| Replacing skills or CLI | Never — MCP is an adapter |

---

## Related

- [`agent-skills.md`](agent-skills.md) — skills remain first-class without MCP
- [`avo-commands.md`](avo-commands.md) — `/avo.*` slash commands
- [`avo-workflow.md`](avo-workflow.md) — pipeline, approval gates, preserved-set
- [`why-not-editor-mcp.md`](why-not-editor-mcp.md) — orchestrator vs editor MCP
- [`ai-memory-and-ai-jail.md`](ai-memory-and-ai-jail.md) — optional HTTP MCP for memory (different pattern)
- [MRTR draft](https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr) — gated-tool round-trips
- [MCP 2026-07-28 / Claude](https://claude.com/blog/bringing-mcp-2026-07-28-to-claude) — stateless protocol announcement
- Spec: `specs/active/avo-mcp/spec.md` (v1.2 FR-14/15) · follow-up roadmap: `specs/todo-roadmap/avo-mcp-mrtr`
