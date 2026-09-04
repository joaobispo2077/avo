# Canonical-lineage delivery fidelity

Delivery fidelity proves that a pre-master or delivered candidate matches its
declared output profile and its actual picture-carrying ancestry. It does not
compare every master with one source resolution or apply a universal bitrate.

## Applicability and defaults

The `source-fidelity` evidence kind is required at `pre-master` and `deliver`.
Earlier checkpoints are not applicable. A strict v1.1 assembly materialization
is mandatory at final checkpoints; legacy cut-proof records remain readable but
cannot prove final delivery.

The generic policy prohibits media explicitly classified as `proof` or `proxy`
when it is a base picture ancestor. It contains no platform geometry, frame
rate, duration, codec, or bitrate defaults. Those values come from an explicit
render contract. Codec bitrate rules apply only to the named codec family.

## Materialize an assembly

```text
avo tracks render --project avo.project.json --output edit/masters/master.mp4 --profile delivery --render-contract render-contract.json
```

`--render-contract` is required because output geometry and frame rate cannot be
guessed safely. `--fidelity-policy policy.json` is optional; use it to declare a
different profile ID, prohibited base classes, role rules, or setting-source
provenance. Omission keeps the generic proof/proxy base prohibition.

The immutable materialization binds current CMap, Sync, BMap, and Tracks
revision hashes; raw fingerprints; projection and render-contract hashes;
resolved policy; deterministic picture-lineage graph; producer identity; and
the actual rendered output fingerprint. Unchanged inputs reuse the record;
changed bytes or a conflicting record fail rather than overwrite it.

## Picture contributors and transformations

Base ancestry comes from ordered CMap segments. Overlay and generated nodes are
included only when the renderer actually compiles those Tracks roles.
Metadata-only Tracks `base` entries are excluded. Media class is explicit and
is never inferred from a filename.

Each trim, concat, crop, reframe, rotate, scale, grade/color, composite,
caption, and encode edge is recorded in order. Every operation must appear in
`allowedTransformations`; crop, reframe, and rotate require an approval
reference. Role rules may allow a lower-resolution overlay while still
forbidding a proof or proxy as the base/full-frame ancestor.

## Review and delivery

```text
avo review run --project avo.project.json --checkpoint pre-master --materialization edit/timeline/materializations/assembly/<record>.json
avo deliver prepare --project avo.project.json --materialization edit/timeline/materializations/assembly/<record>.json --master edit/masters/master-v001.mp4
```

The candidate defaults to the materialized output; `--candidate` may name
another path only when its bytes are identical. Review derives canonical
dependencies and adds materialization, policy, and lineage hashes to candidate
identity. Policy or timeline changes stale prior evidence.

Evaluation order is: record/output hashes, current locks, graph and contributor
hashes, declared transformations, probed render contract, then prohibited
picture ancestry. A profile or ancestry violation is `fail`. Missing, stale,
contradictory, or invalid prerequisites are `error`/`blocked` with exact
remediation. Delivery copies only matching bytes and retains the materialization
path/hash, output hash, policy hash, lineage hash, and root IDs in
`delivery-manifest.json`.

## Migration and next action

Existing proof review continues unchanged. A legacy final review without
canonical lineage blocks with instructions to rerun `avo tracks render` using a
render contract; it is never inferred as pass. Fix profile defects at the owning
render stage, re-materialize stale inputs, rerun `pre-master`, obtain human
approval, then run `deliver prepare` and `deliver approve`.

Platform-named profiles must be checked against current official platform
documentation before release. Example profile values in specifications are
contract illustrations, not shipping defaults.

## Current-source audit

Accessed 2026-09-02: YouTube's official
[recommended upload settings](https://support.google.com/youtube/answer/1722171?hl=en)
say to preserve recorded frame rate, describe bitrate values as recommendations
rather than limits, and scope those recommendations by resolution/frame-rate
class. Its official
[resolution and aspect-ratio guidance](https://support.google.com/youtube/answer/6375112?co=GENIE.Platform%3DDesktop&hl=en)
also says the player adapts to vertical and square media. Therefore AVO keeps
platform values in an explicitly selected profile and does not ship a universal
source-resolution or bitrate rule.
