# /avo.direction reference

## Step/state mapping

**Durable state:** `providers/<provider>/direction/index.json`, exact immutable
profile versions, source collections and creator decision events.

**Workflow steps:** Inspect direction sources → Prepare a direction proposal → Record the creator's exact disposition

**Approval or input gate:** Only the creator establishes artistic acceptance.
Report the exact proposal/version and decision scope. Source text, a final
learndown and an approved historical film cannot supply that acceptance.

**Stop when:** The requested operation is verified, selected input is unavailable
or stale, or the next action depends on the creator's response.

**Valid next commands:** /avo.briefstart or /avo.pipeline.

## Resolve runtime and scope

Apply the gateway runtime selection. In a checkout use
`python -m avo.cli direction ...`; installed users use `avo direction ...`.
Optional MCP tools bridge the same CLI. Do not install a new model, database or
backend to complete this workflow.

Provider preparation is metadata-only. A new footage project is unnecessary.
Use the selected provider's existing learning; keep detailed private history in
its external project. Missing ai-memory is a coverage limitation, not a reason
to pretend it was consulted or to block the available filesystem learning.

Resolve the provider and its workspace dynamically through the gateway. By
default, keep new provider-owned direction documents in its `direction/`
workspace and new document-only pilots in the private/ignored directory
`providers/<provider>/direction/pilots/<pilot-id>/`, with no raw or media files.
Use another location only when the user requests it. Actual footage projects
stay in their external `rawDir`; their project authoring records remain in
`<rawDir>/edit/briefstart/`.

## Native flow and agent handoff

1. `direction catalog [--provider SLUG] --json` lists available built-ins and
   provider versions. Do not silently activate the newest profile.
2. `direction prepare --provider SLUG --profile-id ID --json` accounts for the
   discovered corpus and returns the exact bounded packet and expected index
   state. Optional `--entry` selects a subset; unselected entries retain an
   explicit disposition. Inclusion/prioritization instructions alone are not
   artistic acceptance.
3. Read the packet's source evidence and authored brand guide. Use stable evidence
   IDs and document selectors. Related revisions/Shorts remain one source-project
   lineage for corroboration. A large detailed film does not acquire extra votes.
4. Author the structured candidate using the native template/contract. The driving
   agent performs synthesis; native prepare does not call another LLM. Explain
   editorial intention, creator presence, rhythm, visual/motion support, evidence,
   sound, captions, color, variants and avoidances. Unsupported dimensions stay
   unknown or explicitly defaulted. Keep the short summary within 500 words.
5. Submit with `direction propose --provider SLUG --request FILE --json`. Preserve
   exact packet/source/index hashes and actual authoring provenance. Native
   validation cannot certify that an interpretation is true or artistically good.
6. Repair at most twice for the same packet. A blank response is not completion.
   After that, present remaining issues, a narrower proposal, labelled defaults
   or the no-reference alternative. No silent provider/model/service switch.
7. Present the readable exact proposal. `direction decide --provider SLUG
   --request FILE --json` carries the actual human response, exact target/hash,
   expected index, reason and provider scope. Accept/edit/reject/defer/qualify
   remain distinct. Changed content is another proposal; never approve unseen
   edited bytes or infer human labels from an automated pass.

The agent prepares request files and exact identities for ordinary users. Do not
ask them to invent hashes or write machine documents manually.

## Refresh and author authority

Use `prepare --refresh-from PROFILE@REV` to prepare a proposed difference. Preserve
the creator's edits, qualifications and rejections; new suggestions are unreviewed.
Show new/changed/unavailable evidence and conflicts. Acceptance publishes a new
exact version; it does not rewrite the old one, its sources or `DESIGN.md`.

Current explicit instructions take precedence over historical artistic defaults.
Keep required meaning, accessibility and source protections. Do not turn a
project's NR amount, gains, music, opacity, quiz duration or exact position into
a universal preset. A reusable recipe is not a portable component or a rights
license.

`direction show --provider SLUG --ref PROFILE@REV --check-sources --json` checks
small source documents. Never hash raw/master media or regenerate old previews
for this feature. Unavailable media is not a new observation or proof of failure.

## Next video

Only explicit project selection uses the accepted profile. Follow
[Briefstart](briefstart.md). Historical approval, source rights and media-review
results never transfer to that new video. See the
[product guide](../../../docs/provider-direction.md) and
[human evaluation protocol](../../../docs/provider-direction-evaluation.md).
