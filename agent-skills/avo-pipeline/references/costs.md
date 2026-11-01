# Recorded video costs

## Workflow guidance

**Workflow steps:** Resolve video or history scope -> Read recorded usage -> Verify and report costs
**Step state source:** external video's edit/costs/ or portable provider cost export
**Stopping conditions:** Ambiguous context, invalid evidence, or verified cost report
**Valid next commands:** /avo.pipeline, /avo.learndown, /avo.cleanup

Use `python -m avo.cli costs --project <avo.project.json>` in a checkout or `avo costs --project <avo.project.json>` with the installed engine. `/avo.metrics` is an exact alias. `--history` queries known local ledgers, `--phase NAME` filters a report, and `--trends` compares recorded cohorts. `--json` exposes the same values for tools. Reports never discover raw host logs, collect sources, mutate a ledger, initiate inference or query billing accounts.

## Explicit context and continuity

At session start/pipeline run or resume, pass an available metadata-only descriptor using `--cost-context <JSON>`. Standalone registration uses `costs context --descriptor <file> --project <project>`. Use the shipped v2 descriptor contract: operation ID, explicit mode, available agent family/surface/version/role and source session, attributable scope/boundaries, and provenance. Retry unchanged input with the same operation ID; a distinct entry/change gets a new ID. Never include prompts, conversations, tool arguments or secrets.

Registration records expected participation, not consumption, and reads no source. Omission creates unknown expected-host coverage. Never borrow a previous host, infer human/CI from absent metadata, or turn MCP client/request IDs into a conversation binding. Explicit human/CI execution needs bounded scope. A model/agent change preserves `accountingVideoId` and earlier evidence; use explicit `costs transition` requests for sequential/concurrent work and parent relationships. Starting another agent does not implicitly end the old interval.

## Contribution and qualification

Use `costs capabilities` to inspect Codex CLI, Codex Desktop, ChatGPT, Cursor, Claude Code, OpenCode, Gemini CLI, Cline, Windsurf and unknown-agent rows. Capability state describes **bundled native qualification**. Public vendor documentation and synthetic contract fixtures are candidates, not a qualified collector; this release bundles no qualified native vendor profile. Unknown versions never inherit a reviewed version's guarantees.

All rows retain explicit context, typed packets, normalized import, manual evidence and scoped estimates. `costs observe --file <packet> --project <project>` admits strict v2 packets with evidence nature, source/profile, attribution and receipts. A manually supplied contribution remains manual; importing provider measurement is measured only with an authorized qualified exact-version profile and actual source proof. Normalized legacy `costs import --file <metadata-json>` and `costs report-manual` remain available without retroactively certifying old observations.

From a blank runtime, first register `costs context --descriptor <metadata-json>`, then use `costs report-manual --project <project> --file <normalized-observations-json> --participation-fact-id <returned-factId> --operation-id <stable-manual-operation>`. Both opt-in flags are required together. This validates the exact declared agent/source scope and freezes a deterministic **manual-only** profile; the response returns its `profileId` for subsequent typed manual `observe` packets. It certifies no native source or served model. Without those flags, `report-manual` keeps its legacy behavior.

MCP can bootstrap without shared files using `avo_costs_report_manual(request={schemaVersion:"2.0.0", operationId, participationFactId, observations:[normalized metadata]})` after an explicitly reviewed context registration. A request string containing a client path is invalid metadata. Scope/type/qualification failures are rejected before a manual profile is published; the store's final claim checks remain authoritative.

MCP accepts structured `descriptor`/`packet` objects and keeps mutation review. Client and server paths may differ; a client path grants no server-side read. SDK/exec/headless wrappers and CI may contribute usage already emitted by the client/job they control. Do not launch another agent or API request merely to measure one.

Installed engine and checkout use the same accounting services. With skills only and no available engine/checkout/MCP runtime, prepare metadata or explain the missing runtime; no ledger mutation/collection has executed. Do not silently clone/install a runtime, add vendor SDK dependencies, activate hooks/OTel, alter global logging or poll admin/account APIs to obtain cost data. Normal runtime setup for the requested editing workflow follows the gateway's Runtime rules.

## Authorized local sources

Bind only a user-authorized local source/session/boundary using `costs bind --project <project> --source <local-file> --agent <id> --session-id <source-session> --boundary <last-prior-request|beginning> --format normalized`. `beginning` deliberately includes the attributable session interval; never silently attach unrelated prior conversation. Before reusing a session for another video, close its existing grant with `costs close-binding --binding-id <id> --end-boundary <last-video-request> --project <project>`.

Automatic collection additionally requires an explicit accepted context `sourceAttachment` linking that grant to its frozen qualified exact-version profile. Registration alone neither creates this qualification nor reads the file. A qualified normalized JSONL profile enables bounded incremental reads; the cursor is committed atomically with accepted evidence/receipts. It assumes immutable prior records in an append-only source; bounded replacement probes cannot prove arbitrary old in-place mutations. Large snapshots use scoped/manual fallback. Manual imports retain their 32 MiB/100,000-record limit.

Refresh explicitly with `costs collect --project <project>`. No-new-rows replay adds no observations. Source loss, denied access, unknown versions, missing baselines, copied history and resets retain accepted data and produce scoped diagnostics; editing continues. Cumulative sources require native epochs and proven baselines. EOF is never terminal/flush proof, and unknown lineage remains unallocated. Generic `--format codex` is denied because a per-turn/line-index interpretation would be unsafe; supply a qualified normalized cumulative packet or explicit manual/estimate evidence. Existing Claude/Gemini request and OpenCode message projections remain legacy imports with unknown native version, not automatic measured qualification.

## Surface limits and values

Cursor selected router/Auto configuration is not each request's served model/provider. Claude main-loop, tree and last-request counters differ, and resume/fork semantics depend on version. OpenCode fork copies can have new IDs and step/message representations can overlap. Gemini chunk hooks are not additive requests. Cline current/total/cache scope needs temporal proof. Legacy Windsurf and successor Devin have different account keys, units and availability. ChatGPT visible replies and MCP calls do not expose all hidden product operations.

Keep missing model/provider/token categories unknown. Known source money remains available when model-based pricing cannot be computed. Keep money basis and native units explicit: SDK estimated money and API-equivalent valuation are not subscription invoices; quota percentages, ACU and CREDITS do not imply token counts or currency. Estimates describe only their declared supplied-content/manual scope, never hidden operations or a proven lower bound. No tokenizer/model download or remote token-count call is implicit.

## Completion reporting

After `/avo.learndown`, automatically show the persisted draft summary before the step-status footer: evidence/valuation basis, coverage, cutoff and pending state. Next step remains cleanup. After verified `/avo.cleanup` and final wrap/export, show the final persisted summary with the same disclosures. Unknown cost coverage does not itself block editing or prove zero usage; unknown pending state remains unknown.

Failed cleanup cannot claim closure. If accounting/export fails after successful deletion, retry accounting/export only. Late usage creates an immutable amendment; never rewrite historical snapshots or generate recursive closing responses to meter the current reply. Raw conversations/local source locators are not portable learndown artifacts.

Follow [step-status.md](step-status.md); no text follows its four-line footer. Documentation and synthetic usage examples: [video cost transparency](https://github.com/joaobispo2077/avo/blob/main/docs/video-cost-transparency.md).
