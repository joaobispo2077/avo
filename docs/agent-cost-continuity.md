# Agent cost continuity

AVO records the executor of a video workflow separately from services invoked by
AVO. A channel/provider such as `bishop` identifies the editorial project; it is
not an inference provider, model or proof of the current caller. An internal
Qwen usage subtotal alone cannot establish the cost of the whole video.

This extends [video cost transparency](video-cost-transparency.md) and features
[011](../specs/011-video-cost-transparency/spec.md) and
[015](../specs/015-agent-cost-continuity/spec.md). The examples use checkout
`python -m avo.cli`; installed engine users use `avo` with the same cost verbs.
All examples are metadata-only. No model call, render or tariff download is
needed to record or query costs.

## Register the current executor

Save a v2 descriptor as `context.json`. This example declares a manual reporting
identity, not native measurement:

```json
{
  "schemaVersion": "2.0.0",
  "operationId": "context-edit-run-1",
  "mode": "agent",
  "agent": {
    "family": "cursor",
    "surface": "manual-export",
    "version": "manual-report",
    "role": "driver",
    "sourceSessionId": "video-session"
  },
  "scope": {
    "runAliases": ["edit-run-1"],
    "sourceInstanceId": "my-export",
    "sourceSessionId": "video-session",
    "beginning": {"kind": "declared", "reference": "beginning"}
  },
  "provenance": {
    "producer": "operator",
    "reference": "explicit scoped manual report"
  }
}
```

```powershell
python -m avo.cli costs context --project C:/videos/demo/avo.project.json --descriptor ./context.json --json
```

Use the actual current product/surface/version and reliable native session/scope
identity when available. Do not invent a native session from a working directory,
MCP client name, tool-call count or transport request ID. Omit unknown optional
identity fields; `identity-unknown` is a valid declaration. Explicit `human-ci`
mode requires a bounded scope and does not erase previously accepted agent work.

`pipeline run`, `pipeline resume` and `python -m avo.session start` accept the
same descriptor as **inline JSON**, through `--cost-context`. For example:

```powershell
$costContextJson = Get-Content -Raw -LiteralPath ./context.json
python -m avo.cli pipeline run --project C:/videos/demo/avo.project.json --cost-context $costContextJson
```

Resume retains its existing actor/reason/recovery-event requirements. Context
registration is part of that authorized lifecycle action. Missing caller context
records an expected unknown executor; it never inherits the last active host.
Read-only report/status/capability operations create no participation.

Stable caller-generated operation IDs make retries idempotent. Reusing an ID
with different metadata is rejected. Compatible explicit session/source/scope
identity can reuse participation and add aliases without another source grant.
An optional `sourceAttachment` refers to an existing binding and frozen profile;
naming a path or setting a boolean cannot grant source access. Closing a binding
narrows that grant and does not prove that the host or usage stream has closed.

## Supply usage without claiming native telemetry

