# Video cost transparency research

Verified 2026-10-22. Scope: specification research, not an implemented cost command.

Planning follow-up: [Phase 0 decisions and current source findings](../specs/011-video-cost-transparency/research.md) refine this initial survey. In particular, Cursor's current official Admin API can provide optional conversation identity for authorized exports; it is not a universal individual-account collection path. Automatic draft/final response summaries and request-level model/provider switching are now explicit requirements.

## Finding

AVO can answer “what has been recorded for this video?” reliably. It cannot promise an exact invoice across arbitrary external agents and subscription plans. Separate observed tokens, source-reported charges, reproducible estimates, native credits and unknown coverage. A report that says partial is preferable to a plausible invented total.

## Repository evidence and reuse

| Existing surface | Finding and proposed role |
| --- | --- |
| `bin/install.cjs` PROVIDERS; README Supported agents | Seven named integrations: Cursor, Claude Code, Codex CLI, Windsurf, Cline, Gemini CLI, OpenCode. Registry compatibility with more agents does not establish usage access. |
| `src/avo/telemetry.py` | Phase progress, disk and model disclosure, not host-agent token accounting. Useful phase/correlation integration point. |
| `src/avo/session.py` | Provisional session hash uses normalized rawDir plus start; final hash uses rawDir plus master name. Preserve aliases across finalization, but do not use master name as the sole lifetime video identity. |
| `src/avo/avo_state.py` | Local state, video keys, active context and session paths are reusable discovery/index surfaces. Shared state is not a sufficient durable evidence store by itself. |
| `src/avo/stats.py` | Local aggregates, atomic state saves and bounded session retention. Cost history must survive this retention limit. Secret-key screening includes `token`; token-usage fields need deliberate schema handling, not removal of secret protection. |
| `src/avo/wrap.py`, `src/avo/learndown_export.py` | Existing draft/final sidecars and provider catalog export offer natural cost snapshot delivery. Export currently selects fields explicitly, so adding a wrap field alone will not propagate it. |
| `src/avo/timeline/review_study.py` | `costSignals` are render/review effort signals; they must not be relabeled as monetary charges. |
| `src/avo/adapters/understand/watch_skill.py` | Native review request/model boundary is a candidate for service usage capture; verify preservation of response usage rather than estimating from requested token limits. |
| `src/avo/cli.py`, `src/avo/mcp/`, `commands/avo/`, `agent-skills/` | Reuse the existing engine routing and optional MCP boundary. Publish a direct command plus slash/natural-language guidance. |
| `specs/backlog/costs-transparency.md`, active capabilities roadmap FR-B5 | Existing intent includes current/history/phase, alias, local state and wraps. Replace unsupported $30–40 to <$10 narrative with measured comparisons. |

The installed engine and clone-local runtime are distinct supported modes; use `docs/install/README.md` as current authority over the older consume-modes research. Storage must work for both. No per-video helpers belong in this repository.

Memory tools were not exposed in this session; no memory lookup could be performed. Repository findings above are direct file inspection. Existing unrelated working-tree changes were left untouched.

## Agent evidence and collection feasibility

These are proposed integration paths, not claims of tested AVO collectors. Validate actual installed versions and sanitized fixtures during planning. Do not inspect private conversations to complete this research.

