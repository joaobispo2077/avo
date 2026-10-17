# /avo.direction Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Inspect direction sources → Prepare a direction proposal → Record the creator's exact disposition
**Step state source:** `providers/<provider>/direction/index.json`, immutable proposals and creator decision events
**Stopping conditions:** Missing selected sources, stale identity, required creator decision or verified completion of the requested operation
**Valid next commands:** /avo.briefstart or /avo.pipeline

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md).

Create a concise artistic direction from a provider's existing learndowns, or
inspect the AVO starting directions. This command does not edit or render video.

**Reference:** [direction.md](../../agent-skills/avo-pipeline/references/direction.md).

## Usage

```text
/avo.direction
Provider: my-channel
Keep all my learning, prioritize my last two analyses, and propose a direction for future reviews.
```

```text
/avo.direction
Show the AVO directions for a tutorial and a quieter analysis.
```

Provider synthesis needs a resolved provider workspace. It does not require a
new raw folder, new master or another learndown when existing learning suffices.

## Instructions

1. Resolve runtime/provider once through the gateway. Use shared native direction
   services; do not create a second registry or overwrite authored `DESIGN.md`.
   Default new provider-owned direction documents to that resolved provider's
   `direction/` workspace, and new document-only pilots to
   `providers/<provider>/direction/pilots/<pilot-id>/` (private/ignored, no raw or
   media). Derive the provider and path dynamically; use another location only
   when the user requests it. Actual footage projects retain their external
   `rawDir`, with project authoring records in `<rawDir>/edit/briefstart/`.
2. Preserve requested inclusion and priority. Prioritizing a video does not
   exclude other learning or approve a new provider-wide artistic conclusion.
3. Prepare bounded document evidence, group related revisions and expose gaps.
   Do not read, hash, render, transcribe or reanalyze historical media.
4. The driving agent authors a short proposal from the packet. Keep instructions,
   observations, inference, AVO defaults and technical lessons distinguishable.
   Show applicability, uncertainty and source links. Keep the summary within
   500 words; evidence stays separate.
5. Submit through native validation. Permit at most two repairs for the same
   packet, then explain remaining issues and available choices. Do not switch
   models, start a server or call a paid service silently.
6. Record accept/edit/reject/defer/qualify only from the creator's actual response
   against exact content and scope. An edit that changes content creates another
   proposal for review. Existing authorization need not be requested again when
   it already identifies that exact action and content.
7. Accepting a profile does not select it for a video, approve media, transfer
   rights, promote a component or start production. Offer the next normal step.

## Shared timeline gateway

This Admin operation changes only provider direction metadata. Profile review
is not a media-candidate gate and does not require manufacturing Watch, ASR or
render evidence. All normal source, timeline, accessibility and delivery review
requirements still apply when an actual video is produced.