The normalized observation example is in [the original guide](video-cost-transparency.md#normalized-example).
To bootstrap scoped manual evidence, use the `factId` returned by context:

```powershell
python -m avo.cli costs report-manual --project C:/videos/demo/avo.project.json --file ./manual-usage.json --participation-fact-id FACT_ID --operation-id manual-usage-1 --json
```

Both flags are required together. Agent/version/source session must match the
accepted context. This creates a manual-only frozen profile and receipt; it does
not qualify vendor telemetry. The legacy unscoped import/manual route remains
readable with its original evidence limitations.

`costs observe --file packet.json` accepts a typed v2 packet: production and
operation IDs, one frozen profile, unchanged observation payloads, separately
addressed evidence and collection receipts. Evidence nature and acquisition are
independent: imported measured evidence remains measured; imported manual data
remains manual. Each new measured claim needs its qualified source/version and
attribution proof. An exact `participationFactId` can identify accepted historical
context; omitted references require a uniquely compatible effective context.
Current selected-model hints cannot become historical served-model evidence.

Receipts, evidence and observations commit in one immutable batch. Receipt-only
terminal packets and metadata-only upgrades are valid; neither adds a fake zero
usage row. Cursor advances follow accepted commits. Truncated records, source
rotation, epoch resets, unknown versions and conflicting frontiers retain gaps.

## Handoffs, resumes and corrections

```powershell
python -m avo.cli costs transition --project C:/videos/demo/avo.project.json --request ./transition.json --json
python -m avo.cli costs reconcile --project C:/videos/demo/avo.project.json --file ./decision.json --json
```

Transition requests name explicit from/to participations, or an embedded target
declaration, plus sequential/delegation/resume/boundary-unknown mode, native
boundary, actor and reason. Delegation retains the parent and requires child
lineage. Device/account/session/epoch changes never borrow a zero counter or old
baseline. A cumulative delta requires a reliable start/end baseline; an unknown
crossing interval remains unallocated rather than split by time.

Source/grant scope is separate from responsibility intervals. A→B→A retains two
A intervals with the handoff gap between them. Explicit predecessor facts and
native boundaries establish those intervals; wall-clock order does not choose
an owner. Unknown or conflicting boundaries prevent complete coverage.

Reconciliation records retain actor, reason, proof references, exact affected
IDs and superseded decisions. Supported relations are `same-activity`,
`covers-rollup`, `revises-evidence`, `replaces-estimate`, `allocation` and
`withdraw`. They preserve all original evidence and snapshots.

- Metadata revisions use exact old/new evidence IDs for one unchanged observation
  key. Payload or served-model changes use the observation-variant correction
  path instead. A selected-model hint alone is not served-model proof.
- Known aggregates and complete known leaves contribute once. A complete leaf
  selector uses `selectedRepresentations`; its singular selector is null.
  Partial trees, unsupported composition and incompatible choices remain gaps.
- Allocations require exact producer scopes. Duplicate active assignments need
  an explicit audited supersession. Cross-production transfer/reversal follows
  exact accepted activity claims; no implicit distributed rewrite or prorating.
- Withdrawal appends a decision referencing exactly the decisions it supersedes.
  A consumed transfer cannot silently resurrect the original production's count.

For a reviewed current-context merge, `costs context` accepts
`participationId`, the entire current `predecessors` frontier and nonempty
`reason`, supplied together. Stale or foreign frontiers fail before publication.
The new fact retains the exact review reason/provenance and current requested
identity; historical usage/model payloads and old snapshots are unchanged.

## Explicit estimates

```powershell
python -m avo.cli costs estimate --project C:/videos/demo/avo.project.json --request ./estimate.json --json
```

`manual-range` requires category endpoints named `minimum`/`maximum`, a human
basis, assumptions and limitations. Counts are bounded integers, never booleans
or fractional tokens. The record retains that basis and separate ranges; it
does not fabricate a midpoint or add modeled usage to accepted usage totals.

`visible-content-tokenizer` counts only explicitly supplied UTF-8 text with a
genuinely installed local tokenizer. The supported `tokenizers-json` route needs
`tokenizerVersion`, model, encoding, `assetsDigest`, and explicit CLI-local
`assetsPath`/`mappingPath`. The mapping JSON contains exactly:

```json
{
  "schemaVersion": "1.0.0",
  "model": "operator-declared-model",
  "encoding": "operator-declared-encoding",
  "tokenizer": "tokenizers-json",
  "tokenizerVersion": "EXACT_INSTALLED_VERSION",
  "assetsDigest": "SHA256_OF_LOCAL_TOKENIZER_JSON"
}
```

The declared tuple, installed version and actual asset digest must match. AVO
does not download packages/assets or call remote token counters. Missing or
unsupported prerequisites return `unavailable` without an estimate record or a
fake zero. Only safe input digests, sizes, method/version and limitations persist;
text and local input/asset/mapping paths do not. This cannot measure hidden
context, chat framing, reasoning, cache, retries, multimodal work or an invoice.

Optional `pricingContext` explicitly supplies service provider, model, timestamp
and dimensions. Estimate creation freezes available `priceScheduleIds`; absent
or inconsistent pricing context leaves valuation unavailable while known token
estimates remain visible. Overlapping estimates/measurements stay separate or
conflicted until an exact-scope audited replacement; no automatic subtraction.

## CLI, MCP and installation boundaries

| Action | CLI input | Structured MCP input |
| --- | --- | --- |
| Context | `costs context --descriptor FILE` | `avo_costs_context(descriptor=...)` |
| Pipeline lifecycle | `--cost-context JSON` | Pipeline tool `cost_context` object |
| Manual bootstrap | `report-manual --file FILE` plus fact/operation flag pair | `avo_costs_report_manual(request=...)` |
| Observe | `costs observe --file FILE` | `avo_costs_observe(packet=...)` |
| Transition | `costs transition --request FILE` | `avo_costs_transition(request=...)` |
| Estimate | `costs estimate --request FILE` | `avo_costs_estimate(request=...)` |
| Reconcile | `costs reconcile --file FILE` | `avo_costs_reconcile(reconciliation=...)` |

MCP uses validated structured JSON, not stringified dictionaries or assumed
shared client/server paths. Estimate MCP rejects `inputPath`, `assetsPath` and
`mappingPath`; inline content can be unavailable without operator-installed
prerequisites. Existing mutation review remains in force. The transport remains
local stdio; no remote admin service or automatic host configuration is added.

`costs capabilities --json` distinguishes Codex CLI, Codex Desktop, ChatGPT,
Cursor, Claude Code, OpenCode, Gemini CLI, Cline, Windsurf and an unknown/custom
route. **No bundled host-native profile is currently qualified.** Candidate or
manual-only status is a supported honest outcome; documentation and synthetic
fixtures do not certify a vendor/version. The seven installer host profiles
remain unchanged. Skills-only installations do not supply an engine or capture
usage, and no vendor SDK, proxy, daemon or account-wide discovery is mandatory.

Typed/manual input is capped at 32 MiB and 100,000 observations. Qualified
incremental collection additionally caps a call at 8 MiB/10,000 records and a
record at 1 MiB. Budget stops or unfinished records cannot advance a false final
frontier. Split larger explicitly attributable inputs; do not disable bounds.

## Interpret reports and preserve history

Accepted usage includes measured, manual and legacy-unknown values; modeled
usage is separate. Source-reported amounts, calculated estimates, API reference
equivalents and manual allocations group by basis and unit. USD, credits and ACU
do not share an unlabeled sum. Subscription equivalents are not subscription
invoices, percentages are not universal token conversions, and local inference
does not imply zero hardware/electricity expense.

Coverage is per expected interval. Qualified semantics, conflict-free exact
attribution/bounds, known authoritative or defensible inferred totals,
applicable cumulative baselines, accepted receipt frontiers and terminal flush
proof establish `complete-for-declared-sources`. Unknown prices alone do not
erase known counts. Missing hosts, unallocated intervals or partial source
categories remain visible. Pending open/settling/unknown/none maps to v2
`pendingTurn` true/true/null/false. Closing a responsibility interval alone is
not a source flush, and a closing answer cannot meter its unfinished response.

All canonical evidence stays under `<rawDir>/edit/costs/`; normal cleanup retains
it. V2 adds participation/profile/estimate/reconciliation records and atomic
batch evidence/receipts. Reports and history capture one membership/cutoff.
Committed data after a closure is displayed as stale without read-side writes;
the next authorized mutation repairs a linked amendment using `previousClosureId`.
Old closures remain immutable. Current raw membership dominates an older copy
of the same production; copies are never summed as additional videos.

Portable exports retain safe numeric evidence and provenance with explicit
omissions, original digests and verification limits. Local source grants and
locators require reauthorization on another machine. `portable_status()` reports
those limitations outside immutable snapshot payloads. An omitted original
preimage cannot masquerade as a fully verified original snapshot.

Existing v1 bytes, identity/hash rules and exact saved-snapshot lookup remain
unchanged. New working views expose legacy-unknown evidence and historical host
gaps. There is no mass rewrite. New major schemas require a compatible runtime;
unmodified old executables cannot be forced to respect a new format marker.
Use one qualified writer runtime and a local filesystem with reliable locking/
atomic replacement; multi-host/cloud-sync merge safety is not promised.

## Validation record

The integrated accounting/public-surface suite passed 506 tests. Synthetic
regressions cover lifecycle/context, privacy, closure recovery,
portable replay, the skills-only missing-runtime boundary and normal cleanup
retention after deleting a temporary usage source. The API examples describe
implemented contracts; they do not qualify vendor telemetry. Lint/format,
architecture, duplication, dead-code and dependency-tree checks passed. Existing
working-tree complexity and dependency-audit failures remain identified in the
validation record. External-root rechecks resolved library/media fixture-harness
failures without production edits; combined same-revision coverage is 78.20%,
above the 68% floor. The completed official serial unit run repeats those
corrected harness cases and the existing complexity failure. The final quiet
100k report took 5.906732s and failed the original five-second target. On
2026-11-01 the user approved retaining the complete auditable report with a
seven-second cap for the documented local H: reference workload. The first fresh
approved-cap attempt measured 7.726554s and failed; substantial background CPU
remained after team tests exited, so idle-qualified verification is pending.
The failed sample remains recorded and the cap is unchanged. This is not a
NAS/CI or other-machine guarantee. See
the [feature validation guide](../specs/015-agent-cost-continuity/quickstart.md)
for exact results and limitations. The earlier feature-011 five-second result
belongs to its documented reference hardware and is not a current performance
claim. Required full-core media integration tests render synthetic temporary
fixtures; accounting operations do not trigger rendering, and production
footage is untouched.

On 2026-11-01 the user accepted delivery with the reference-performance
verification deferred. T056 remains open and the approved seven-second cap is
unchanged; this delivery does not claim a passing performance or aggregate
quality gate. No benchmark or idle monitor remains active.
