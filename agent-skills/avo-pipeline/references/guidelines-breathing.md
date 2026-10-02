# Guidelines: --breathing

Load [breath-control.md](../../../docs/breath-control.md) and AGENTS.md audio rules.
This guideline diagnoses and selects a policy; it does not activate treatment.

Breath control is off unless explicitly requested. State the source clock,
speech protection, action, selection, thresholds, exceptions and review gate.
When the user merely asks to reduce breaths, recommend conservative attenuation.
Distinguish suppressing the sound while retaining the pause from removing time.
Do not treat music, SFX, gameplay, sighs or word beginnings as breathing.

Execution belongs to `/avo.sound` or `/avo.pipeline`; approved duration changes
belong to `/avo.trim`. Follow the canonical-only and immutable-review rules.
