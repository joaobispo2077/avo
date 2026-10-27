# Code-drawn delivery notes

**Status:** Not delivered. Source/QC/approval references must be filled from
actual artifacts. No approval is granted by this template.

This Markdown note accompanies the existing native delivery manifest.
A silent FFV1/Matroska graphic and its generated receipt are source artifacts;
they are not the approved final master or a substitute delivery manifest.

## Requested result

- Project/provider and version: {{actual identity and immutable version}}
- Actual engine / route: {{code-drawn; canvas / svg / brush}}
- Purpose / promised payoff: {{describe}}
- Requested outputs: {{16:9 / 9:16 / 1:1 as requested; no automatic extra variants}}
- Loop requested: {{yes / no; declared boundary convention if yes}}
- Audio scope: {{silent graphic; canonical program mix reference or standalone plan}}
- Existing stage / approval state: {{pending / actual native state}}

## Editable source and reconstruction closure

| Required item | Actual retained path / identity | Verification / outstanding gap |
| --- | --- | --- |
| composition.json and source revision | {{pending / actual SHA-256}} | {{pending}} |
| Original input-lock.json and inputLockHash | {{pending / actual values}} | {{pending}} |
| Editable HTML/JS/CSS and scene/state data | {{actual paths/hashes}} | {{pending}} |
| Fonts, SVG/images/data and other local inputs | {{complete inventory/reference}} | {{pending}} |
| Optional drawing dependency + license | {{not used / actual pinned build/hash/license}} | {{pending}} |
| Generator/adapter, Playwright driver and managed browser executable | {{actual versions/hashes}} | {{pending}} |
| Platform / graphics context, seed and render settings | {{actual recorded identity}} | {{pending}} |
| Generated asset and asset.generated-asset.json | {{not rendered / actual paths/hashes}} | {{pending}} |
| Canonical revisions / ProofPlan / materialization | {{standalone N/A / pending / exact references}} | {{pending}} |
| Reconstruction-bundle verification | {{pending / actual receipt and coverage}} | {{pending}} |

Retain required non-text assets as well as JSON. A video or receipt alone does
not establish reconstruction. Follow existing retention policy; no cleanup
permission is implied.

## Actual outputs

| Role / variant | Path + SHA-256 + size | Dimensions / rational fps / frame count | Codec, pixel/alpha/color properties | Audio rate/channels/duration | Verification |
| --- | --- | --- | --- | --- | --- |
| Generated source graphic | {{not rendered}} | {{not measured}} | {{not measured}} | {{verify silent}} | Pending |
| Requested canonical composite / delivery | {{not rendered}} | {{not measured}} | {{not measured}} | {{not measured / justified silent scope}} | Pending |

Document actual readable re-layout for each requested 16:9, 9:16 or 1:1 output.
Inspect first/final, dense/reveal, caption/safe-area and relevant transition
states. Loop picture/audio seam checks apply only if requested.

## Review, rights and actual delivery authority

| Record | Actual path / hash / state |
| --- | --- |
| ANIMATION-EDITLOG.md and ANIMATION-SOURCE-LOG.md | {{actual references}} |
| code-drawn-review.json with exact final master profile/dependencies | {{not prepared / actual immutable package path and hash}} |
| REVIEW.md and authoritative review.json | {{pending / exact current references}} |
| Visual/alpha/color, audio/sync and accessibility QC | {{pending / actual evidence}} |
| Source rights, licenses, privacy/consent and AI/sponsorship disclosure | {{pending / source-log/audit references}} |
| Final exported-file transcript and sidecars | {{pending / exact candidate-bound references and scope}} |
| Native edit/delivery-manifest.json | {{not generated / actual path, SHA-256 and state}} |
| Native materialization / dependency lock | {{pending / exact current references}} |
| Human decision / approval identity | Pending |
| Promotion / delivered state | Not delivered |

The native manifest's candidate, dependency, transcript, review and approval
identities must match the actual final bytes. An absent record remains absent;
do not invent hashes, successful checks, reviewers or approval dates.

## Channel audio target and checks

- Documented provider/project loudness/true-peak target and source: {{pending / scoped N/A}}
- Actual tool/method, integrated loudness and true peak: {{not measured / actual results}}
- Speech/source sync, clipping/pops, mapping and intelligibility: {{pending}}
- Final-encode recheck / requested loop audio seam: {{pending / not requested}}

No fixed article loudness value becomes a universal YouTube requirement.

## Handoff and unresolved work

- Files actually supplied and editable-project location: {{actual paths}}
- Open blockers, uncertainty, stale evidence or missing source: {{list honestly}}
- Existing human decision needed, if any: {{exact candidate/package or none after recorded approval}}
- Final result: {{not delivered / blocked / actual verified native state}}


## Attach current motion identity to native delivery

After the existing candidate review, regression checks and explicit creator
approval have produced the current approved candidate snapshot, prepare a motion
review package with `--render-profile master` and the candidate's exact
`--materialization`. Then pass its actual file to the existing delivery verb:

```text
avo cli deliver prepare --project "<avo.project.json>" --candidate "<approved-candidate>" --materialization "<native-materialization.json>" --master "<new-master-path>" --motion-review "<new-review-directory>/code-drawn-review.json"
```

The native manifest records `motion.engine`, source/route/version/lock/runtime
identities, measured output contract and review package reference. This optional
metadata is validated before copying and again on delivery validation. Every
drawing source must occur in the native ProofPlan's original input lock.
An unrelated or stale source, preview, candidate or dependency blocks the join.

Native proof-plan delivery verifies the persisted immutable plan, current
original inputs, preflight and microproof gate, and exact approved candidate
snapshot. It still transcribes and reviews the copied final master through the
existing final gates, and leaves delivery approval pending. The motion package
does not replace these steps. `deliver adopt` and `adopt-human-final` retain
their existing assembly-only scope.