| Agent | Primary evidence | Proposed collection and limits |
| --- | --- | --- |
| Claude Code | [Official costs documentation](https://code.claude.com/docs/en/costs) documents session token/cost reporting and cache categories. | Prefer structured supported usage/status or monitoring output bound to a session. Manual snapshot fallback. Subscription valuation is not a bill; resets are version-sensitive and main-conversation cache statistics exclude subagents. |
| Codex CLI | [Official noninteractive documentation](https://learn.chatgpt.com/docs/non-interactive-mode) shows `turn.completed` usage with input, cached input, output and reasoning counts. | Consume JSON events when AVO has an explicitly captured run. For an already interactive/Desktop session, structured export or a version-tested opt-in local reader requires separate validation. Do not launch a replacement agent merely to meter the current one. |
| Gemini CLI | [Official telemetry documentation](https://geminicli.com/docs/cli/telemetry/) describes token categories and model attributes. | Opt-in local telemetry with explicit session correlation; import fallback. Aggregate metrics without video identity are insufficient. Keep prompt logging disabled. |
| OpenCode | [Official CLI documentation](https://opencode.ai/docs/cli/) documents session export and token/cost stats with project filtering. | Prefer session export/structured supported surfaces. Project totals alone cannot distinguish concurrent videos. Validate provider valuation and category semantics. |
| Cline | [Official task documentation](https://docs.cline.bot/core-workflows/task-management) describes token/API-cost tracking per task. | Bind explicit task identity; use supported export where usage fields are verified, otherwise manual task totals. The docs establish UI tracking, not a stable universal usage export schema. |
| Cursor | [Official analytics documentation](https://cursor.com/docs/account/teams/analytics) documents dashboard analytics and CSV download. | Explicit user-supplied exports/manual fallback first. Team/account analytics do not prove per-chat or per-video attribution. No private dashboard endpoints, credential extraction or undocumented SQLite dependency by default. |
| Windsurf | [Official usage URL](https://docs.windsurf.com/windsurf/accounts/usage) currently redirects to [Devin Desktop plans and usage](https://docs.devin.ai/desktop/accounts/usage). | Treat branding/version as a capability concern. Manual native-unit usage fallback until a session-level supported machine source is verified. No generic credit-to-token or credit-to-USD conversion. |

This research does not establish automatic per-video metering for Cursor, Windsurf, Cline exports, or every interactive Codex surface. Those remain explicit compatibility investigations, with truthful fallbacks required for release.

## Recommended fit with AVO

Use a small reusable Python accounting service behind existing CLI routing, with narrow agent-specific source readers. Avoid a new gateway, account system or hosted collector. A proxy only sees requests routed through it and would change authentication and agent behavior; it cannot transparently meter arbitrary existing subscriptions.

Proposed commands: `/avo.costs`, `/avo.metrics`, current-video default, `--history`, `--phase`, explicit video/provider selectors, structured output and an explicit import/collection action. The eventual engine spelling must follow existing installed-engine routing; do not document `python -m avo` as an existing entry point.

Persist a versioned evidence ledger beneath the external video's `edit/` tree, outside timeline decision-map semantics; use `.avo/state.json` only for discoverability/cached summaries. Preserve evidence and snapshots through cleanup and provider export. Choose exact files and transactional storage during planning after checking cleanup allowlists and both runtime modes. A small append-only file may suffice, but concurrent writes and deduplication must be proven; SQLite is an alternative if locking/recovery complexity justifies it.

Normalized observations need stable source/request IDs, parent relationships, source version, video/run/phase binding, observation interval, model/provider identity, token category semantics and valuation provenance. Never equate AVO's channel “provider” with the model service provider.

Collect at boundaries and on explicit refresh where available. Binding starts before usage; a late binding needs an explicit baseline or historical interval. Cumulative snapshots become deltas per source epoch. Forks, resets, retries and child-agent rollups need fixtures. If parent totals include children, keep the parent as a rollup, not an additional charge. Shared intervals stay unallocated unless an explicit allocation is recorded.

Snapshots should contain known subtotals, unknown/unallocated coverage, source cutoff, currency and price version. Use exact decimal monetary arithmetic and round only for display. Cache and reasoning counters are not universally additive. Compute prices only after each source's category semantics and billing tier are known. Freeze effective prices with each valuation; do not fetch prices during a normal report or silently reprice history. Unknown/local model prices remain unknown, with local-compute exclusions visible.

Capture paid AVO-owned inference separately at response boundaries. An orchestrator agent's tool call does not account for the tool's external inference; conversely an imported service bill may duplicate captured service records. Reconcile by source identity. Render duration, disk size and token limits are not monetary usage.

## Validation and next planning work

1. Define shared observation and snapshot contracts, privacy boundaries and stable video identity compatible with existing session finalization.
2. Obtain sanitized, versioned usage fixtures for all seven agents. Record supported automatic/import/manual paths and fields; do not promise uniform automation.
3. Prove category normalization, cumulative deltas, deduplication, child rollups, late correction, two simultaneous videos, source truncation and concurrent writes.
4. Integrate direct CLI, slash references, generic skill guidance and optional MCP registry without duplicating accounting logic.
5. Integrate wrap/learndown snapshots and cleanup preservation; test retained history independently of bounded stats retention and missing ai-memory.
6. Test missing prices, mixed currencies, subscriptions, local inference and missing historical data. Verify reporting performs no paid calls or uploads.
7. Run core unit tests and required software-quality gates when implementing. This documentation-only work does not implement collectors or validate real account bills.

## Scope decisions

No billing enforcement, pre-production quote engine, subscription amortization, hosted dashboard, mandatory telemetry server or guaranteed savings in this feature. Optional price-table updates and future richer native adapters can follow independently. Preserve all existing editorial gates; recording costs must never alter the cut or media ancestry.

The new specification is [011-video-cost-transparency](../specs/011-video-cost-transparency/spec.md). It intentionally replaces the older backlog's unsupported learning-curve assumption; the historical roadmap is left intact as prior context.
