# /avo.trim reference

## Step/state mapping

**Durable state:** pipeline-run.json plus the current canonical timeline revision

**Workflow steps:** Validate trim prerequisites → Run trim → Verify and report the trim result

**Approval or input gate:** Pause whenever required input or a human decision prevents the next declared step; report the exact reply or artifact needed.

**Stop when:** Missing required input, a failed or stale gate, a required human decision, or verified trim completion

**Valid next commands:** /avo.watch

Edit-only path. See [`SKILL.md`](../../../SKILL.md) Hard Rules for cut correctness.
Cut workflow detail: [`cuts.md`](cuts.md).

## Workflow

1. Diagnose the format, viewer promise, source limitations and protected holds.
2. Inventory fingerprinted originals and approve current Sync or explicit N/A.
3. Transcribe for search; packed timestamps do not prove safe cut edges.
4. For opted-in cutting, call the shared `trim analyze` operation with effective
   family/intensity and optional canonical `scope.segmentIds`.
5. Review immutable proposal classifications, source evidence and every-join audit.
6. Use `trim preview` for contextual native windows. Unobserved words, unavailable
   alignment, conflicts and failed encoded checks remain blocked or uncertain.
7. Use `trim decide` with exact proposal/verification hashes; then `trim apply`
   authors CMap. EDL is a generated projection, never the selection authority.
8. Rebuild and verify the complete proof from current canonical originals. Obtain
   separate exact-candidate human approval before later export stages.

All five operations (`analyze`, `preview`, `decide`, `apply`, `status`) share the
Python service and command handlers used by the CLI. Evidence lives under the
footage project, not the repository. Explicitly provision optional local alignment
resources; missing models must not trigger downloads or a false verification pass.
Six format families and three intensities are seed presets, pending independent
PT-BR/English calibration. No profile weakens word guards, quizzes or meaning.

## Optional window

Breathing remains off unless requested. For approved breath duration changes,
load [breathing guidelines](guidelines-breathing.md). Emit raw-source CMap cut
proposals, preserve cadence and word guards, and remap dependent cues. Never
delete time solely from the dialogue track. Attenuation without a duration
change belongs to `/avo.sound`.

Map `from`/`to` notes to the canonical source units before using
`scope.segmentIds`. Limit heavy analysis to that scope and report coverage; the
structural every-join audit does not imply acoustic inspection of the whole video.
