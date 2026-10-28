# Motion review notes

**Status:** Pending. No checks or approval are asserted by this template.
**Human decision:** Pending.

This is a human-readable companion to the existing candidate-bound review.json.
Editing this file cannot create machine evidence, freshen stale evidence or
grant promotion. Use the existing ReviewRunner, humanWatch/transcript package
and explicit user decision; there is no second approval gate here.

## Exact subject of this review

| Identity | Actual value |
| --- | --- |
| Stage / checkpoint | {{standalone asset / canonical proof / pre-master / delivery}} |
| Candidate path | {{not rendered / actual path}} |
| Candidate SHA-256 and size | {{not computed / actual fingerprint}} |
| Canonical revision / dependency-lock identity | {{not bound / exact references}} |
| ProofPlan and assembly materialization | {{not applicable / pending / exact references}} |
| Composition manifest / original input lock | {{pending / actual paths and hashes}} |
| Generated-asset receipt | {{pending / actual path and record hash}} |
| code-drawn-review.json / reviewHash | {{not prepared / actual immutable path and file SHA-256}} |
| review.json / review-contract identity | {{pending / actual references}} |

A standalone FFV1 graphic is a silent source asset. A canonical composite review
requires admitted current inputs and the actual reconstructed picture/audio.

## Prepare previews from the exact candidate

Installed engine example, with actual paths substituted:

```text
avo cli animation code-drawn-review --candidate "<candidate>" --source-receipt "<asset.generated-asset.json>" --output "<new-review-directory>" --project "<avo.project.json>" --materialization "<native-materialization.json>" --render-profile master --json
```

For a source checkout, replace `avo cli` with `python -m avo.cli`.
Repeat `--source-receipt` for each drawing ancestor. Use
`--sample-frame <integer>` and `--transition <start:end>` for relevant
half-open ranges. Add `--loop` only when a loop was requested. Without a
materialization, standalone review requires the receipt's exact generated
output bytes; a receipt cannot authorize an unrelated composite.

The new directory contains `code-drawn-review.json`, contact sheets,
full-size and small-display sampled frames, and requested transition/loop
strips. It binds candidate bytes, output dimensions/rate/count, source manifest,
original input lock, receipt, runtime/dependency identities and preview hashes.
Prepared/decoded previews remain `needs-human-judgment` with no approval;
they do not claim inspected frames, full Watch coverage, listening or a seamless
loop. Inspect the actual candidate and record findings through the existing
review process. A two-frame loop strip is a seam aid, not playback verification.

## Actual coverage and evidence

| Frame/time/range | Reason | Evidence path + hash | Requested / decoded / inspected | Result or gap |
| --- | --- | --- | --- | --- |
| {{0}} | First encoded frame | {{pending}} | {{pending}} | {{unreviewed}} |
| {{N-1 at recorded rate}} | Final encoded frame | {{pending}} | {{pending}} | {{unreviewed}} |
| {{actual}} | Densest state / readable hold | {{pending}} | {{pending}} | {{unreviewed}} |
| {{actual}} | Reveal / scene boundary / transition strip | {{pending}} | {{pending}} | {{unreviewed}} |
| {{actual}} | Small phone-size view / caption collision | {{pending}} | {{pending}} | {{unreviewed}} |

Record contact sheets and relevant before/through/after transition strips.
Keep maximum coverage gaps and failed samples visible. The mathematical
duration endpoint is excluded; the final encoded sample is frame N-1.

## QC observations

| Category | Actual check/evidence | Status / blocker |
| --- | --- | --- |
| Meaning, facts, attribution and promised payoff | {{pending}} | Unreviewed |
| Readability, contrast, safe areas and holds | {{pending}} | Unreviewed |
| Captions / essential meaning beyond color or motion | {{pending or scoped N/A}} | Unreviewed |
| Flashing, camera motion / reduced-motion treatment | {{pending}} | Unreviewed |
| Independent seeking / decoded-frame parity | {{actual native evidence or pending}} | Unreviewed |
| Alpha/color over test backgrounds and actual canonical composite | {{pending or scoped N/A}} | Unreviewed |
| Canonical audio preservation, sync, intelligibility, pops/mapping | {{pending or documented silent scope}} | Unreviewed |
| Requested variant re-layout / loop picture and audio seam | {{pending or not requested}} | Unreviewed |
| Rights, privacy and disclosure | {{source-log/review reference or pending}} | Unreviewed |

## Timestamped findings and rechecks

| Finding ID | Candidate SHA-256 | Frame/time range | Severity / observation or inference | Evidence / correction | Status |
| --- | --- | --- | --- | --- | --- |
| {{id}} | {{actual, not a placeholder digest}} | {{actual range}} | {{class and uncertainty}} | {{reference and proposed fix}} | {{open / fixed awaiting recheck / resolved}} |

| Finding ID | Observation / fix / recheck timestamps | Fix source/canonical revision | New candidate SHA-256 | Rechecked range / evidence hash | Actual result / remaining uncertainty |
| --- | --- | --- | --- | --- | --- |
| {{id}} | {{actual timezone-aware dates}} | {{reference}} | {{not rendered / actual hash}} | {{not rechecked / actual evidence}} | {{pending}} |

A changed source, candidate or dependency invalidates affected evidence.
A self-score, elapsed time, empty checklist or lack of user response is not
approval.

## Existing review and human authority

- Deterministic checks: {{pending / actual evidence references and result}}
- Watch coverage, contradictions and blockers: {{pending / exact current record}}
- Candidate/final-file transcript and terms/names review: {{pending / actual result/scope}}
- Human watch/listening package shown: {{pending / exact paths and identity}}
- Explicit user decision and existing approval identity: {{pending}}
- Promotion status: {{blocked / actual native state after recorded decision}}

Do not mark the human decision or promotion as complete on the user's behalf.


The machine finding record binds its original candidate and frame range, an
explicit fix revision/time and a later recheck against the current candidate,
dependency lock and hashed preview evidence. A failed or missing recheck cannot
resolve a finding. The review package is immutable; prepare a new directory for
a changed candidate, source, dependency, preview or finding disposition.
