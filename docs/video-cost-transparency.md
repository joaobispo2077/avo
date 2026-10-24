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

## Supported collection paths

| Agent | Local input | Limitations |
| --- | --- | --- |
| Codex CLI | Documented exec JSONL with thread.started and completed-turn usage | Requires explicit thread binding; model/provider/time remain unknown when absent. Interactive/Desktop rollout formats are not silently guessed. |
| OpenCode | Completed assistant-message export | Session/model/provider identity retained; partial messages wait for completion. |
| Claude Code | Projected api_request event metadata | Source must include matching session/request identity; no raw prompt logging needed. |
| Gemini CLI | Projected api_response metadata | Missing category overlap remains unknown; aggregate counters alone cannot identify a video's requests. |
| Cursor | Normalized authorized usage export or manual metadata | Optional conversation identity must be explicitly attributed; no private dashboard endpoint or admin key required. |
| Cline | Normalized per-task report or manual metadata | No promise of a stable universal native export schema. |
| Windsurf | Normalized/native-unit manual report | Credits/ACUs are not tokens; no universal credit conversion. |

All seven accept normalized imports/manual reports. `capabilities` describes source shapes, not a guarantee every installed agent version exposes that format. Account-wide collection, background daemons and remote admin fetching are not required. Files are bounded to 32 MiB per input, with at most 100,000 observations per import; split larger exports into attributable parts.

## Bind and collect

```powershell
python -m avo.cli costs bind --project C:/videos/demo/avo.project.json --source C:/usage/scoped.jsonl --agent codex --session-id THREAD_ID --boundary beginning --format codex
python -m avo.cli costs collect --project C:/videos/demo/avo.project.json
python -m avo.cli costs close-binding --project C:/videos/demo/avo.project.json --binding-id BINDING_ID --end-boundary LAST_REQUEST
```

Choose beginning only when the entire supplied session belongs to this video. Otherwise specify the last request before the video began. Close a binding before using that session for another video. Independent sessions may run concurrently; unknown shared intervals stay unallocated. Each record retains its original model, service provider and billing basis, so switching mid-pipeline cannot retroactively price earlier usage with the newly selected model. The channel provider is a separate identity from the AI service provider.

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
