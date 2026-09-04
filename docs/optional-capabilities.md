# Optional AVO capabilities

Optional behavior is configured as named fields or invocation flags. Omitting a
field preserves AVO's generic default; it never selects a private project,
language, topic, device, or footage path.

## Purpose

The `--watch-*` controls tune one Watch execution without changing mandatory
review gates. Persistent equivalents let a global install, provider, registry
entry, or footage project declare reusable policy.

## Applicability

These controls apply to `avo review policy` and `avo review run`. Delivery uses
the same resolved persistent policy. They do not disable Watch or human approval.

## Default

`whisperModel=inherit`, `device=auto`, `maxFrames=18`,
`repairMaxFrames=8`, `analysisAttempts=2`, `toolAttempts=3`, no custom working
directory, and no undeclared format, language, criteria, or risk notes.

## Accepted values

| Flag | Accepted value |
| --- | --- |
| `--watch-whisper-model` | `inherit` or a configured model identifier |
| `--watch-device` | `auto`, `cpu`, `cuda`, or `cuda:N` |
| `--watch-max-frames` | integer 1–64 |
| `--watch-repair-max-frames` | integer 1–64 and no greater than `maxFrames` |
| `--watch-analysis-attempts` | integer 1–3 |
| `--watch-tool-attempts` | integer 1–3 |
| `--watch-working-directory` | path contained by `rawDir` |
| `--watch-format` | declared format text |
| `--watch-language` | declared language text |
| `--watch-acceptance-criterion` | repeatable non-empty criterion |
| `--watch-risk-note` | repeatable non-empty risk note |

## Scope and precedence

Fields resolve independently in this order: global → provider → registry →
project → invocation. Later arrays replace earlier arrays. Nested objects merge
by field; an unrelated project cannot inherit another project's resolved state.

Use invocation flags for a one-run constraint or experiment. Persist stable
organization-wide behavior globally, channel behavior in provider routing
overrides, video-family bootstrap values in registry defaults, and facts about
one footage project in `avo.project.json`.

## Failure behavior

Invalid values or paths fail before Watch starts. Missing, malformed, refused,
uncertain, or incomplete Watch evidence blocks or requests human judgment; it
never becomes an implicit pass. Only `device=cpu` forces
`CUDA_VISIBLE_DEVICES=-1`.

## Examples

```text
avo review policy --project C:/footage/avo.project.json --watch-device cpu
avo review run --project C:/footage/avo.project.json --candidate edit/proof.mp4 --dependency cmap=<sha256> --watch-language en --watch-risk-note "third-party screen"
```

Persistent project example:

```json
{"watch":{"device":"auto","format":"tutorial","acceptanceCriteria":["UI labels remain readable"]}}
```

## Artifact effects

`review.json` records the effective values, setting sources, policy hash, prompt
hash, declared context, actual tool/model, outcome kind, and raw attempts.
Changing the resolved policy changes candidate evidence identity and makes old
evidence stale.

## Valid next workflow action

After `avo review policy`, run `avo review run` with the inspected settings.
After a passing review, proceed to the declared human approval gate. For
`blocked` or `needs-human-judgment`, perform the exact remediation in the review
package and rerun the same candidate.

## Shorts location controls

`--raw-dir` selects the footage project that owns `edit/shorts`; v1.1 requires
it. `--batch-dir` optionally chooses a nested root under that directory and must
end with `batchId`. Defaults are the canonical project root and
`<rawDir>/edit/shorts/<batchId>`. Invalid containment, identity, plan placement,
or index collisions stop before work. The selected root and source are recorded
in request, plan, status, index, and delivery artifacts. After resolution,
review the immutable plan; full behavior and examples are in
[`shorts-batch-paths-and-lineage.md`](shorts-batch-paths-and-lineage.md).

`--delivery-dir` is not a general location flag. It is a deprecated v1.0-only
compatibility option that records `legacyExternalDelivery`; v1.1 rejects it and
directs the user to resolve the batch with `--batch-dir`.

## Delivery-fidelity controls

`avo tracks render --render-contract <json>` requires an explicit geometry,
frame-rate, transformation, and optional codec-scoped encoding contract. The
optional `--fidelity-policy <json>` supplies a profile ID, prohibited base
classes, role rules, and provenance. Without it, AVO uses no platform output
defaults and only prohibits explicitly classified proof/proxy base ancestry.
Invalid or contradictory policy stops before render; policy and contract hashes
become immutable materialization identity.

At `pre-master` and `deliver`, `--materialization <json>` is required. It derives
current timeline dependencies and binds policy, lineage, and output bytes into
review and delivery records. Missing or stale prerequisites block with a
re-materialization action. See [`delivery-fidelity.md`](delivery-fidelity.md).

## Current-source audit

Reviewed 2026-09-02 against runtime help, schemas, command wrappers, and the
official YouTube
[upload settings](https://support.google.com/youtube/answer/1722171?hl=en) and
[aspect-ratio guidance](https://support.google.com/youtube/answer/6375112?co=GENIE.Platform%3DDesktop&hl=en).
Every new control above states applicability, default behavior, accepted shape,
scope, failure behavior, artifact effect, example or linked example, and next
workflow action. Platform values remain opt-in profile data.
