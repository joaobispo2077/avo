# Video cost transparency

Ask “what have I spent on this video?” or use `/avo.costs` (`/avo.metrics` alias). In a checkout:

```powershell
python -m avo.cli costs --project C:/videos/demo/avo.project.json
python -m avo.cli costs collect --project C:/videos/demo/avo.project.json
python -m avo.cli costs --project C:/videos/demo/avo.project.json --phase motion --json
python -m avo.cli costs --history
python -m avo.cli costs --trends
python -m avo.cli costs capabilities
```

Installed engine users use `avo costs` with the same arguments. A report reads recorded data; collect refreshes explicitly bound local sources. Neither starts inference, fetches tariffs or uploads usage. Unknown amounts remain unknown. All amounts show their basis: reported cost, calculated estimate, API-equivalent value or manual report. Unlike currencies and native credits remain separate. Subscription API equivalents are not your subscription invoice. Labor, hardware, electricity and unreported service use are excluded.

## Supported contribution paths

The [agent continuity guide](agent-cost-continuity.md) documents context, handoffs,
manual bootstrap, estimates and reconciliation. `costs capabilities --json`
reports ten separate environments:

| Environment | Bundled host-native status | Contribution available now |
| --- | --- | --- |
| Codex CLI | Candidate | Scoped manual report, typed packet or explicit estimate |
| Codex Desktop | Candidate, qualified separately from CLI | Scoped manual report, typed packet or explicit estimate |
| ChatGPT | Manual-only | Supplied structured metadata or explicit estimate |
| Cursor | Candidate | Scoped manual report, typed packet or explicit estimate |
| Claude Code | Candidate | Scoped manual report, typed packet or explicit estimate |
| OpenCode | Candidate | Scoped manual report, typed packet or explicit estimate |
| Gemini CLI | Candidate | Scoped manual report, typed packet or explicit estimate |
| Cline | Candidate | Scoped manual report, typed packet or explicit estimate |
| Windsurf | Manual-only | Attributable native-unit/manual data or explicit estimate |
| Unknown or custom agent | Manual-only | Preserve its supplied identity; use scoped manual data or an estimate |

No bundled host-native profile is currently qualified. Documentation and synthetic
fixtures do not certify a vendor source/version. Native measurement needs an
explicitly admitted, fixture-qualified profile and an authorized scoped source.
Unknown versions do not inherit an old parser. Codex cumulative exec output is
not treated as per-turn usage or as a proven final flush.

The existing seven installer profiles remain unchanged. Skills-only installation
does not supply a runtime or capture host usage. Account-wide collection,
background daemons and remote admin fetching are not activated. Typed/manual
inputs are bounded to 32 MiB and 100,000 observations; split larger sources into
attributable parts. Incremental qualified collection additionally limits each
call to 8 MiB, 10,000 records and 1 MiB per record.

## Bind and collect

```powershell
python -m avo.cli costs bind --project C:/videos/demo/avo.project.json --source C:/usage/scoped.jsonl --agent cursor --session-id video-session --boundary beginning --format normalized
python -m avo.cli costs collect --project C:/videos/demo/avo.project.json
python -m avo.cli costs close-binding --project C:/videos/demo/avo.project.json --binding-id BINDING_ID --end-boundary LAST_REQUEST
```

Choose beginning only when the entire supplied session belongs to this video. Otherwise specify the last request before the video began. Close a binding before using that session for another video. Independent sessions may run concurrently; unknown shared intervals stay unallocated. Each record retains its original model, service provider and billing basis, so switching mid-pipeline cannot retroactively price earlier usage with the newly selected model. The channel provider is a separate identity from the AI service provider.

This legacy normalized route retains its evidence limitations. To identify a new
manual declaration explicitly, first register its context and use
`report-manual --participation-fact-id <factId> --operation-id <stable-id>`.
That route freezes a manual-only profile; it never certifies native measurement.
MCP callers can supply a structured manual request without a shared file path.

## Normalized example

The amounts below are synthetic, not model pricing. Save a list of observations with these fields:

```json
[
  {
    "sourceInstanceId": "my-export",
    "sourceSessionId": "video-session",
    "requestId": "request-1",
    "agent": "cursor",
    "agentVersion": "manual-report",
    "model": "observed-model",
    "serviceProvider": "observed-service",
    "billingMode": "api",
    "serviceClass": "host-agent",
    "occurredAt": "2026-10-22T16:00:00Z",
    "phase": "motion",
    "tokens": {"input": 1000, "output": 200, "cacheRead": 600},
    "semantics": {"cacheRead": "input"},
    "amounts": [{"basis": "manual", "unit": "USD", "amount": "0.01", "provenance": "synthetic example"}]
  }
]
```

`cacheRead: input` means cached tokens are already included in input. `disjoint` means an additional category; `unknown` prevents a fabricated combined token total. Unknown categories can be null. Import with `costs import --project <project> --file <metadata.json>`; use `report-manual` to label manual measurement. Identical observations count once, even after repeated imports. Conflicting variants are excluded until an explicit `costs correct --file <correction.json>` selects a source-content hash or excludes it. Correction fields are observationId, action (select/exclude), actor, reason and selected (variant SHA-256 or null).

## Prices, snapshots and history

`costs price --file <price.json> --project <project>` registers a frozen schedule before import. Price fields: schemaVersion, model, serviceProvider, unit, basis, effectiveAt, provenance, denominator and rates by token category. Optional dimensions (tier, region, contextBand) require matching pricingDimensions on each observation; incomplete rates or unknown overlap cannot produce a partial price disguised as a full estimate. Imports bind the available schedules; adding a later schedule does not silently reprice existing records. `costs revalue --file <price.json> --project <project>` is an explicit alternative valuation; historical snapshots remain intact.

`costs snapshot --stage draft --project <project>` saves a working checkpoint. A final snapshot requires the completed cleanup receipt. The normal learndown/cleanup workflow publishes matching snapshots to wraps and provider exports automatically. Reports include pending-turn and partial-coverage disclosures because the final agent response itself may not yet be measured. No fixed learning-curve savings are assumed.

Evidence lives under the footage project's `edit/costs/`; ordinary cleanup preserves that entire directory. Provider learndowns retain sanitized evidence for offline history. `.avo/cost-locators/` is only a discovery index. Existing untracked videos say not recorded. Moving a project preserves accounting identity. An independent copy can explicitly `costs fork --project <project> --new-video-id <id>`; its inherited accounting directory is archived locally before initializing the new identity.

Atomic writes require a local filesystem with reliable rename/locking. No concurrent multi-host/cloud-sync merge guarantee. An interrupted writer can leave a `.lock` directory: verify no writer is running before removing that specific lock and retrying; accepted JSON evidence must never be edited/deleted to unlock a report.

Recorded trend cohorts match valuation basis, unit, coverage, service classes and excluded costs. At least two completed videos are required for a mean. Counts describe recorded videos; no duration normalization, invoice reconciliation or promised savings is inferred.
