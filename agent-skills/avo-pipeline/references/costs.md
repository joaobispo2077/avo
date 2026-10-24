# Recorded video costs

## Workflow guidance

**Workflow steps:** Resolve video or history scope -> Read recorded usage -> Verify and report costs
**Step state source:** external video's edit/costs/ or portable provider cost export
**Stopping conditions:** Ambiguous context, invalid evidence, or verified cost report
**Valid next commands:** /avo.pipeline, /avo.learndown, /avo.cleanup

Use `python -m avo.cli costs --project <avo.project.json>` in a clone or `avo costs --project <avo.project.json>` with the installed engine. `/avo.metrics` aliases `/avo.costs`. `--history` queries declared local history; `--phase NAME` filters a current report; `--trends` compares recorded completed-video cohorts. `--json` exposes the same values for tools.

Read-only reports never initiate paid calls or remote billing requests. Refresh explicitly with `costs collect --project <project>`. Report cutoff and pending turn. Do not promise automatic exact metering: inspect `costs capabilities` for documented local import shapes and fallback modes.

At pipeline start, initialize through the normal session workflow. When a user provides an agent usage source, bind it explicitly using `costs bind --project <project> --source <local-file> --agent <id> --session-id <source-session> --boundary <last-prior-request|beginning> --format <normalized|codex|opencode|claude|gemini>`. `beginning` deliberately includes all attributable requests from that source session. Never bind unrelated prior conversation silently. Use `costs close-binding --binding-id <id> --end-boundary <last-video-request> --project <project>` before reusing a session for another video. A model/service switch within one video keeps the binding and preserves each event's original model/service; switching agents adds an explicitly scoped binding.

Normalized/manual imports accept only usage metadata described in the shipped `avo.cost-observation` schema. Use `costs import --file <metadata-json> --project <project>` or `costs report-manual ...`. Native exports may contain conversations: retain only the projected metadata, never copy the original export to provider learndowns. Where model/provider identity or a tariff is unavailable, leave it unknown. Account plan percentages and native credits do not imply token counts or a cash invoice.

After `/avo.learndown`, automatically show the persisted draft cost/token summary before the step-status footer, including basis, coverage, cutoff and pending turn; next step remains cleanup. After verified `/avo.cleanup` and final wrap/export, automatically show finished-video cost/token summary with the same disclosures. Failed cleanup cannot claim closure. If accounting/export fails after successful deletion, retry accounting/export only. Late usage creates an immutable amendment and never rewrites prior final snapshots.

Follow [step-status.md](step-status.md); no text follows its four-line footer. Documentation and synthetic usage examples: [video cost transparency](https://github.com/joaobispo2077/avo/blob/main/docs/video-cost-transparency.md).
