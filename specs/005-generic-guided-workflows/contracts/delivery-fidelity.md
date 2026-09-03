# Contract: Canonical-Lineage Delivery Fidelity

## Applicability

Evidence kind remains `source-fidelity`. It is `not-applicable` before `pre-master` and `deliver`. At those checkpoints a canonical assembly materialization is mandatory.

## Assembly materialization

Add a strict `avo.materialization` schema. New assembly materializations contain:

```json
{
  "schemaVersion": "1.1.0",
  "kind": "assembly",
  "canonicalInputLock": {
    "cmapRevisionHash": "<sha256>",
    "syncRevisionHash": "<sha256>",
    "bmapRevisionHash": "<sha256>",
    "tracksRevisionHash": "<sha256>",
    "rawFingerprints": {}
  },
  "projectionHash": "<sha256>",
  "renderProfile": "delivery",
  "renderContract": {},
  "pictureLineage": {},
  "pictureLineageHash": "<sha256>",
  "deliveryFidelityPolicy": {},
  "deliveryFidelityPolicyHash": "<sha256>",
  "output": {"locator": "...", "sha256": "<sha256>"},
  "producer": {},
  "materializationHash": "<sha256>"
}
```

`renderProfile` remains for compatibility. Cut/motion proof records remain readable without the new fields; only pre-master/deliver require them.

## Render-contributor graph

`pictureLineage` is a deterministic directed graph:

- Base nodes come from ordered CMap segments and exact raw/source fingerprints.
- Overlay nodes include only roles actually compiled by the renderer.
- Generated nodes record generator identity and input fingerprints.
- Edges record trim, concat, crop, reframe, rotate, scale, grade/color, place/composite, captions, and encode operations with parameters.
- Geometry/editorial transformations carry an approval reference when the active policy requires one.
- Tracks entries ignored by the render graph, including metadata-only base entries, are not ancestors.
- No proof/proxy classification is inferred from a filename.

## Resolved policy

```json
{
  "policyId": "avo.delivery-fidelity",
  "profileId": "youtube-1080p",
  "policyHash": "<sha256>",
  "settingSources": {},
  "renderContract": {
    "width": 1920,
    "height": 1080,
    "displayAspectRatio": "16:9",
    "frameRate": {"num": 30000, "den": 1001, "tolerance": 0.001},
    "durationToleranceSec": 0.05,
    "allowedTransformations": ["crop", "reframe", "scale-down", "color-convert", "encode"],
    "encodingRules": {
      "h264": {"minimumBitRate": 12000000}
    }
  },
  "prohibitedBaseClasses": ["proof", "proxy"],
  "roleRules": {}
}
```

Encoding rules are optional and codec-family-specific. Values in the example are illustrative contract shapes, not shipping platform defaults. A platform-named profile MUST be verified against current official platform documentation before release. No global resolution or bitrate floor exists. Role rules may allow lower-resolution overlays while still forbidding a proof/proxy as the base/full-frame ancestor.

## Evaluation order

1. Validate the materialization content hash and candidate/output byte hash.
2. Verify current approved revision locks and explicit dependency agreement.
3. Validate complete graph roots, contributor hashes, and lineage hash.
4. Verify each transformation is declared and permitted.
5. Probe the candidate and compare it with the resolved render contract.
6. Traverse picture-carrying ancestors and reject prohibited classes by role/placement.

Outcomes:

- Profile or ancestry violation: evidence `fail`, review finding identifies exact node/artifact and remediation.
- Missing, stale, contradictory, or invalid materialization/policy/lineage: evidence `error`; review state `blocked` with prerequisite such as re-materializing the current assembly.
- Complete compliant candidate: `pass`.

Structured evidence details include policy ID/hash/source, materialization path/hash/output hash, lineage hash/root IDs/offending node IDs, and evaluated render contract.

## CLI and delivery integration

- `review run --checkpoint pre-master|deliver` requires `--materialization`; ad hoc `--candidate` plus dependency hashes is insufficient.
- The review runner derives dependencies from the materialization lock, includes materialization/policy hashes, and passes the complete context to deterministic QC.
- Policy changes make existing evidence stale.
- Delivery preparation verifies copied master bytes against materialization output and persists materialization, policy, and lineage references in `delivery-manifest.json`.

## Compatibility

- Existing cut-proof and motion-proof paths continue unchanged.
- Existing evidence kind stays stable and new structured details are optional in the schema.
- Legacy pre-master/deliver without canonical lineage blocks with explicit re-materialization guidance; it is never inferred as pass.
