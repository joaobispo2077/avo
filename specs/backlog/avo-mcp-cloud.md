# Backlog: avo.mcp Docker / cloud (weak hardware)

**Status:** Backlog only — **do not implement** from this note alone.  
**Related:** `specs/active/avo-mcp` (local stdio MCP is the shipped path)  
**Parent cloud backlog:** `specs/backlog/avo-cloud.md`  
**Roadmap:** `specs/todo-roadmap/avo-mcp` task-013 · epic-006

## Intent

Some operators have weak local CPU/GPU/disk and may later want an optional
**Docker image** or **cloud-hosted** MCP endpoint that runs the same AVO
orchestrator tool surface remotely.

That option is a **future enhancement**, not part of phase-1 `avo.mcp`.

## Non-negotiable invariant

**Local MCP, skills, and CLI must never be replaced or blocked** by a cloud or
Docker option.

- Default and documented happy path remains: install optional `avo[mcp]`, run
  `python -m avo.mcp` over **stdio**, wire the harness locally — **no account /
  OAuth / IdP required**.
- Cloud/Docker, if built later, is **opt-in** and additive.
- No release may require a remote account, image pull, or network MCP listen
  surface in order to use AVO skills, CLI, or local `avo.mcp`.
- When cloud exists, docs must keep local-first instructions first; remote is
  an alternate for constrained hardware — never a gate.

## Possible future scope (sketch only)

- Container image with AVO + `[mcp]` extra and a documented entrypoint
- Optional Streamable HTTP/SSE transport for remote harnesses — prefer **stateless /
  serverless-friendly** design aligned with MCP **2026-07-28** and
  [MRTR](https://modelcontextprotocol.io/specification/draft/basic/patterns/mrtr)
  (`InputRequiredResult` / `requestState`) so gated tools need no sticky sessions
- Resource limits and media volume mounts for rawDir/edit workspaces
- Cost/telemetry disclosure for remote runs
- **Authentication for cloud-hosted `avo.mcp`** — see `avo-cloud.md`; treat as a
  **late** milestone on the cloud roadmap (after the remote path works), never as
  a requirement for local MCP

None of the above are phase-1 acceptance criteria. Local stdio remains first;
see active spec FR-14/FR-15 for serverless-built-in posture on the local server.

## Agent rule

Do not scaffold Dockerfiles, cloud deploy configs, HTTP MCP listeners, or auth
providers for `avo.mcp` until the relevant backlog item is promoted to an
approved active spec with explicit user approval. Local stdio work in
`specs/active/avo-mcp` proceeds independently and stays auth-free.

---
Recorded: 2026-08-14 | Source: task-013  
Updated: 2026-08-14 | Auth deferred to late avo.cloud
