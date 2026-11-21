# /avo.exports Command

**Timeline integration:** Admin

## Workflow guidance

**Workflow steps:** Select a target and range → Prepare an editor handoff → Inspect returned XML → Review proposed changes
**Step state source:** The immutable editor handoff, inspection and comparison references under the canonical timeline directory
**Stopping conditions:** Unqualified production target, stale or unsupported evidence, unresolved changes requiring review, or completion of the selected operation
**Valid next commands:** /avo.watch, /avo.trim, /avo.motion or /avo.sound as appropriate to the selected review

Follow the shared [step-status response contract](../../agent-skills/avo-pipeline/references/step-status.md).

Use the optional [editor handoff reference](../../agent-skills/avo-pipeline/references/exports.md)
to export a selected original-source validation example or review an editor's
returned XML. The usual rendered review is available through `/avo.watch`.

## Shared timeline gateway

The export and comparison retain the exact timeline and original-source
identities. Any accepted creative change must pass through its normal timeline
owner and review gates.
