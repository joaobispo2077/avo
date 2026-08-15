# Backlog: avo.cloud

**Status:** Backlog only — **do not implement** from this note alone.  
**Related:** `specs/active/avo-mcp` · `specs/backlog/avo-mcp-cloud.md`

## Intent

Optional **cloud / remote** AVO for operators who lack minimum hardware to run
AVO **100% locally**. Additive to local skills, CLI, and local `avo.mcp` —
never a replacement or gate.

## Milestone order (sketch)

1. Remote runtime / packaging that can host AVO workloads (weak-hardware path)
2. Optional remote MCP endpoint (stateless / serverless-friendly; MRTR-capable)
3. Resource limits, media mounts, cost/telemetry disclosure
4. **Last (or near-last): authentication for cloud-hosted `avo.mcp`**
   (OAuth / IdP / API keys as appropriate for a network surface)

Local `avo.mcp` over stdio remains **auth-free** forever as the default path.
Cloud auth must not be required to use AVO locally.

## Agent rule

Do not start `avo.cloud` or cloud MCP auth implementation until this backlog is
promoted to an approved active spec/roadmap with explicit user approval.

---
Recorded: 2026-08-14 | Source: evolve no-local-auth / approve evolve
