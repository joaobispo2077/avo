# Timeline migration and recovery

The Python runtime owns migration. Start with read-only inspection and planning; do not edit the legacy EDL or canonical indexes by hand.

```bash
python -m avo.cli migrate-timeline inspect --project <rawDir> --edl <rawDir>/edit/edl.json --video-id <id> --json
python -m avo.cli migrate-timeline plan --project <rawDir> --edl <rawDir>/edit/edl.json --video-id <id> --json
```

`inspect` and `plan` write nothing. Apply only after the report identifies every source fingerprint and any information loss:

```bash
python -m avo.cli migrate-timeline apply --project <rawDir> --edl <rawDir>/edit/edl.json --video-id <id> --actor <actor> --reason <reason> --json
python -m avo.cli migrate-timeline validate --project <rawDir> --edl <rawDir>/edit/edl.json --video-id <id> --actor <actor> --reason <reason> --json
python -m avo.cli migrate-timeline activate --project <rawDir> --edl <rawDir>/edit/edl.json --video-id <id> --actor <actor> --reason <reason> --json
```

Activation is blocked when legacy approvals cannot be bound to exact candidate and dependency hashes. If the creator accepts that those approvals remain unknown, repeat `activate` with `--confirm-unknown-approvals`. Migration never invents approval from filenames, modification times, prose, or old checkboxes.

Legacy ranges become provisional raw-based CMap segments. Supported overlays, SFX, music, captions, animation facts, and verifiable Sync facts become provisional BMap, Tracks, Animation, and SyncMap state. Bespoke helper code is never imported. Apply is idempotent for the same source/tool configuration and blocks on changed input or target collision.

Canonical state becomes authoritative only after validation and activation. It regenerates `edit/edl.json` as a compatibility projection. A hand-edited generated EDL mismatch blocks rather than becoming truth. Rollback changes the authority pointer without deleting canonical history or modifying the legacy EDL:

```bash
python -m avo.cli migrate-timeline rollback --project <rawDir> --edl <rawDir>/edit/edl.json --video-id <id> --actor <actor> --reason <reason> --json
```

Before cleanup, build and verify the reconstruction bundle from the dependency graph:

```bash
python -m avo.cli cleanup bundle --project <rawDir> --video-id <id> --master-basename <master> --actor <actor> --json
python -m avo.cli cleanup verify --project <rawDir> --video-id <id> --master-basename <master> --json
python -m avo.cli cleanup dry-run --project <rawDir> --video-id <id> --master-basename <master> --json
```

Cleanup preserves raw identities, the exact master and master-derived transcript, all five canonical indexes, required immutable revisions/events, review evidence, and decisions needed for reconstruction. Bulky proofs are eligible for pruning only after their hashed references are recorded and the bundle verifies.

## Compatibility and migration limits

The legacy EDL and direct cut-proof record remain readable for one documented
compatibility window. They never regain canonical write authority. Migration
inventory records old proofs and helper outputs, but proof media stays excluded
from new render ancestry and footage-specific helper code is not imported.

After migration, create new proofs only from canonical revisions, original
sources, current generated-asset records, exact implementation references, and
the current ProofPlan. Preserve iteration ledgers, candidate snapshots,
regression evidence, final timeline-learning snapshots, selected still records,
provider-component decisions, and project-local component source required to
reconstruct an approved candidate before removing bulky working media.
